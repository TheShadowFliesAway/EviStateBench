#!/usr/bin/env python3
"""Audit local BEHAVIOR / OmniGibson data sources for EviStateBench.

This script is intentionally read-only.  It does not launch OmniGibson or run
simulation.  The goal is to understand which local files can support a real
data pipeline and which parts still require runtime probing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from itertools import islice
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "source_audits"

TASK_FAMILY_RULES = {
    "cleaning / washing": (
        "clean",
        "wash",
        "wipe",
        "rinse",
        "scrub",
        "sanitize",
        "disinfect",
        "sweep",
        "mop",
    ),
    "cooking / food preparation": (
        "cook",
        "bake",
        "boil",
        "chop",
        "slice",
        "brew",
        "toast",
        "prepare",
        "can_",
        "canning",
    ),
    "storage / organization / packing": (
        "put",
        "pack",
        "box",
        "store",
        "organize",
        "sort",
        "arrange",
        "bring",
        "carry",
    ),
    "liquid / material transfer": (
        "fill",
        "pour",
        "water",
        "adding_chemicals",
        "chlorinating",
        "bottling",
    ),
    "assembly / setup": (
        "assemble",
        "assembling",
        "attach",
        "install",
        "changing",
    ),
}

CORE_PREDICATES = {
    "inside",
    "contains",
    "ontop",
    "nextto",
    "under",
    "overlaid",
    "covered",
    "filled",
    "saturated",
    "cooked",
    "frozen",
    "open",
    "folded",
    "unfolded",
    "toggled_on",
    "hot",
    "on_fire",
    "broken",
    "attached",
    "draped",
    "touching",
    "grasped",
}

LOGICAL_FORMS = {
    "and",
    "or",
    "not",
    "exists",
    "forall",
    "imply",
    "implies",
    "when",
    "forn",
    "forpairs",
    "fornpairs",
    "for-pairs",
    "for-n-pairs",
}


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def path_summary(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
    }


def first_paths(root: Path, pattern: str, limit: int = 5) -> list[str]:
    if not root.exists():
        return []
    return [str(path) for path in islice(sorted(root.rglob(pattern)), limit)]


def count_paths(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob(pattern))


def shallow_child_count(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"dirs": 0, "files": 0}
    dirs = 0
    files = 0
    for child in path.iterdir():
        if child.is_dir():
            dirs += 1
        elif child.is_file():
            files += 1
    return {"dirs": dirs, "files": files}


def categorize_task_family(task_name: str) -> str:
    for family, needles in TASK_FAMILY_RULES.items():
        if any(needle in task_name for needle in needles):
            return family
    return "other / mixed"


def scan_tokens(path: Path) -> list[Any]:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r";.*$", "", raw, flags=re.MULTILINE).lower()
    stack: list[list[Any]] = []
    tokens: list[Any] = []
    for token in re.findall(r"[()]|[^\s()]+", raw):
        if token == "(":
            stack.append(tokens)
            tokens = []
        elif token == ")":
            if not stack:
                raise ValueError(f"Missing open parenthesis in {path}")
            expr = tokens
            tokens = stack.pop()
            tokens.append(expr)
        else:
            tokens.append(token)
    if stack or len(tokens) != 1:
        raise ValueError(f"Malformed BDDL expression in {path}")
    return tokens[0]


def parse_domain_predicates(domain_path: Path) -> set[str]:
    if not domain_path.exists():
        return set()
    tokens = scan_tokens(domain_path)
    predicates: set[str] = set()
    for group in tokens:
        if isinstance(group, list) and group and group[0] == ":predicates":
            for pred in group[1:]:
                if isinstance(pred, list) and pred:
                    predicates.add(str(pred[0]))
    return predicates


def extract_predicates(
    expr: Any,
    predicate_names: set[str],
    section: str,
    polarity: bool = True,
) -> list[tuple[str, int, str, bool]]:
    if not isinstance(expr, list) or not expr:
        return []
    head = expr[0]
    if head == "not" and len(expr) > 1:
        return extract_predicates(expr[1], predicate_names, section, not polarity)
    if isinstance(head, str) and head in predicate_names:
        args = [arg for arg in expr[1:] if not isinstance(arg, list)]
        return [(head, len(args), section, polarity)]
    children = expr[1:] if isinstance(head, str) and head in LOGICAL_FORMS else expr
    out: list[tuple[str, int, str, bool]] = []
    for child in children:
        out.extend(extract_predicates(child, predicate_names, section, polarity))
    return out


def parse_problem_predicates(path: Path, predicate_names: set[str]) -> list[tuple[str, int, str, bool]]:
    tokens = scan_tokens(path)
    out: list[tuple[str, int, str, bool]] = []
    for group in tokens:
        if not isinstance(group, list) or not group:
            continue
        if group[0] == ":init":
            for expr in group[1:]:
                out.extend(extract_predicates(expr, predicate_names, "init"))
        elif group[0] == ":goal" and len(group) > 1:
            out.extend(extract_predicates(group[1], predicate_names, "goal"))
    return out


def audit_bddl(behavior_root: Path) -> dict[str, Any]:
    activity_root = behavior_root / "bddl3" / "bddl" / "activity_definitions"
    domain_path = activity_root / "domain_omnigibson.bddl"
    problem_files = sorted(activity_root.glob("*/problem*.bddl")) if activity_root.exists() else []
    task_dirs = sorted({path.parent for path in problem_files})
    predicate_names = parse_domain_predicates(domain_path)

    family_counter = Counter(categorize_task_family(path.parent.name) for path in problem_files)
    predicate_counter: Counter[str] = Counter()
    section_counter: Counter[str] = Counter()
    arity_counter: Counter[str] = Counter()
    parse_errors: list[str] = []
    for path in problem_files:
        try:
            for name, arity, section, polarity in parse_problem_predicates(path, predicate_names):
                predicate_counter[name] += 1
                section_counter[f"{section}:{'positive' if polarity else 'negative'}"] += 1
                arity_counter[str(arity)] += 1
        except Exception as exc:  # pragma: no cover - diagnostic path
            parse_errors.append(f"{path}: {exc}")

    return {
        "activity_root": str(activity_root),
        "domain_path": str(domain_path),
        "problem_files": len(problem_files),
        "task_dirs": len(task_dirs),
        "domain_predicates": len(predicate_names),
        "core_predicates_in_domain": sorted(CORE_PREDICATES & predicate_names),
        "missing_core_predicates": sorted(CORE_PREDICATES - predicate_names),
        "problem_count_by_family": dict(family_counter),
        "top_predicates": predicate_counter.most_common(30),
        "section_counts": dict(section_counter),
        "arity_counts": dict(arity_counter),
        "parse_error_count": len(parse_errors),
        "parse_error_sample": parse_errors[:10],
        "sample_problem_files": [str(path) for path in problem_files[:10]],
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl_sample(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            if len(rows) >= limit:
                break
            if line.strip():
                rows.append(json.loads(line))
    return rows


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def audit_challenge_instances(behavior_root: Path) -> dict[str, Any]:
    root = behavior_root / "datasets" / "2025-challenge-task-instances"
    scenes_root = root / "scenes"
    metadata_root = root / "metadata"
    template_files = sorted(scenes_root.rglob("*_template.json")) if scenes_root.exists() else []
    partial_room_files = sorted(scenes_root.rglob("*_template-partial_rooms.json")) if scenes_root.exists() else []
    scene_counter = Counter(path.parts[-3] for path in template_files if len(path.parts) >= 3)
    episodes_path = metadata_root / "episodes.jsonl"
    episode_samples = read_jsonl_sample(episodes_path, limit=5)
    task_counter: Counter[str] = Counter()
    for row in read_jsonl_sample(episodes_path, limit=200):
        for task in row.get("tasks", []):
            task_counter[task] += 1

    return {
        "root": str(root),
        "exists": root.exists(),
        "metadata_files": sorted(path.name for path in metadata_root.glob("*")) if metadata_root.exists() else [],
        "episodes_jsonl_rows": count_jsonl(episodes_path),
        "episodes_sample": episode_samples,
        "template_json_count": len(template_files),
        "partial_room_json_count": len(partial_room_files),
        "scene_counts": dict(scene_counter),
        "sample_template_files": [str(path) for path in template_files[:10]],
        "sample_tasks_from_episodes": task_counter.most_common(10),
    }


def audit_sampled_tasks(behavior_root: Path, sample_limit: int) -> dict[str, Any]:
    root = behavior_root / "joylo" / "sampled_task"
    task_dirs = [path for path in root.iterdir() if path.is_dir()] if root.exists() else []
    template_files = sorted(
        path for path in root.rglob("*_template.json") if "-tro_state" not in path.name
    ) if root.exists() else []
    partial_room_files = sorted(root.rglob("*_template-partial_rooms.json")) if root.exists() else []
    tro_files = sorted(root.rglob("*-tro_state.json")) if root.exists() else []

    object_count_values: list[int] = []
    non_kin_counter: Counter[str] = Counter()
    root_link_counter: Counter[str] = Counter()
    tro_parse_errors: list[str] = []
    for path in tro_files[:sample_limit]:
        try:
            row = read_json(path)
        except Exception as exc:  # pragma: no cover - diagnostic path
            tro_parse_errors.append(f"{path}: {exc}")
            continue
        object_count_values.append(len(row))
        for obj_state in row.values():
            if isinstance(obj_state, dict):
                root_link = obj_state.get("root_link", {})
                if isinstance(root_link, dict):
                    root_link_counter.update(root_link.keys())
                non_kin = obj_state.get("non_kin", {})
                if isinstance(non_kin, dict):
                    non_kin_counter.update(non_kin.keys())

    inst_to_name_counts: list[int] = []
    template_parse_errors: list[str] = []
    for path in template_files[:sample_limit]:
        try:
            row = read_json(path)
            inst_to_name = row.get("metadata", {}).get("task", {}).get("inst_to_name", {})
            if isinstance(inst_to_name, dict):
                inst_to_name_counts.append(len(inst_to_name))
        except Exception as exc:  # pragma: no cover - diagnostic path
            template_parse_errors.append(f"{path}: {exc}")

    return {
        "root": str(root),
        "exists": root.exists(),
        "task_dirs": len(task_dirs),
        "template_json_count": len(template_files),
        "partial_room_json_count": len(partial_room_files),
        "tro_state_json_count": len(tro_files),
        "sample_template_files": [str(path) for path in template_files[:10]],
        "sample_tro_state_files": [str(path) for path in tro_files[:10]],
        "sampled_tro_files": min(sample_limit, len(tro_files)),
        "tro_object_count_min": min(object_count_values) if object_count_values else 0,
        "tro_object_count_max": max(object_count_values) if object_count_values else 0,
        "tro_object_count_avg": (
            sum(object_count_values) / len(object_count_values)
            if object_count_values
            else 0.0
        ),
        "template_object_scope_min": min(inst_to_name_counts) if inst_to_name_counts else 0,
        "template_object_scope_max": max(inst_to_name_counts) if inst_to_name_counts else 0,
        "template_object_scope_avg": (
            sum(inst_to_name_counts) / len(inst_to_name_counts)
            if inst_to_name_counts
            else 0.0
        ),
        "top_non_kin_states": non_kin_counter.most_common(30),
        "root_link_fields": root_link_counter.most_common(20),
        "tro_parse_error_count": len(tro_parse_errors),
        "tro_parse_error_sample": tro_parse_errors[:5],
        "template_parse_error_count": len(template_parse_errors),
        "template_parse_error_sample": template_parse_errors[:5],
    }


def audit_omnigibson_source(behavior_root: Path) -> dict[str, Any]:
    og_root = behavior_root / "OmniGibson"
    og_pkg = og_root / "omnigibson"
    object_states_root = og_pkg / "object_states"
    tasks_root = og_pkg / "tasks"
    object_state_files = sorted(
        path for path in object_states_root.glob("*.py") if not path.name.startswith("__")
    ) if object_states_root.exists() else []
    task_files = sorted(path.name for path in tasks_root.glob("*.py")) if tasks_root.exists() else []
    module_names = [path.stem for path in object_state_files]

    likely_core_modules = sorted(
        module
        for module in module_names
        if module
        in {
            "inside",
            "contains",
            "on_top",
            "next_to",
            "under",
            "overlaid",
            "covered",
            "filled",
            "cooked",
            "frozen",
            "open_state",
            "folded",
            "attached_to",
            "draped",
            "contact_bodies",
            "contact_particles",
            "heated",
            "on_fire",
        }
    )

    return {
        "omnigibson_root": str(og_root),
        "package_root": str(og_pkg),
        "exists": og_pkg.exists(),
        "object_state_module_count": len(object_state_files),
        "object_state_modules": module_names,
        "likely_core_state_modules": likely_core_modules,
        "task_modules": task_files,
        "behavior_task_path": str(tasks_root / "behavior_task.py"),
    }


def audit_assets(behavior_root: Path) -> dict[str, Any]:
    datasets_root = behavior_root / "datasets"
    behavior_assets = datasets_root / "behavior-1k-assets"
    robot_assets = datasets_root / "omnigibson-robot-assets"
    return {
        "datasets_root": path_summary(datasets_root),
        "behavior_1k_assets": {
            **path_summary(behavior_assets),
            "objects_shallow": shallow_child_count(behavior_assets / "objects"),
            "scenes_shallow": shallow_child_count(behavior_assets / "scenes"),
            "systems_shallow": shallow_child_count(behavior_assets / "systems"),
        },
        "robot_assets": {
            **path_summary(robot_assets),
            "models_shallow": shallow_child_count(robot_assets / "models"),
        },
    }


def run_probe(
    label: str,
    code: str,
    *,
    pythonpath: list[Path] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    env = os.environ.copy()
    if pythonpath:
        existing = env.get("PYTHONPATH")
        pieces = [str(path) for path in pythonpath]
        if existing:
            pieces.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(pieces)
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
            "stdout": proc.stdout.strip()[-2000:],
            "stderr": proc.stderr.strip()[-2000:],
            "pythonpath": [str(path) for path in pythonpath or []],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "ok": False,
            "returncode": None,
            "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr": "timeout",
            "pythonpath": [str(path) for path in pythonpath or []],
        }


def audit_imports(behavior_root: Path) -> dict[str, Any]:
    og_root = behavior_root / "OmniGibson"
    bddl_root = behavior_root / "bddl3"
    find_spec_code = """
import importlib.util, json
mods = ["omnigibson", "bddl"]
print(json.dumps({m: bool(importlib.util.find_spec(m)) for m in mods}, sort_keys=True))
"""
    bddl_import_code = """
import bddl, json
print(json.dumps({"file": getattr(bddl, "__file__", None)}, sort_keys=True))
"""
    og_import_code = """
import omnigibson, json
print(json.dumps({"file": getattr(omnigibson, "__file__", None)}, sort_keys=True))
"""
    return {
        "default_find_spec": run_probe("default_find_spec", find_spec_code),
        "local_path_find_spec": run_probe(
            "local_path_find_spec",
            find_spec_code,
            pythonpath=[og_root, bddl_root],
        ),
        "local_path_import_bddl": run_probe(
            "local_path_import_bddl",
            bddl_import_code,
            pythonpath=[og_root, bddl_root],
        ),
        "local_path_import_omnigibson": run_probe(
            "local_path_import_omnigibson",
            og_import_code,
            pythonpath=[og_root, bddl_root],
        ),
    }


def top_rows(items: list[tuple[Any, Any]], limit: int = 12) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in items[:limit]:
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def dict_rows(data: dict[str, Any]) -> str:
    lines = ["| item | value |", "| --- | --- |"]
    for key, value in data.items():
        lines.append(f"| `{key}` | `{value}` |")
    if len(lines) == 2:
        lines.append("| n/a | n/a |")
    return "\n".join(lines)


def probe_rows(probes: dict[str, dict[str, Any]]) -> str:
    lines = ["| probe | process ok | stdout | stderr |", "| --- | --- | --- | --- |"]
    for name, result in probes.items():
        stdout = (result.get("stdout") or "").replace("\n", " ")[:180]
        stderr = (result.get("stderr") or "").replace("\n", " ")[:180]
        lines.append(f"| `{name}` | `{result.get('ok')}` | `{stdout}` | `{stderr}` |")
    return "\n".join(lines)


def build_report(audit: dict[str, Any]) -> str:
    paths = audit["paths"]
    bddl = audit["bddl"]
    challenge = audit["challenge_instances"]
    sampled = audit["sampled_tasks"]
    og = audit["omnigibson_source"]
    assets = audit["assets"]
    imports = audit["imports"]

    return f"""# BEHAVIOR / OmniGibson Local Source Audit

本报告由 `real_data_pipeline/stages/source_audit.py` 生成。

目标是回答一个问题：

```text
本地 BEHAVIOR / OmniGibson 里哪些数据源可以支撑 EviStateBench 的真实数据 pipeline？
```

## Path Summary

{dict_rows({key: value["exists"] for key, value in paths.items()})}

## Import Probe

{probe_rows(imports)}

解释：

- `default_find_spec` 表示当前 Python 环境是否直接能找到模块。
- `local_path_find_spec` 表示加上本地 `OmniGibson` / `bddl3` 源码路径后是否能找到模块。
- `local_path_import_bddl` 和 `local_path_import_omnigibson` 是轻量真实 import probe。
- 表中的 `process ok` 只表示探针脚本是否正常退出；模块是否可用要看 `stdout` 或 import probe 是否成功。

## BDDL Task Definitions

| item | value |
| --- | ---: |
| problem files | {bddl["problem_files"]} |
| task dirs | {bddl["task_dirs"]} |
| domain predicates | {bddl["domain_predicates"]} |
| parse errors | {bddl["parse_error_count"]} |

### Problem Count by Family

{top_rows(list(bddl["problem_count_by_family"].items()), 20)}

### Top BDDL Predicates

{top_rows(bddl["top_predicates"], 20)}

### Core Predicate Coverage

可在 BDDL domain 中找到的 v0 core predicates：

```text
{", ".join(bddl["core_predicates_in_domain"])}
```

暂未在 BDDL domain 中找到的 v0 core predicates：

```text
{", ".join(bddl["missing_core_predicates"]) or "none"}
```

## 2025 Challenge Task Instances

| item | value |
| --- | ---: |
| episodes rows | {challenge["episodes_jsonl_rows"]} |
| template json | {challenge["template_json_count"]} |
| partial-room json | {challenge["partial_room_json_count"]} |

### Scene Counts

{top_rows(list(challenge["scene_counts"].items()), 20)}

### Sample Episode Tasks

{top_rows(challenge["sample_tasks_from_episodes"], 10)}

## joylo/sampled_task

| item | value |
| --- | ---: |
| task dirs | {sampled["task_dirs"]} |
| template json | {sampled["template_json_count"]} |
| partial-room json | {sampled["partial_room_json_count"]} |
| tro_state json | {sampled["tro_state_json_count"]} |
| sampled tro files | {sampled["sampled_tro_files"]} |
| tro objects min | {sampled["tro_object_count_min"]} |
| tro objects avg | {sampled["tro_object_count_avg"]:.2f} |
| tro objects max | {sampled["tro_object_count_max"]} |
| template object scope min | {sampled["template_object_scope_min"]} |
| template object scope avg | {sampled["template_object_scope_avg"]:.2f} |
| template object scope max | {sampled["template_object_scope_max"]} |

### tro_state Root Link Fields

{top_rows(sampled["root_link_fields"], 20)}

### tro_state Non-Kinematic States

{top_rows(sampled["top_non_kin_states"], 20)}

解释：

`*-tro_state.json` 看起来是 task-relevant object snapshot。它能提供 object existence、pose、velocity、temperature 等状态，但它本身不是完整执行轨迹。spatial relation / containment / goal satisfaction 仍需要通过 OmniGibson object state 或 BDDL predicate evaluator 从 snapshot/runtime 中计算。

## OmniGibson Source

| item | value |
| --- | ---: |
| object state modules | {og["object_state_module_count"]} |

### Likely Useful Object-State Modules

```text
{", ".join(og["likely_core_state_modules"])}
```

### Task Modules

```text
{", ".join(og["task_modules"])}
```

## Assets

### behavior-1k-assets

| subtree | dirs | files |
| --- | ---: | ---: |
| objects | {assets["behavior_1k_assets"]["objects_shallow"]["dirs"]} | {assets["behavior_1k_assets"]["objects_shallow"]["files"]} |
| scenes | {assets["behavior_1k_assets"]["scenes_shallow"]["dirs"]} | {assets["behavior_1k_assets"]["scenes_shallow"]["files"]} |
| systems | {assets["behavior_1k_assets"]["systems_shallow"]["dirs"]} | {assets["behavior_1k_assets"]["systems_shallow"]["files"]} |

### omnigibson-robot-assets

| subtree | dirs | files |
| --- | ---: | ---: |
| models | {assets["robot_assets"]["models_shallow"]["dirs"]} | {assets["robot_assets"]["models_shallow"]["files"]} |

## What This Means for EviStateBench

可以立即用于真实数据 pipeline 的部分：

```text
1. BDDL task definitions: 任务目标、predicate vocabulary、object scope。
2. 2025 challenge task instance templates: 已采样的 scene/task instance 配置。
3. joylo sampled_task templates: 可读的 task instance 配置和 object mapping。
4. joylo tro_state snapshots: task-relevant object state snapshot，可做 snapshot-grounded pilot。
5. OmniGibson object_state source: 说明 inside / on_top / filled / cooked 等 predicate 有 runtime evaluator 入口。
```

还不能直接宣称为真实 temporal rollout 的部分：

```text
1. tro_state 是 snapshot，不是完整执行时间序列。
2. BDDL init/goal 仍只是任务规范，不是执行轨迹。
3. 真正的 temporal state timeline 需要 OmniGibson runtime recorder 或已有 trajectory/state dump。
```

建议下一步：

```text
1. 做 `runtime_probe.py`：验证本地 PYTHONPATH + dataset path 后能否加载一个 task instance。
2. 做 `static_observation_audit.py`：从 tro_state snapshot 中抽取可确定的 StateObservation 类型。
3. 再做 real hidden timeline recorder：从 OmniGibson runtime object_states / BDDL goal evaluation 生成 temporal events。
```
"""


def build_audit(behavior_root: Path, sample_limit: int) -> dict[str, Any]:
    paths = {
        "behavior_root": path_summary(behavior_root),
        "omnigibson_source": path_summary(behavior_root / "OmniGibson" / "omnigibson"),
        "bddl_source": path_summary(behavior_root / "bddl3" / "bddl"),
        "bddl_activity_definitions": path_summary(
            behavior_root / "bddl3" / "bddl" / "activity_definitions"
        ),
        "datasets": path_summary(behavior_root / "datasets"),
        "behavior_1k_assets": path_summary(behavior_root / "datasets" / "behavior-1k-assets"),
        "robot_assets": path_summary(behavior_root / "datasets" / "omnigibson-robot-assets"),
        "challenge_instances": path_summary(
            behavior_root / "datasets" / "2025-challenge-task-instances"
        ),
        "joylo_sampled_task": path_summary(behavior_root / "joylo" / "sampled_task"),
    }
    return {
        "behavior_root": str(behavior_root),
        "sample_limit": sample_limit,
        "paths": paths,
        "imports": audit_imports(behavior_root),
        "bddl": audit_bddl(behavior_root),
        "challenge_instances": audit_challenge_instances(behavior_root),
        "sampled_tasks": audit_sampled_tasks(behavior_root, sample_limit=sample_limit),
        "omnigibson_source": audit_omnigibson_source(behavior_root),
        "assets": audit_assets(behavior_root),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit local BEHAVIOR / OmniGibson data sources.")
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample-limit", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = build_audit(args.behavior_root, sample_limit=args.sample_limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "behavior_sources_audit.json"
    md_path = args.output_dir / "behavior_sources_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_report(audit), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(json_path),
                "report": str(md_path),
                "bddl_problem_files": audit["bddl"]["problem_files"],
                "challenge_templates": audit["challenge_instances"]["template_json_count"],
                "sampled_task_templates": audit["sampled_tasks"]["template_json_count"],
                "tro_state_json": audit["sampled_tasks"]["tro_state_json_count"],
                "probe_process_ok": {
                    name: result["ok"]
                    for name, result in audit["imports"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
