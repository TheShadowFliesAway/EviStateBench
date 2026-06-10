#!/usr/bin/env python3
"""Audit what StateObservation candidates can be extracted from tro_state files.

This is a bidirectional audit:

1. Data -> schema:
   Inspect local ``*-tro_state.json`` snapshots and summarize which fields can
   become StateObservation evidence.

2. Schema -> data:
   Check each StateObservation field and explain whether tro_state can provide
   it directly, requires a deterministic derivation, or cannot provide it.

The script is read-only with respect to BEHAVIOR / OmniGibson data. It writes
reports under ``real_data_pipeline/artifacts/source_audits*``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import fields
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evistatebench.schema import (  # noqa: E402
    CORE_STATE_PREDICATES_V0,
    PREDICATE_CATEGORY_V0,
    StateObservation,
    is_json_value,
)


DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "source_audits"

OBJECT_NAME_RE = re.compile(r"^(?P<synset>.+)_\d+$")
SNAPSHOT_INDEX_RE = re.compile(r"_(?P<index>\d+)_template-tro_state\.json$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def camel_to_snake(name: str) -> str:
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.lower()


def task_id_from_path(path: Path, sampled_root: Path) -> str:
    try:
        return path.relative_to(sampled_root).parts[0]
    except Exception:
        return "unknown_task"


def snapshot_index_from_path(path: Path) -> int | None:
    match = SNAPSHOT_INDEX_RE.search(path.name)
    if not match:
        return None
    return int(match.group("index"))


def object_synset(object_id: str) -> str:
    match = OBJECT_NAME_RE.match(object_id)
    return match.group("synset") if match else object_id


def value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "null"
    return type(value).__name__


def iter_scalar_leaves(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        out: list[tuple[tuple[str, ...], Any]] = []
        for key, child in value.items():
            out.extend(iter_scalar_leaves(child, prefix + (str(key),)))
        return out
    if isinstance(value, (bool, int, float, str)) or value is None:
        return [(prefix, value)]
    return [(prefix, value)]


def classify_non_kin_leaf(state_name: str, leaf_path: tuple[str, ...], value: Any) -> dict[str, Any]:
    """Classify one non_kin leaf into a possible observation mapping."""
    field_name = leaf_path[-1] if leaf_path else "value"
    state_snake = camel_to_snake(state_name)
    field_snake = camel_to_snake(field_name)
    leaf_key = f"{state_name}.{'.'.join(leaf_path)}"

    if state_name == "ToggledOn" and field_name == "value":
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": "toggled_on",
            "candidate_category": PREDICATE_CATEGORY_V0.get("toggled_on", "unknown"),
            "schema_status": "direct_bool_core_predicate",
            "reason": "bool leaf directly matches BDDL core predicate toggled_on(object).",
        }

    if state_name == "Temperature" and field_name == "temperature":
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": "temperature",
            "candidate_category": "numeric object state",
            "schema_status": "direct_numeric_measurement",
            "reason": "float leaf fits observed_value and maps to numeric object state.",
        }

    if state_name == "MaxTemperature" and field_name == "max_temperature":
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": "max_temperature",
            "candidate_category": "numeric simulator/object diagnostic",
            "schema_status": "direct_numeric_diagnostic",
            "reason": "float leaf fits observed_value, but it is more diagnostic than task-state predicate.",
        }

    if state_name == "AttachedTo" and field_name == "attached_obj_uuid":
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": "attached",
            "candidate_category": PREDICATE_CATEGORY_V0.get("attached", "unknown"),
            "schema_status": "blocked_target_mapping_missing",
            "reason": "attached requires object-object arguments; tro_state stores an internal uuid and all observed samples are -1.",
        }

    if state_name == "Saturated" and field_name == "n_systems":
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": "saturated",
            "candidate_category": PREDICATE_CATEGORY_V0.get("saturated", "unknown"),
            "schema_status": "proxy_numeric_needs_semantic_policy",
            "reason": "n_systems may support saturated(object, substance), but BDDL predicate semantics need runtime/evaluator policy.",
        }

    if state_name in {"ParticleApplier", "ParticleRemover", "ModifiedParticles"}:
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": f"{state_snake}_{field_snake}",
            "candidate_category": "particle/process diagnostic",
            "schema_status": "direct_scalar_but_likely_internal_process_state",
            "reason": "scalar fits StateObservation, but this is simulator process bookkeeping unless mapped to task predicate.",
        }

    if state_name == "SlicerActive" and field_name == "value":
        return {
            "leaf_key": leaf_key,
            "candidate_predicate": "slicer_active",
            "candidate_category": "tool/action state",
            "schema_status": "direct_bool_tool_state",
            "reason": "bool leaf fits observed_value and maps to tool/action state.",
        }

    if isinstance(value, bool):
        status = "direct_bool_but_taxonomy_missing"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        status = "direct_numeric_but_taxonomy_missing"
    elif isinstance(value, str):
        status = "direct_categorical_but_taxonomy_missing"
    else:
        status = "not_supported_by_current_observed_value"

    return {
        "leaf_key": leaf_key,
        "candidate_predicate": state_snake if field_snake == "value" else f"{state_snake}_{field_snake}",
        "candidate_category": "unknown",
        "schema_status": status,
        "reason": "generic non_kin leaf; mapping needs task-state semantics.",
    }


def summarize_values(values: list[Any], limit: int = 8) -> dict[str, Any]:
    counter = Counter(json.dumps(v, sort_keys=True) for v in values[:5000])
    numeric = [
        float(v)
        for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    summary: dict[str, Any] = {
        "sample_values": [json.loads(item) for item, _ in counter.most_common(limit)],
        "distinct_sample_values": len(counter),
    }
    if numeric:
        summary.update({"min": min(numeric), "max": max(numeric), "avg": mean(numeric)})
    return summary


def make_sample_observation(
    *,
    path: Path,
    sampled_root: Path,
    object_id: str,
    predicate_name: str,
    value: Any,
    evidence_suffix: str,
    sample_index: int,
    observation_kind: str = "predicate_state",
) -> StateObservation:
    task_id = task_id_from_path(path, sampled_root)
    snap_index = snapshot_index_from_path(path)
    event_time = float(snap_index if snap_index is not None else sample_index)
    return StateObservation(
        obs_id=f"tro_audit_obs_{sample_index:05d}",
        episode_id=f"tro_snapshot__{task_id}__{path.stem}",
        task_id=task_id,
        event_time=event_time,
        arrival_time=event_time,
        source="tro_state_snapshot",
        predicate_name=predicate_name,
        arguments=(object_id,),
        observed_value=value,
        confidence=1.0,
        observation_kind=observation_kind,
        evidence_ref=f"{path}:{object_id}:{evidence_suffix}",
        polarity="support",
        metadata={
            "source_file": str(path),
            "source_format": "tro_state",
            "time_policy": "event_time_from_filename_snapshot_index_or_scan_order",
            "confidence_policy": "simulator_snapshot_default_1.0",
        },
    )


def audit_tro_state(behavior_root: Path, max_files: int, sample_observation_limit: int) -> dict[str, Any]:
    sampled_root = behavior_root / "joylo" / "sampled_task"
    template_tasks = sorted(
        {
            path.parent.name
            for path in sampled_root.glob("*/*_template.json")
            if "-tro_state" not in path.name
        }
    ) if sampled_root.exists() else []
    all_files = sorted(sampled_root.rglob("*-tro_state.json")) if sampled_root.exists() else []
    files = all_files[:max_files] if max_files > 0 else all_files

    task_counter: Counter[str] = Counter()
    object_synset_counter: Counter[str] = Counter()
    object_entry_key_counter: Counter[str] = Counter()
    root_link_field_counter: Counter[str] = Counter()
    root_link_value_kind_counter: Counter[str] = Counter()
    joint_field_counter: Counter[str] = Counter()
    robot_pose_type_counter: Counter[str] = Counter()
    non_kin_state_counter: Counter[str] = Counter()
    non_kin_leaf_counter: Counter[str] = Counter()
    non_kin_leaf_kind_counter: Counter[str] = Counter()
    non_kin_values: dict[str, list[Any]] = defaultdict(list)
    attached_uuid_counter: Counter[str] = Counter()
    parse_errors: list[str] = []
    object_counts: list[int] = []
    objects_with_pose = 0
    objects_with_velocity = 0
    objects_with_non_kin = 0
    object_total = 0
    candidate_counts: Counter[str] = Counter()
    candidate_status_counter: Counter[str] = Counter()
    leaf_classifications: dict[str, dict[str, Any]] = {}
    sample_observations: list[dict[str, Any]] = []

    for file_index, path in enumerate(files):
        task_id = task_id_from_path(path, sampled_root)
        task_counter[task_id] += 1
        try:
            row = read_json(path)
        except Exception as exc:  # pragma: no cover - diagnostic path
            parse_errors.append(f"{path}: {exc}")
            continue

        object_count = 0
        robot_poses = row.get("robot_poses")
        if isinstance(robot_poses, dict):
            for robot_type, poses in robot_poses.items():
                count = len(poses) if isinstance(poses, list) else 1
                robot_pose_type_counter[str(robot_type)] += count
                candidate_counts["ROBOT_POSE_SNAPSHOT"] += count

        for object_id, object_state in row.items():
            if object_id == "robot_poses" or not isinstance(object_state, dict):
                continue
            object_count += 1
            object_total += 1
            object_synset_counter[object_synset(object_id)] += 1
            object_entry_key_counter.update(object_state.keys())
            candidate_counts["OBJECT_EXISTS"] += 1

            if len(sample_observations) < sample_observation_limit:
                obs = make_sample_observation(
                    path=path,
                    sampled_root=sampled_root,
                    object_id=object_id,
                    predicate_name="object_exists",
                    value=True,
                    evidence_suffix="exists",
                    sample_index=len(sample_observations),
                    observation_kind="object_existence",
                )
                sample_observations.append(obs.to_dict())

            root_link = object_state.get("root_link")
            if isinstance(root_link, dict):
                root_link_field_counter.update(root_link.keys())
                for field_name, value in root_link.items():
                    root_link_value_kind_counter[f"{field_name}:{value_kind(value)}"] += 1
                if "pos" in root_link and "ori" in root_link:
                    objects_with_pose += 1
                    candidate_counts["OBJECT_POSE_SNAPSHOT"] += 1
                    if len(sample_observations) < sample_observation_limit:
                        obs = make_sample_observation(
                            path=path,
                            sampled_root=sampled_root,
                            object_id=object_id,
                            predicate_name="object_pose",
                            value={"pos": root_link["pos"], "ori": root_link["ori"]},
                            evidence_suffix="root_link.pose",
                            sample_index=len(sample_observations),
                            observation_kind="object_pose",
                        )
                        sample_observations.append(obs.to_dict())
                if "lin_vel" in root_link or "ang_vel" in root_link:
                    objects_with_velocity += 1
                    candidate_counts["OBJECT_VELOCITY_SNAPSHOT"] += 1
                    if len(sample_observations) < sample_observation_limit:
                        obs = make_sample_observation(
                            path=path,
                            sampled_root=sampled_root,
                            object_id=object_id,
                            predicate_name="object_velocity",
                            value={
                                key: root_link[key]
                                for key in ("lin_vel", "ang_vel")
                                if key in root_link
                            },
                            evidence_suffix="root_link.velocity",
                            sample_index=len(sample_observations),
                            observation_kind="object_velocity",
                        )
                        sample_observations.append(obs.to_dict())

            for joint_field in ("joint_pos", "joint_vel"):
                if joint_field in object_state:
                    joint_field_counter[f"{joint_field}:{value_kind(object_state[joint_field])}"] += 1
                    candidate_counts["JOINT_STATE_SNAPSHOT"] += 1
            if ("joint_pos" in object_state or "joint_vel" in object_state) and len(sample_observations) < sample_observation_limit:
                obs = make_sample_observation(
                    path=path,
                    sampled_root=sampled_root,
                    object_id=object_id,
                    predicate_name="joint_state",
                    value={
                        key: object_state[key]
                        for key in ("joint_pos", "joint_vel")
                        if key in object_state
                    },
                    evidence_suffix="joint_state",
                    sample_index=len(sample_observations),
                    observation_kind="joint_state",
                )
                sample_observations.append(obs.to_dict())

            non_kin = object_state.get("non_kin")
            if isinstance(non_kin, dict) and non_kin:
                objects_with_non_kin += 1
                for state_name, state_value in non_kin.items():
                    non_kin_state_counter[state_name] += 1
                    for leaf_path, leaf_value in iter_scalar_leaves(state_value):
                        leaf_key = f"{state_name}.{'.'.join(leaf_path) if leaf_path else 'value'}"
                        non_kin_leaf_counter[leaf_key] += 1
                        non_kin_leaf_kind_counter[f"{leaf_key}:{value_kind(leaf_value)}"] += 1
                        if len(non_kin_values[leaf_key]) < 1000:
                            non_kin_values[leaf_key].append(leaf_value)
                        classification = classify_non_kin_leaf(state_name, leaf_path, leaf_value)
                        leaf_classifications.setdefault(leaf_key, classification)
                        candidate_status_counter[classification["schema_status"]] += 1
                        if state_name == "AttachedTo" and leaf_path == ("attached_obj_uuid",):
                            attached_uuid_counter[str(leaf_value)] += 1

                        if is_json_value(leaf_value) and len(sample_observations) < sample_observation_limit:
                            kind = "predicate_state"
                            if classification["schema_status"].startswith("direct_numeric"):
                                kind = "numeric_state"
                            elif classification["schema_status"].startswith("direct_bool"):
                                kind = "categorical_state"
                            elif classification["schema_status"].startswith("direct_scalar_but"):
                                kind = "simulator_diagnostic"
                            obs = make_sample_observation(
                                path=path,
                                sampled_root=sampled_root,
                                object_id=object_id,
                                predicate_name=classification["candidate_predicate"],
                                value=leaf_value,
                                evidence_suffix=f"non_kin.{leaf_key}",
                                sample_index=len(sample_observations),
                                observation_kind=kind,
                            )
                            sample_observations.append(obs.to_dict())

        object_counts.append(object_count)

    non_kin_leaf_summaries = {
        key: {
            "count": non_kin_leaf_counter[key],
            "value_kinds": {
                kind.split(":", 1)[1]: count
                for kind, count in non_kin_leaf_kind_counter.items()
                if kind.startswith(f"{key}:")
            },
            "values": summarize_values(non_kin_values[key]),
            "mapping": leaf_classifications.get(key, {}),
        }
        for key, _ in non_kin_leaf_counter.most_common()
    }
    tasks_with_tro_state = sorted(task_counter)
    tasks_without_tro_state = sorted(set(template_tasks) - set(tasks_with_tro_state))

    return {
        "behavior_root": str(behavior_root),
        "sampled_root": str(sampled_root),
        "template_task_count": len(template_tasks),
        "tasks_with_tro_state_count": len(tasks_with_tro_state),
        "tasks_without_tro_state_count": len(tasks_without_tro_state),
        "tasks_without_tro_state_sample": tasks_without_tro_state[:30],
        "tro_state_files_total": len(all_files),
        "tro_state_files_audited": len(files),
        "parse_error_count": len(parse_errors),
        "parse_error_sample": parse_errors[:10],
        "task_count": len(task_counter),
        "top_tasks_by_snapshot_count": task_counter.most_common(20),
        "object_count_per_snapshot": {
            "min": min(object_counts) if object_counts else 0,
            "max": max(object_counts) if object_counts else 0,
            "avg": mean(object_counts) if object_counts else 0.0,
        },
        "object_total": object_total,
        "top_object_synsets": object_synset_counter.most_common(30),
        "object_entry_keys": object_entry_key_counter.most_common(),
        "root_link_fields": root_link_field_counter.most_common(),
        "root_link_value_kinds": root_link_value_kind_counter.most_common(),
        "joint_fields": joint_field_counter.most_common(),
        "robot_pose_types": robot_pose_type_counter.most_common(),
        "objects_with_pose": objects_with_pose,
        "objects_with_velocity": objects_with_velocity,
        "objects_with_non_kin": objects_with_non_kin,
        "non_kin_states": non_kin_state_counter.most_common(),
        "non_kin_leaf_summaries": non_kin_leaf_summaries,
        "attached_uuid_values": attached_uuid_counter.most_common(20),
        "candidate_counts": candidate_counts.most_common(),
        "candidate_status_counts": candidate_status_counter.most_common(),
        "sample_observations": sample_observations,
    }


def schema_alignment_table() -> list[dict[str, str]]:
    return [
        {
            "field": "obs_id",
            "tro_state_support": "derivable",
            "notes": "Use file path + object id + source field to create stable ids.",
        },
        {
            "field": "episode_id",
            "tro_state_support": "derivable_but_semantics_need_policy",
            "notes": "tro_state is a snapshot, not rollout; episode can be task/template/snapshot id.",
        },
        {
            "field": "task_id",
            "tro_state_support": "direct_from_path",
            "notes": "sampled_task/<task_id>/... encodes task id.",
        },
        {
            "field": "event_time",
            "tro_state_support": "missing_true_time_derivable_proxy",
            "notes": "No physical timestamp; can use filename snapshot index or scan order.",
        },
        {
            "field": "arrival_time",
            "tro_state_support": "missing_generate_policy",
            "notes": "Offline snapshot has no arrival time; clean stream can equal event_time, perturbation injects delay.",
        },
        {
            "field": "source",
            "tro_state_support": "direct_constant",
            "notes": "Use source='tro_state_snapshot'.",
        },
        {
            "field": "predicate_name",
            "tro_state_support": "partial",
            "notes": "Scalar non_kin leaves and measurement predicates can map directly; observation_kind distinguishes predicate vs measurement evidence.",
        },
        {
            "field": "arguments",
            "tro_state_support": "partial",
            "notes": "Object id is available; relation target is not always available, e.g. AttachedTo only has internal uuid.",
        },
        {
            "field": "observed_value",
            "tro_state_support": "partial",
            "notes": "JSON-compatible bool/int/float/str/list/dict values fit current schema.",
        },
        {
            "field": "confidence",
            "tro_state_support": "missing_generate_policy",
            "notes": "Simulator snapshot has no uncertainty; use 1.0 for clean source, inject lower confidence later.",
        },
        {
            "field": "evidence_ref",
            "tro_state_support": "direct_derivable",
            "notes": "Use file path + object id + field path.",
        },
        {
            "field": "polarity",
            "tro_state_support": "missing_generate_policy",
            "notes": "Use support for clean observations; contradict/correction are benchmark perturbation regimes.",
        },
        {
            "field": "metadata",
            "tro_state_support": "direct_required",
            "notes": "Raw pose, velocity, joint vectors, simulator diagnostics, and time policy should live here for now.",
        },
    ]


def format_rows(rows: list[tuple[Any, Any]], limit: int = 20) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in rows[:limit]:
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def format_schema_alignment(rows: list[dict[str, str]]) -> str:
    lines = ["| StateObservation field | tro_state support | notes |", "| --- | --- | --- |"]
    for row in rows:
        lines.append(f"| `{row['field']}` | `{row['tro_state_support']}` | {row['notes']} |")
    return "\n".join(lines)


def format_leaf_mapping(audit: dict[str, Any], limit: int = 20) -> str:
    lines = [
        "| tro_state leaf | count | value kinds | schema status | candidate predicate | note |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for leaf_key, summary in list(audit["non_kin_leaf_summaries"].items())[:limit]:
        mapping = summary.get("mapping", {})
        kinds = ", ".join(f"{k}:{v}" for k, v in summary.get("value_kinds", {}).items())
        lines.append(
            f"| `{leaf_key}` | {summary['count']} | `{kinds}` | "
            f"`{mapping.get('schema_status', 'unknown')}` | "
            f"`{mapping.get('candidate_predicate', 'unknown')}` | {mapping.get('reason', '')} |"
        )
    if len(lines) == 2:
        lines.append("| n/a | 0 | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(audit: dict[str, Any], schema_rows: list[dict[str, str]]) -> str:
    object_stats = audit["object_count_per_snapshot"]
    known_core = sorted(CORE_STATE_PREDICATES_V0)
    return f"""# tro_state Observation Audit

本报告由 `real_data_pipeline/stages/static_observation_audit.py` 生成。

目标是双向检查：

```text
tro_state 里实际有什么状态证据？
这些证据和 evistatebench/schema.py 里的 StateObservation v0 是否对得上？
```

## Scope

| item | value |
| --- | ---: |
| tro_state files total | {audit["tro_state_files_total"]} |
| tro_state files audited | {audit["tro_state_files_audited"]} |
| template task count | {audit["template_task_count"]} |
| tasks with tro_state | {audit["tasks_with_tro_state_count"]} |
| tasks without tro_state | {audit["tasks_without_tro_state_count"]} |
| parse errors | {audit["parse_error_count"]} |
| object total | {audit["object_total"]} |
| objects per snapshot min | {object_stats["min"]} |
| objects per snapshot avg | {object_stats["avg"]:.2f} |
| objects per snapshot max | {object_stats["max"]} |

## Data -> Observation Candidates

{format_rows(audit["candidate_counts"], limit=20)}

解释：

```text
OBJECT_EXISTS / scalar non_kin states / pose / velocity / joint state 都可以转成 StateObservation。
关键区别是 observation_kind：
predicate_state 面向任务谓词，object_pose / object_velocity / joint_state 面向测量证据。
```

## Schema Fit of Candidate Leaves

{format_rows(audit["candidate_status_counts"], limit=20)}

## StateObservation Field Alignment

{format_schema_alignment(schema_rows)}

## tro_state Object Structure

### Object Entry Keys

{format_rows(audit["object_entry_keys"], limit=20)}

### Root Link Fields

{format_rows(audit["root_link_fields"], limit=20)}

### Joint Fields

{format_rows(audit["joint_fields"], limit=20)}

### Robot Pose Types

{format_rows(audit["robot_pose_types"], limit=20)}

## non_kin State Summary

{format_rows(audit["non_kin_states"], limit=30)}

## non_kin Leaf Mapping

{format_leaf_mapping(audit, limit=30)}

## AttachedTo Check

{format_rows(audit["attached_uuid_values"], limit=20)}

解释：

```text
AttachedTo 在当前 tro_state 中只有 attached_obj_uuid。
本次审计中没有看到可直接映射到另一个 BDDL object id 的正向 attached target。
因此它暂时不能直接生成 attached(obj_a, obj_b)=True，只能作为 simulator internal evidence。
```

## Current Predicate Taxonomy

v0 core predicates:

```text
{", ".join(known_core)}
```

对照本次审计，`toggled_on` 可以从 `ToggledOn.value` 直接得到；
`temperature`、`max_temperature`、`slicer_active`、pose、velocity、joint state
已经可以作为 observation-level / measurement-level predicates 进入 StateObservation。
但它们不都等价于 BDDL goal predicate，后续 query/metric 里要区分任务状态和测量证据。

## Main Findings

```text
1. tro_state 可以支撑 snapshot-grounded observation pilot。
2. 当前 StateObservation 已经可以承载 pose/vector；需要用 observation_kind 避免把 measurement 误读成 BDDL predicate。
3. predicate_name + arguments 的泛化方向是对的；taxonomy 仍需要继续覆盖 numeric/tool/measurement states。
4. event_time / arrival_time / confidence / polarity 不是 tro_state 原生字段，需要 benchmark generation policy。
5. relation predicates 不能只靠 tro_state 文件直接得到，inside/ontop/contains/covered/filled 等仍需要 runtime evaluator 或几何/粒子规则。
```

## Suggested Next Step

```text
写 static_observation_audit.py 的最小版：
先抽 OBJECT_EXISTS + scalar non_kin leaves + pose/velocity/joint measurement，
并把 event_time/confidence 等策略显式写进 metadata。
```
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Maximum tro_state files to audit. 0 means all files.",
    )
    parser.add_argument("--sample-observation-limit", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = audit_tro_state(args.behavior_root, args.max_files, args.sample_observation_limit)
    schema_rows = schema_alignment_table()
    audit["state_observation_fields"] = [field.name for field in fields(StateObservation)]
    audit["schema_alignment"] = schema_rows

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "tro_state_observation_audit.json"
    report_path = args.output_dir / "tro_state_observation_audit.md"
    samples_path = args.output_dir / "tro_state_observation_candidates_sample.jsonl"

    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(build_report(audit, schema_rows), encoding="utf-8")
    with samples_path.open("w", encoding="utf-8") as f:
        for row in audit["sample_observations"]:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")

    print(
        json.dumps(
            {
                "json": str(json_path),
                "report": str(report_path),
                "sample_observations": str(samples_path),
                "tro_state_files_audited": audit["tro_state_files_audited"],
                "task_count": audit["task_count"],
                "object_total": audit["object_total"],
                "candidate_status_counts": audit["candidate_status_counts"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
