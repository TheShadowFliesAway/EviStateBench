#!/usr/bin/env python3
"""Probe local BEHAVIOR / OmniGibson runtime readiness for EviStateBench.

This script is intentionally lightweight and read-only. It checks whether the
current Python environment can see and import BDDL / OmniGibson, whether local
dataset paths are usable, and whether one local task template plus one
tro_state snapshot can support a snapshot-grounded real-data pilot.

It does not launch a simulator window or run a full OmniGibson episode.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "source_audits"

CRITICAL_MODULES = [
    "future",
    "addict",
    "numpy",
    "networkx",
    "yaml",
    "gymnasium",
    "scipy",
    "transforms3d",
    "trimesh",
    "cv2",
    "bddl",
    "omnigibson",
]


def path_summary(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def first_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    return next(iter(sorted(root.rglob(pattern))), None)


def run_probe(
    label: str,
    code: str,
    *,
    pythonpath: list[Path] | None = None,
    extra_env: dict[str, str] | None = None,
    timeout: int = 40,
) -> dict[str, Any]:
    env = os.environ.copy()
    if pythonpath:
        pieces = [str(path) for path in pythonpath]
        if env.get("PYTHONPATH"):
            pieces.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pieces)
    for key, value in (extra_env or {}).items():
        env[key] = value

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "label": label,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip()[-5000:],
            "stderr": proc.stderr.strip()[-5000:],
            "pythonpath": [str(path) for path in pythonpath or []],
            "extra_env": extra_env or {},
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "label": label,
            "ok": False,
            "returncode": None,
            "stdout": stdout[-5000:],
            "stderr": (stderr[-5000:] + "\ntimeout").strip(),
            "pythonpath": [str(path) for path in pythonpath or []],
            "extra_env": extra_env or {},
        }


def ast_literal_list(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    values: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            values.append(item.value)
    return values


def extract_setup_requires(setup_path: Path) -> dict[str, Any]:
    if not setup_path.exists():
        return {"path": str(setup_path), "exists": False, "install_requires": [], "extras": {}}

    tree = ast.parse(setup_path.read_text(encoding="utf-8"))
    install_requires: list[str] = []
    extras: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "setup":
            continue
        for keyword in node.keywords:
            if keyword.arg == "install_requires":
                install_requires = ast_literal_list(keyword.value)
            elif keyword.arg == "extras_require" and isinstance(keyword.value, ast.Dict):
                for key_node, value_node in zip(keyword.value.keys, keyword.value.values):
                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                        extras[key_node.value] = ast_literal_list(value_node)
    return {
        "path": str(setup_path),
        "exists": True,
        "install_requires": install_requires,
        "extras": extras,
    }


def summarize_template(path: Path | None, behavior_root: Path) -> dict[str, Any]:
    if path is None:
        return {"exists": False}
    data = read_json(path)
    task_meta = data.get("metadata", {}).get("task", {})
    init_args = data.get("init_info", {}).get("args", {})
    scene_model = init_args.get("scene_model")
    scene_file = init_args.get("scene_file")
    local_scene_candidates: list[str] = []
    if scene_model:
        scene_json_root = behavior_root / "datasets" / "behavior-1k-assets" / "scenes" / scene_model / "json"
        local_scene_candidates = [str(p) for p in sorted(scene_json_root.glob("*.json"))]

    inst_to_name = task_meta.get("inst_to_name", {})
    robot_poses = task_meta.get("robot_poses", {})
    return {
        "exists": True,
        "path": str(path),
        "top_level_keys": sorted(data.keys()),
        "class_module": data.get("init_info", {}).get("class_module"),
        "class_name": data.get("init_info", {}).get("class_name"),
        "scene_model": scene_model,
        "scene_file": scene_file,
        "scene_file_exists": bool(scene_file and Path(scene_file).exists()),
        "local_scene_json_candidates": local_scene_candidates,
        "object_scope_count": len(inst_to_name) if isinstance(inst_to_name, dict) else 0,
        "robot_pose_types": sorted(robot_poses.keys()) if isinstance(robot_poses, dict) else [],
    }


def summarize_tro_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"exists": False}
    data = read_json(path)
    root_link_fields: Counter[str] = Counter()
    non_kin_states: Counter[str] = Counter()
    object_count = 0
    objects_with_pose = 0
    objects_with_non_kin = 0
    for name, value in data.items():
        if name == "robot_poses" or not isinstance(value, dict):
            continue
        object_count += 1
        root_link = value.get("root_link", {})
        if isinstance(root_link, dict):
            root_link_fields.update(root_link.keys())
            if "pos" in root_link and "ori" in root_link:
                objects_with_pose += 1
        non_kin = value.get("non_kin", {})
        if isinstance(non_kin, dict) and non_kin:
            objects_with_non_kin += 1
            non_kin_states.update(non_kin.keys())

    return {
        "exists": True,
        "path": str(path),
        "object_count": object_count,
        "has_robot_poses": "robot_poses" in data,
        "objects_with_pose": objects_with_pose,
        "objects_with_non_kin": objects_with_non_kin,
        "root_link_fields": root_link_fields.most_common(20),
        "non_kin_states": non_kin_states.most_common(20),
        "direct_observation_types": [
            "OBJECT_EXISTS",
            "OBJECT_POSE_SNAPSHOT",
            "OBJECT_VELOCITY_SNAPSHOT",
            "NUMERIC_OBJECT_STATE",
        ],
    }


def probe_python_runtime(behavior_root: Path, sample_task: str) -> dict[str, Any]:
    og_root = behavior_root / "OmniGibson"
    bddl_root = behavior_root / "bddl3"
    datasets_root = behavior_root / "datasets"
    pythonpath = [og_root, bddl_root]
    og_env = {
        "OMNIGIBSON_DATA_PATH": str(datasets_root),
        "OMNIGIBSON_HEADLESS": "True",
    }

    find_spec_code = f"""
import importlib.util, json
mods = {CRITICAL_MODULES!r}
print(json.dumps({{m: bool(importlib.util.find_spec(m)) for m in mods}}, sort_keys=True))
"""
    import_deps_code = f"""
import importlib, json
mods = {CRITICAL_MODULES[:9]!r}
out = {{}}
for mod in mods:
    try:
        m = importlib.import_module(mod)
        out[mod] = {{"ok": True, "file": getattr(m, "__file__", None)}}
    except Exception as exc:
        out[mod] = {{"ok": False, "error": type(exc).__name__ + ": " + str(exc)}}
print(json.dumps(out, sort_keys=True))
"""
    bddl_conditions_code = f"""
import json
from bddl.activity import Conditions
conds = Conditions({sample_task!r}, 0, "omnigibson")
print(json.dumps({{
    "objects": sum(len(v) for v in conds.parsed_objects.values()),
    "object_categories": len(conds.parsed_objects),
    "init_conditions": len(conds.parsed_initial_conditions),
    "goal_conditions": len(conds.parsed_goal_conditions),
}}, sort_keys=True))
"""
    og_import_code = """
import json
import omnigibson
print(json.dumps({"file": getattr(omnigibson, "__file__", None)}, sort_keys=True))
"""
    og_macros_code = """
import json
from omnigibson.macros import gm
print(json.dumps({
    "data_path": str(gm.DATA_PATH),
    "headless": bool(gm.HEADLESS),
    "enable_object_states": bool(gm.ENABLE_OBJECT_STATES),
}, sort_keys=True))
"""

    return {
        "default_find_spec": run_probe("default_find_spec", find_spec_code),
        "local_path_find_spec": run_probe(
            "local_path_find_spec",
            find_spec_code,
            pythonpath=pythonpath,
            extra_env=og_env,
        ),
        "critical_dependency_imports": run_probe(
            "critical_dependency_imports",
            import_deps_code,
        ),
        "bddl_conditions_import_and_parse": run_probe(
            "bddl_conditions_import_and_parse",
            bddl_conditions_code,
            pythonpath=pythonpath,
            extra_env=og_env,
        ),
        "omnigibson_import": run_probe(
            "omnigibson_import",
            og_import_code,
            pythonpath=pythonpath,
            extra_env=og_env,
        ),
        "omnigibson_macros_import": run_probe(
            "omnigibson_macros_import",
            og_macros_code,
            pythonpath=pythonpath,
            extra_env=og_env,
        ),
    }


def derive_findings(audit: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    probes = audit["runtime_probes"]
    template = audit["sampled_task_template"]
    tro = audit["tro_state_snapshot"]

    if template.get("exists") and tro.get("exists"):
        findings.append("snapshot_pilot_ready: local task template and tro_state snapshot are readable.")
    else:
        findings.append("snapshot_pilot_blocked: missing task template or tro_state snapshot.")

    if template.get("scene_file") and not template.get("scene_file_exists"):
        findings.append(
            "template_scene_file_is_stale: template scene_file is an absolute path that does not exist locally; "
            "use scene_model plus local behavior-1k-assets scene json candidates."
        )

    if probes["bddl_conditions_import_and_parse"]["ok"]:
        findings.append("bddl_runtime_ready: BDDL Conditions can be imported and parsed.")
    else:
        findings.append("bddl_runtime_blocked: BDDL import/parse failed in the current Python environment.")

    if probes["omnigibson_import"]["ok"] and probes["omnigibson_macros_import"]["ok"]:
        findings.append("omnigibson_runtime_ready: OmniGibson import probe passed.")
    else:
        findings.append("omnigibson_runtime_blocked: OmniGibson import probe failed before task loading.")

    return findings


def table_from_dict(data: dict[str, Any]) -> str:
    lines = ["| item | value |", "| --- | --- |"]
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        lines.append(f"| `{key}` | `{text[:500]}` |")
    return "\n".join(lines)


def probe_table(probes: dict[str, dict[str, Any]]) -> str:
    lines = ["| probe | ok | stdout | stderr |", "| --- | --- | --- | --- |"]
    for name, result in probes.items():
        stdout = (result.get("stdout") or "").replace("\n", " ")[:260]
        stderr = (result.get("stderr") or "").replace("\n", " ")[:260]
        lines.append(f"| `{name}` | `{result.get('ok')}` | `{stdout}` | `{stderr}` |")
    return "\n".join(lines)


def build_report(audit: dict[str, Any]) -> str:
    findings = "\n".join(f"- {item}" for item in audit["findings"])
    return f"""# OmniGibson Runtime Probe

本报告由 `real_data_pipeline/stages/runtime_probe.py` 生成。

目标是回答：

```text
当前本地环境是否已经能把 BEHAVIOR / OmniGibson 从“文件可读”推进到“runtime 可用”？
```

## Verdict

{findings}

## Python

{table_from_dict(audit["python"])}

## Path Preflight

{table_from_dict({key: value["exists"] for key, value in audit["paths"].items()})}

## Runtime Probes

{probe_table(audit["runtime_probes"])}

## Sampled Task Template

{table_from_dict(audit["sampled_task_template"])}

## tro_state Snapshot

{table_from_dict(audit["tro_state_snapshot"])}

## Challenge Template

{table_from_dict(audit["challenge_template"])}

## Setup Requirements

### OmniGibson install_requires

```json
{json.dumps(audit["setup_requirements"]["omnigibson"]["install_requires"], indent=2, ensure_ascii=False)}
```

### BDDL install_requires

```json
{json.dumps(audit["setup_requirements"]["bddl"]["install_requires"], indent=2, ensure_ascii=False)}
```

## Interpretation

```text
1. 如果 snapshot_pilot_ready 为真，可以先做不启动 simulator 的真实数据试点：
   task template + tro_state snapshot -> StateObservation candidates。
2. 如果 bddl_runtime_blocked，需要先解决 BDDL Python 依赖，再用 BDDL parser 读取 init / goal / scope。
3. 如果 omnigibson_runtime_blocked，需要先解决 OmniGibson Python 依赖和 Omniverse runtime，再谈 object_state evaluator / simulator truth。
4. tro_state 仍然只是 snapshot，不是完整 temporal rollout；真正 timeline 需要 runtime recorder 或已有 trajectory state dump。
```
"""


def run_audit(behavior_root: Path, sample_task: str) -> dict[str, Any]:
    datasets = behavior_root / "datasets"
    sampled_root = behavior_root / "joylo" / "sampled_task"
    challenge_root = datasets / "2025-challenge-task-instances"
    paths = {
        "behavior_root": path_summary(behavior_root),
        "omnigibson_source": path_summary(behavior_root / "OmniGibson" / "omnigibson"),
        "bddl_source": path_summary(behavior_root / "bddl3" / "bddl"),
        "datasets": path_summary(datasets),
        "behavior_1k_assets": path_summary(datasets / "behavior-1k-assets"),
        "robot_assets": path_summary(datasets / "omnigibson-robot-assets"),
        "challenge_instances": path_summary(challenge_root),
        "sampled_task": path_summary(sampled_root),
    }

    sampled_template = first_file(sampled_root / sample_task, "*_template.json")
    if sampled_template and "-tro_state" in sampled_template.name:
        sampled_template = None
    if sampled_template is None:
        sampled_template = next(
            (p for p in sorted(sampled_root.rglob("*_template.json")) if "-tro_state" not in p.name),
            None,
        )
    tro_state = first_file(sampled_root / sample_task, "*-tro_state.json") or first_file(sampled_root, "*-tro_state.json")
    challenge_template = first_file(challenge_root, "*_template.json")

    audit = {
        "behavior_root": str(behavior_root),
        "sample_task": sample_task,
        "python": {
            "executable": sys.executable,
            "version": sys.version.replace("\n", " "),
            "platform": platform.platform(),
            "cwd": str(REPO_ROOT),
        },
        "paths": paths,
        "setup_requirements": {
            "omnigibson": extract_setup_requires(behavior_root / "OmniGibson" / "setup.py"),
            "bddl": extract_setup_requires(behavior_root / "bddl3" / "setup.py"),
        },
        "runtime_probes": probe_python_runtime(behavior_root, sample_task),
        "sampled_task_template": summarize_template(sampled_template, behavior_root),
        "tro_state_snapshot": summarize_tro_state(tro_state),
        "challenge_template": summarize_template(challenge_template, behavior_root),
    }
    audit["findings"] = derive_findings(audit)
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--sample-task", default="assembling_gift_baskets")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = run_audit(args.behavior_root, args.sample_task)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "omnigibson_runtime_probe.json"
    report_path = args.output_dir / "omnigibson_runtime_probe.md"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(build_report(audit), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(json_path),
                "report": str(report_path),
                "findings": audit["findings"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
