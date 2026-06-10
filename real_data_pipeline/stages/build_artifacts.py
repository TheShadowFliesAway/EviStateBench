#!/usr/bin/env python3
"""Build validated public artifacts from real OmniGibson benchmark episodes.

This is the handoff stage after ``live_recorder.py`` and
``run_pilots.py``:

real episode artifacts -> normalized real-v0 intermediates -> perturbed streams
-> query set -> hidden answer sets -> sanitized public package -> validation.

The adapter intentionally keeps query targets narrow: it uses each episode's
manifest-level expected transition as the benchmark semantic target, while the
public observation streams may still contain richer background measurements
such as object poses, velocities, and robot joints.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_TOOLS_DIR = REPO_ROOT / "tools" / "artifacts"

DEFAULT_STAGE3_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "stage3_pilot_v0"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "public_pilot_v0"

SEMANTIC_QUERY_PREDICATES = {
    "attached",
    "broken",
    "contains",
    "cooked",
    "covered",
    "draped",
    "filled",
    "folded",
    "frozen",
    "hot",
    "inside",
    "nextto",
    "on_fire",
    "ontop",
    "open",
    "overlaid",
    "saturated",
    "max_temperature",
    "temperature",
    "toggled_on",
    "touching",
    "under",
    "unfolded",
}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def annotate_real_query_scopes(query_path: Path) -> dict[str, Any]:
    rows = read_jsonl(query_path)
    query_scope_counts: Counter[str] = Counter()
    for row in rows:
        metadata = dict(row.get("metadata", {}) or {})
        query_type = row.get("query_type")
        if query_type in {"CHECK_STATE", "AS_OF_STATE"}:
            metadata["query_scope"] = "target_state"
            query_scope_counts["target_state"] += 1
        elif query_type == "STATE_DIFF":
            row["scope"] = "target_state_set"
            metadata["query_scope"] = "target_state_set"
            metadata["diff_scope"] = "target_state_set"
            query_scope_counts["target_state_set"] += 1
        elif query_type == "CHECK_GOAL":
            metadata["query_scope"] = "target_goal"
            metadata["goal_scope"] = "target_goal"
            query_scope_counts["target_goal"] += 1
        row["metadata"] = metadata
    write_jsonl(query_path, rows)
    manifest_path = query_path.parent / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        manifest["real_query_scope_counts"] = dict(query_scope_counts)
        manifest["real_scope_note"] = (
            "This real pilot query set is scoped to expected target states / "
            "target goals, not full BDDL task-goal semantics."
        )
        write_json(manifest_path, manifest)
    return {
        "query_path": rel(query_path),
        "query_scope_counts": dict(query_scope_counts),
    }


def bool_from_any(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def targets_for_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    targets = summary.get("expected_targets") or []
    if targets:
        return [dict(target) for target in targets]
    target = summary.get("expected_transition")
    return [dict(target)] if target else []


def target_key(target: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    return (str(target["predicate_name"]), tuple(str(arg) for arg in target["arguments"]))


def target_check_for(summary: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    predicate_name, arguments = target_key(target)
    expect = target.get("expect")
    for check in summary.get("target_checks") or []:
        if check.get("predicate_name") != predicate_name:
            continue
        if tuple(check.get("arguments") or ()) != arguments:
            continue
        if expect is not None and check.get("expect") != expect:
            continue
        return check
    return None


def is_numeric_target(target: dict[str, Any]) -> bool:
    expect = target.get("expect")
    return target.get("predicate_name") in {"temperature", "max_temperature"} or expect in {
        "increase",
        "numeric_increase",
        "decrease",
        "numeric_decrease",
        "decrease_or_low",
        "threshold_min",
        "threshold_max",
        "at_least",
        "at_most",
        "gte",
        "lte",
    }


def goal_value_for_target(target: dict[str, Any]) -> bool | None:
    expect = target.get("expect")
    if expect == "false_to_true" or expect == "eventual_true":
        return True
    if expect == "true_to_false" or expect == "eventual_false":
        return False
    if "to" in target and isinstance(target["to"], bool):
        return target["to"]
    if target.get("from") is False and target.get("to") is True:
        return True
    if target.get("from") is True and target.get("to") is False:
        return False
    return None


def task_file_id_from_summary(row: dict[str, Any]) -> str:
    return (
        f"real_og/{row['pilot_id']}/"
        f"{row['activity_name']}__def{row.get('activity_definition_id', 0):03d}"
        f"__inst{row.get('activity_instance_id', 0):03d}"
    )


def task_family_from_target(target: dict[str, Any]) -> str:
    predicate = str(target.get("predicate_name", "unknown"))
    if predicate in {"inside", "contains"}:
        return "real_og/containment"
    if predicate in {"open", "toggled_on", "hot", "frozen", "cooked"}:
        return "real_og/object_unary_state"
    if predicate in {"covered", "filled", "saturated"}:
        return "real_og/material_state"
    if predicate in {"attached", "draped", "touching"}:
        return "real_og/contact_configuration"
    if predicate in {"temperature", "max_temperature"}:
        return "real_og/numeric_state"
    return f"real_og/{predicate}"


def predicate_category(row: dict[str, Any], fallback: str = "unknown") -> str:
    return str(
        row.get("predicate_category")
        or row.get("metadata", {}).get("predicate_category")
        or fallback
    )


def load_passed_episode_summaries(stage3_dir: Path) -> list[dict[str, Any]]:
    summary_path = stage3_dir / "episode_run_summaries.jsonl"
    if not summary_path.exists():
        raise FileNotFoundError(f"episode summary not found: {summary_path}")

    rows = []
    for row in read_jsonl(summary_path):
        if row.get("status") != "PASS" or not row.get("transition_ok"):
            continue
        episode_dir = REPO_ROOT / row["episode_dir"]
        if not episode_dir.exists():
            raise FileNotFoundError(f"episode dir missing for {row['episode_id']}: {episode_dir}")
        rows.append(row)
    if not rows:
        raise ValueError(f"No PASS + transition_ok episodes found in {summary_path}")
    return rows


def target_category(predicate: str) -> str:
    return {
        "inside": "containment/content relation",
        "contains": "containment/content relation",
        "covered": "material/particle state",
        "filled": "material/particle state",
        "open": "object unary state",
        "toggled_on": "object unary state",
        "hot": "object unary state",
        "cooked": "object unary state",
        "frozen": "object unary state",
        "attached": "contact/configuration relation",
        "temperature": "numeric object state",
        "max_temperature": "numeric simulator/object diagnostic",
    }.get(predicate, "unknown")


def select_target_timeline_rows(
    rows: list[dict[str, Any]],
    *,
    target: dict[str, Any],
    target_check: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not rows or not is_numeric_target(target):
        return rows

    keep_times: list[float] = []
    for row in (rows[0], rows[-1]):
        try:
            keep_times.append(float(row["event_time"]))
        except (KeyError, TypeError, ValueError):
            pass
    if target_check is not None and target_check.get("first_satisfying_event_time") is not None:
        keep_times.append(float(target_check["first_satisfying_event_time"]))

    selected: list[dict[str, Any]] = []
    seen: set[tuple[float, int]] = set()
    for target_time in keep_times:
        best = min(
            rows,
            key=lambda row: abs(float(row.get("event_time", 0.0)) - target_time),
        )
        key = (float(best.get("event_time", 0.0)), int(best.get("event_index", 0)))
        if key in seen:
            continue
        seen.add(key)
        selected.append(best)
    return sorted(selected, key=lambda row: (float(row.get("event_time", 0.0)), int(row.get("event_index", 0))))


def normalized_timeline_events(
    *,
    summary: dict[str, Any],
    target: dict[str, Any],
    hidden_rows: list[dict[str, Any]],
    task_file_id: str,
    task_family: str,
    target_index: int,
    target_check: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    predicate_name, arguments = target_key(target)
    selected: list[dict[str, Any]] = []
    for row in hidden_rows:
        if row.get("predicate_name") != predicate_name:
            continue
        if tuple(row.get("arguments", ())) != arguments:
            continue
        truth_value = row.get("truth_value")
        if truth_value is None:
            truth_value = row.get("observed_value")
        if truth_value is None:
            continue
        event_type = row.get("event_type", "state_change")
        if event_type == "initial_state":
            event_type = "init_assert"
        selected.append(row)

    selected = select_target_timeline_rows(
        selected,
        target=target,
        target_check=target_check,
    )
    events: list[dict[str, Any]] = []
    for row in selected:
        truth_value = row.get("truth_value")
        if truth_value is None:
            truth_value = row.get("observed_value")
        event_type = row.get("event_type", "state_change")
        if event_type == "initial_state":
            event_type = "init_assert"
        events.append(
            {
                "arguments": list(arguments),
                "episode_id": summary["episode_id"],
                "event_id": (
                    f"{summary['episode_id']}__target{target_index:02d}"
                    f"__real_evt_{len(events) + 1:05d}"
                ),
                "event_index": len(events) + 1,
                "event_time": float(row["event_time"]),
                "event_type": event_type,
                "metadata": {
                    "artifact_source": "real_omnigibson_stage3",
                    "expect": target.get("expect"),
                    "query_scope": "target_state",
                    "source_event_id": row.get("event_id"),
                    "source_evidence_ref": row.get("source_evidence_ref"),
                    "predicate_category": predicate_category(row),
                    "target_index": target_index,
                },
                "predicate_name": predicate_name,
                "source_instance_id": (
                    f"{task_file_id}__target{target_index:02d}__"
                    f"{predicate_name}__{'__'.join(arguments)}"
                ),
                "source_section": "real_stage3_target_timeline",
                "state_key": [predicate_name, list(arguments)],
                "task_family": task_family,
                "task_file_id": task_file_id,
                "task_id": summary["activity_name"],
                "truth_value": truth_value,
            }
        )

    if len(events) < 2:
        raise ValueError(
            f"{summary['episode_id']} target timeline too short for "
            f"{predicate_name}{arguments}: {len(events)} events"
        )
    return events


def normalized_task_instance_rows(
    *,
    summary: dict[str, Any],
    targets: list[dict[str, Any]],
    task_spec: dict[str, Any],
    task_file_id: str,
    task_family: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target_index, target in enumerate(targets, start=1):
        target_predicate, target_arguments = target_key(target)
        target_goal_value = goal_value_for_target(target)
        rows.append(
            {
                "arguments": list(target_arguments),
                "instance_id": (
                    f"{task_file_id}__target{target_index:02d}__"
                    f"{target_predicate}__{'__'.join(target_arguments)}"
                ),
                "metadata": {
                    "expect": target.get("expect"),
                    "source": "real_omnigibson_expected_transition",
                    "episode_id": summary["episode_id"],
                    "pilot_id": summary["pilot_id"],
                    "target_index": target_index,
                },
                "predicate_category": target_category(target_predicate),
                "predicate_name": target_predicate,
                "section": "goal" if target_goal_value is not None else "query_target",
                "source_file": f"real_stage3://{summary['episode_id']}/expected_transition",
                "task_family": task_family,
                "task_file_id": task_file_id,
                "task_id": summary["activity_name"],
                "truth_value": target_goal_value if target_goal_value is not None else True,
            }
        )

    for index, object_name in enumerate(task_spec.get("object_scope", []), start=1):
        rows.append(
            {
                "arguments": [object_name],
                "instance_id": f"{task_file_id}__context_object__{index:05d}",
                "metadata": {
                    "source": "real_omnigibson_task_spec",
                    "episode_id": summary["episode_id"],
                },
                "predicate_category": "object existence evidence",
                "predicate_name": "object_exists",
                "section": "context",
                "source_file": f"real_stage3://{summary['episode_id']}/task_spec",
                "task_family": task_family,
                "task_file_id": task_file_id,
                "task_id": summary["activity_name"],
                "truth_value": True,
            }
        )

    return rows


def normalized_clean_rows(
    *,
    summary: dict[str, Any],
    clean_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in clean_rows:
        row = dict(row)
        episode_id = row["episode_id"]
        original_obs_id = str(row["obs_id"])
        row["obs_id"] = f"{episode_id}__{original_obs_id}"
        row["source"] = "sim_state_sensor"
        row["task_id"] = summary["activity_name"]
        metadata = dict(row.get("metadata", {}) or {})
        metadata["artifact_source"] = "real_omnigibson_stage3_clean"
        metadata["pilot_id"] = summary["pilot_id"]
        metadata["task_family"] = task_family_from_target(summary["expected_transition"])
        metadata["original_obs_id"] = original_obs_id
        row["metadata"] = metadata
        normalized.append(row)
    return normalized


def build_intermediates(stage3_dir: Path, intermediate_dir: Path) -> dict[str, Any]:
    summaries = load_passed_episode_summaries(stage3_dir)
    timeline_rows: list[dict[str, Any]] = []
    task_instance_rows: list[dict[str, Any]] = []
    clean_rows: list[dict[str, Any]] = []
    episode_rows: list[dict[str, Any]] = []

    for summary in summaries:
        episode_dir = REPO_ROOT / summary["episode_dir"]
        task_spec = read_json(episode_dir / "task_spec.json")
        hidden = read_jsonl(episode_dir / "hidden_state_timeline.jsonl")
        clean = read_jsonl(episode_dir / "clean_state_observations.jsonl")
        targets = targets_for_summary(summary)
        for target in targets:
            if target["predicate_name"] not in SEMANTIC_QUERY_PREDICATES:
                raise ValueError(
                    f"target predicate is not configured as semantic query target: {target}"
                )

        task_file_id = task_file_id_from_summary(summary)
        task_family = task_family_from_target(targets[0])
        target_event_times: dict[str, list[float]] = {}
        hidden_target_events = 0
        for target_index, target in enumerate(targets, start=1):
            target_events = normalized_timeline_events(
                summary=summary,
                target=target,
                hidden_rows=hidden,
                task_file_id=task_file_id,
                task_family=task_family,
                target_index=target_index,
                target_check=target_check_for(summary, target),
            )
            hidden_target_events += len(target_events)
            timeline_rows.extend(target_events)
            predicate_name, arguments = target_key(target)
            target_event_times[f"{predicate_name}({', '.join(arguments)})"] = [
                event["event_time"] for event in target_events
            ]
        task_instance_rows.extend(
            normalized_task_instance_rows(
                summary=summary,
                targets=targets,
                task_spec=task_spec,
                task_file_id=task_file_id,
                task_family=task_family,
            )
        )
        clean_rows.extend(normalized_clean_rows(summary=summary, clean_rows=clean))
        episode_rows.append(
            {
                "activity_name": summary["activity_name"],
                "clean_observations": len(clean),
                "episode_dir": summary["episode_dir"],
                "episode_id": summary["episode_id"],
                "hidden_target_events": hidden_target_events,
                "pilot_id": summary["pilot_id"],
                "seed": summary.get("seed"),
                "task_family": task_family,
                "task_file_id": task_file_id,
                "target": targets[0],
                "targets": targets,
                "target_event_times": target_event_times,
            }
        )

    timeline_rows.sort(key=lambda row: (row["episode_id"], row["event_time"], row["event_index"]))
    for index, row in enumerate(timeline_rows, start=1):
        row["global_event_index"] = index

    paths = {
        "timeline": intermediate_dir / "real_hidden_state_timeline_v0.jsonl",
        "task_instances": intermediate_dir / "real_task_predicate_instances_v0.jsonl",
        "clean_stream": intermediate_dir / "real_clean_state_observations_v0.jsonl",
        "episodes": intermediate_dir / "real_episode_index_v0.jsonl",
        "manifest": intermediate_dir / "manifest.json",
    }
    write_jsonl(paths["timeline"], timeline_rows)
    write_jsonl(paths["task_instances"], task_instance_rows)
    write_jsonl(paths["clean_stream"], clean_rows)
    write_jsonl(paths["episodes"], episode_rows)

    manifest = {
        "artifact_version": "real_public_adapter_v0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage3_dir": rel(stage3_dir),
        "episode_count": len(episode_rows),
        "timeline_events": len(timeline_rows),
        "task_instance_rows": len(task_instance_rows),
        "clean_observations": len(clean_rows),
        "target_predicate_counts": dict(
            Counter(target["predicate_name"] for row in episode_rows for target in row["targets"])
        ),
        "paths": {key: rel(path) for key, path in paths.items() if key != "manifest"},
        "notes": [
            "Timeline/query targets are limited to expected semantic transitions.",
            "Clean/public streams keep richer simulator-derived background observations.",
            "CHECK_GOAL is target_goal scoped until full BDDL task-goal timelines are generated.",
            "STATE_DIFF is target_state_set scoped in the current real pilot.",
        ],
    }
    write_json(paths["manifest"], manifest)
    return {
        "paths": paths,
        "manifest": manifest,
        "episodes": episode_rows,
    }


def run_command(cmd: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "command": cmd,
        "returncode": completed.returncode,
        "output": completed.stdout,
    }


def require_success(result: dict[str, Any]) -> None:
    if result["returncode"] == 0:
        return
    output_tail = "\n".join(str(result["output"]).splitlines()[-80:])
    raise RuntimeError(
        "Command failed with return code "
        f"{result['returncode']}:\n{' '.join(result['command'])}\n\n{output_tail}"
    )


def path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def artifact_size_summary(output_dir: Path) -> dict[str, int]:
    return {
        "total": path_size_bytes(output_dir),
        "public_v0": path_size_bytes(output_dir / "public_v0"),
        "public_observation_streams": path_size_bytes(
            output_dir / "public_v0" / "observation_streams"
        ),
        "intermediate": path_size_bytes(output_dir / "intermediate"),
        "perturbation_streams": path_size_bytes(output_dir / "observation_streams_v0"),
        "answer_sets": path_size_bytes(output_dir / "answer_sets_v0"),
        "reports": path_size_bytes(output_dir / "reports"),
    }


def size_table(size_summary: dict[str, int]) -> str:
    lines = ["| component | bytes | approx MiB |", "| --- | ---: | ---: |"]
    for name, size in size_summary.items():
        lines.append(f"| `{name}` | {size} | {size / (1024 * 1024):.2f} |")
    return "\n".join(lines)


def build_report(
    *,
    output_dir: Path,
    intermediate_manifest: dict[str, Any],
    command_results: list[dict[str, Any]],
    validation_result: dict[str, Any] | None,
    artifact_config: dict[str, Any],
) -> str:
    command_rows = [
        "| step | returncode |",
        "| --- | ---: |",
    ]
    for result in command_results:
        command_rows.append(
            f"| `{Path(result['command'][1]).name if len(result['command']) > 1 else result['command'][0]}` "
            f"| {result['returncode']} |"
        )

    validation_status = "UNKNOWN"
    validation_errors = "n/a"
    if validation_result is not None:
        try:
            parsed = json.loads(validation_result["output"])
            validation_status = parsed.get("status", "UNKNOWN")
            validation_errors = str(parsed.get("errors", "n/a"))
        except json.JSONDecodeError:
            validation_status = "UNPARSEABLE"
            validation_errors = "n/a"
    size_summary = artifact_size_summary(output_dir)

    return f"""# Real Benchmark Public Artifact Build v0

## Status

```text
{validation_status}
```

## Inputs

| item | value |
| --- | ---: |
| episodes | {intermediate_manifest['episode_count']} |
| semantic timeline events | {intermediate_manifest['timeline_events']} |
| clean observations | {intermediate_manifest['clean_observations']} |

## Target Predicates

```json
{json.dumps(intermediate_manifest['target_predicate_counts'], ensure_ascii=False, indent=2)}
```

## Outputs

```text
{rel(output_dir)}
```

## Artifact Profile

```json
{json.dumps(artifact_config, ensure_ascii=False, indent=2)}
```

## Size Summary

{size_table(size_summary)}

Key files:

```text
{rel(output_dir / "public_v0" / "manifest.json")}
{rel(output_dir / "public_v0" / "task_specs.jsonl")}
{rel(output_dir / "public_v0" / "queries.jsonl")}
{rel(output_dir / "public_v0" / "observation_streams")}
{rel(output_dir / "answer_sets_v0")}
{rel(output_dir / "reports" / "public_artifact_validation_v0.md")}
```

## Pipeline Commands

{chr(10).join(command_rows)}

## Validation

| item | value |
| --- | --- |
| status | `{validation_status}` |
| errors | `{validation_errors}` |

## Boundary

The public package contains sanitized task specs, queries, and observation
streams. Hidden simulator timelines and answer sets stay under the build
directory for local evaluation only.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build validated public artifacts from real benchmark episodes."
    )
    parser.add_argument("--stage3-dir", type=Path, default=DEFAULT_STAGE3_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument(
        "--perturbation-profile",
        choices=("full", "main", "diagnostic"),
        default="full",
        help=(
            "Perturbed stream profile. full keeps all regimes; main keeps the mixed "
            "leaderboard stream; diagnostic keeps single-factor streams."
        ),
    )
    parser.add_argument(
        "--perturbation-streams",
        help="Optional comma-separated perturbation stream override, e.g. mixed,missing.",
    )
    parser.add_argument(
        "--gzip-perturbation-streams",
        action="store_true",
        help="Write intermediate perturbation streams as .jsonl.gz.",
    )
    parser.add_argument(
        "--gzip-public-streams",
        action="store_true",
        help="Write sanitized public observation streams as .jsonl.gz.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stage3_dir = args.stage3_dir.resolve()
    output_dir = args.output_dir.resolve()
    if args.clean_output and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    intermediate_dir = output_dir / "intermediate"
    reports_dir = output_dir / "reports"
    streams_dir = output_dir / "observation_streams_v0"
    query_dir = output_dir / "query_sets_v0"
    answer_dir = output_dir / "answer_sets_v0"
    public_dir = output_dir / "public_v0"

    intermediate = build_intermediates(stage3_dir, intermediate_dir)
    paths = intermediate["paths"]
    command_results: list[dict[str, Any]] = []

    perturbation_command = [
        sys.executable,
        str(ARTIFACT_TOOLS_DIR / "build_perturbed_observations.py"),
        "--input",
        str(paths["clean_stream"]),
        "--output-dir",
        str(streams_dir),
        "--report",
        str(reports_dir / "perturbed_observations_v0.md"),
        "--seed",
        str(args.seed),
        "--profile",
        args.perturbation_profile,
    ]
    if args.perturbation_streams:
        perturbation_command.extend(["--streams", args.perturbation_streams])
    if args.gzip_perturbation_streams:
        perturbation_command.append("--gzip")

    public_command = [
        sys.executable,
        str(ARTIFACT_TOOLS_DIR / "build_public_artifacts.py"),
        "--task-instances",
        str(paths["task_instances"]),
        "--timeline",
        str(paths["timeline"]),
        "--queries",
        str(query_dir / "queries.jsonl"),
        "--clean-stream",
        str(paths["clean_stream"]),
        "--stream-dir",
        str(streams_dir),
        "--output-dir",
        str(public_dir),
        "--report",
        str(reports_dir / "public_artifacts_v0.md"),
    ]
    if args.gzip_public_streams:
        public_command.append("--gzip-streams")

    pre_query_annotation_commands = [
        perturbation_command,
        [
            sys.executable,
            str(ARTIFACT_TOOLS_DIR / "build_query_sets.py"),
            "--timeline",
            str(paths["timeline"]),
            "--goal-instances",
            str(paths["task_instances"]),
            "--output-dir",
            str(query_dir),
            "--report",
            str(reports_dir / "query_sets_v0.md"),
        ],
    ]
    post_query_annotation_commands = [
        [
            sys.executable,
            str(ARTIFACT_TOOLS_DIR / "build_ground_truth_answers.py"),
            "--timeline",
            str(paths["timeline"]),
            "--queries",
            str(query_dir / "queries.jsonl"),
            "--clean-stream",
            str(paths["clean_stream"]),
            "--stream-dir",
            str(streams_dir),
            "--output-dir",
            str(answer_dir),
            "--report",
            str(reports_dir / "ground_truth_answers_v0.md"),
        ],
        public_command,
        [
            sys.executable,
            str(ARTIFACT_TOOLS_DIR / "validate_public_artifacts.py"),
            "--public-dir",
            str(public_dir),
            "--report",
            str(reports_dir / "public_artifact_validation_v0.md"),
            "--strict",
        ],
    ]

    validation_result: dict[str, Any] | None = None
    query_annotation: dict[str, Any] | None = None
    for command in pre_query_annotation_commands:
        result = run_command(command)
        command_results.append(result)
        require_success(result)

    query_annotation = annotate_real_query_scopes(query_dir / "queries.jsonl")

    for command in post_query_annotation_commands:
        result = run_command(command)
        command_results.append(result)
        if command[1].endswith("validate_public_artifacts.py"):
            validation_result = result
        require_success(result)

    write_json(
        output_dir / "build_commands.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_config": {
                "perturbation_profile": args.perturbation_profile,
                "perturbation_streams": args.perturbation_streams,
                "gzip_perturbation_streams": args.gzip_perturbation_streams,
                "gzip_public_streams": args.gzip_public_streams,
            },
            "query_annotation": query_annotation,
            "commands": command_results,
        },
    )
    (reports_dir / "real_public_artifact_build_v0.md").write_text(
        build_report(
            output_dir=output_dir,
            intermediate_manifest=intermediate["manifest"],
            command_results=command_results,
            validation_result=validation_result,
            artifact_config={
                "perturbation_profile": args.perturbation_profile,
                "perturbation_streams": args.perturbation_streams,
                "gzip_perturbation_streams": args.gzip_perturbation_streams,
                "gzip_public_streams": args.gzip_public_streams,
            },
        ),
        encoding="utf-8",
    )

    validation_payload: dict[str, Any] = {}
    if validation_result is not None:
        validation_payload = json.loads(validation_result["output"])
    size_summary = artifact_size_summary(output_dir)
    print(
        json.dumps(
            {
                "status": validation_payload.get("status", "UNKNOWN"),
                "output_dir": rel(output_dir),
                "public_dir": rel(public_dir),
                "episodes": intermediate["manifest"]["episode_count"],
                "semantic_timeline_events": intermediate["manifest"]["timeline_events"],
                "clean_observations": intermediate["manifest"]["clean_observations"],
                "artifact_config": {
                    "perturbation_profile": args.perturbation_profile,
                    "perturbation_streams": args.perturbation_streams,
                    "gzip_perturbation_streams": args.gzip_perturbation_streams,
                    "gzip_public_streams": args.gzip_public_streams,
                },
                "size_bytes": size_summary,
                "queries": validation_payload.get("queries"),
                "streams": validation_payload.get("streams"),
                "validation_report": rel(reports_dir / "public_artifact_validation_v0.md"),
                "build_report": rel(reports_dir / "real_public_artifact_build_v0.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
