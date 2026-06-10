#!/usr/bin/env python3
"""Run selected real benchmark pilot episodes and summarize their artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    REPO_ROOT / "real_data_pipeline" / "manifests" / "real_benchmark_pilot_tasks_v0.jsonl"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "stage3_pilot_v0"
RECORDER = REPO_ROOT / "real_data_pipeline" / "stages" / "live_recorder.py"
RELATION_PREDICATES = {
    "attached",
    "contains",
    "covered",
    "filled",
    "inside",
    "modified_particles",
    "nextto",
    "ontop",
    "overlaid",
    "saturated",
    "touching",
    "under",
}


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = json.loads(line)
        row.setdefault("manifest_line", line_index)
        rows.append(row)
    return rows


def parse_csv_ints(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            values.append(int(part))
    return values


def manifest_bool(row: dict[str, Any], key: str, default: bool) -> bool:
    value = row.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return bool(value)


def entry_id(pilot: dict[str, Any]) -> str:
    return str(pilot.get("pilot_id") or pilot.get("candidate_id") or pilot.get("activity_name"))


def episode_id_for(pilot: dict[str, Any], instance_id: int, seed: int, repeat_index: int) -> str:
    return f"{entry_id(pilot)}__inst{instance_id:03d}__seed{seed:03d}__rep{repeat_index:02d}"


def primary_expected_transition(pilot: dict[str, Any]) -> dict[str, Any]:
    if pilot.get("expected_transition"):
        return pilot["expected_transition"]
    for target in pilot.get("expected_targets") or []:
        expect = target.get("expect")
        if expect == "false_to_true":
            return {
                "predicate_name": target.get("predicate_name"),
                "arguments": target.get("arguments"),
                "from": False,
                "to": True,
            }
        if expect == "true_to_false":
            return {
                "predicate_name": target.get("predicate_name"),
                "arguments": target.get("arguments"),
                "from": True,
                "to": False,
            }
    targets = expected_conditions(pilot)
    return targets[0] if targets else {}


def expected_conditions(pilot: dict[str, Any]) -> list[dict[str, Any]]:
    if pilot.get("expected_transition"):
        target = dict(pilot["expected_transition"])
        if "expect" not in target:
            if target.get("from") is False and target.get("to") is True:
                target["expect"] = "false_to_true"
            elif target.get("from") is True and target.get("to") is False:
                target["expect"] = "true_to_false"
            else:
                target["expect"] = "value_change"
        return [target]
    return [dict(target) for target in (pilot.get("expected_targets") or [])]


def focused_relations_for(pilot: dict[str, Any]) -> list[str]:
    if not pilot.get("record_relations"):
        return []
    targets = expected_conditions(pilot)
    focused: list[str] = []
    for target in targets:
        args = target.get("arguments") or []
        predicate = target.get("predicate_name")
        if predicate in RELATION_PREDICATES and len(args) == 2:
            focused.append(f"{predicate}:{args[0]}:{args[1]}")
    return list(dict.fromkeys(focused))


def build_command(
    *,
    pilot: dict[str, Any],
    output_dir: Path,
    instance_id: int,
    seed: int,
    repeat_index: int,
    args: argparse.Namespace,
) -> tuple[list[str], Path, Path]:
    episode_id = episode_id_for(pilot, instance_id, seed, repeat_index)
    run_dir = output_dir / "runs" / episode_id
    episode_dir = output_dir / "episodes" / episode_id
    command = [
        sys.executable,
        str(RECORDER),
        "--output-dir",
        str(run_dir),
        "--episode-output-dir",
        str(episode_dir),
        "--episode-id",
        episode_id,
        "--activity-name",
        pilot["activity_name"],
        "--scene-model",
        pilot["scene_model"],
        "--activity-definition-id",
        str(pilot.get("activity_definition_id", 0)),
        "--activity-instance-id",
        str(instance_id),
        "--seed",
        str(seed),
        "--robot-type",
        pilot.get("robot_type", "R1"),
        "--action-source",
        pilot.get("action_source", "primitive_jsonl"),
        "--steps",
        str(args.steps),
        "--max-objects",
        str(args.max_objects),
        "--max-states-per-object",
        str(args.max_states_per_object),
        "--max-runtime-steps",
        str(args.max_runtime_steps),
        "--max-primitive-low-level-steps",
        str(args.max_primitive_low_level_steps),
        "--runtime-timeout",
        str(args.runtime_timeout),
    ]
    if pilot.get("primitive_jsonl"):
        command.extend(["--primitive-jsonl", str(REPO_ROOT / pilot["primitive_jsonl"])])
    if pilot.get("record_relations"):
        command.append("--record-relations")
        focused_relations = focused_relations_for(pilot)
        if args.focused_relations and focused_relations:
            for focused_relation in focused_relations:
                command.extend(["--focused-relation", focused_relation])
            command.extend(["--max-relation-pairs", "0"])
        else:
            command.extend(["--max-relation-pairs", str(pilot.get("max_relation_pairs", 0))])
    else:
        command.extend(["--max-relation-pairs", "0"])
    if pilot.get("requires_enable_transition_rules"):
        command.append("--enable-transition-rules")
    if not manifest_bool(pilot, "use_presampled_robot_pose", True):
        command.append("--no-presampled-robot-pose")
    return command, run_dir, episode_dir


def tail_text(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def find_target_timeline(episode_dir: Path, expected: dict[str, Any]) -> list[dict[str, Any]]:
    timeline_path = episode_dir / "hidden_state_timeline.jsonl"
    if not timeline_path.exists():
        return []
    predicate = expected.get("predicate_name")
    arguments = expected.get("arguments")
    matches: list[dict[str, Any]] = []
    with timeline_path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("predicate_name") == predicate and row.get("arguments") == arguments:
                matches.append(row)
    return matches


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def condition_label(expected: dict[str, Any]) -> str:
    args = ", ".join(str(arg) for arg in expected.get("arguments") or [])
    expect = expected.get("expect")
    if expect:
        return f"{expected.get('predicate_name')}({args}) {expect}"
    return f"{expected.get('predicate_name')}({args})"


def first_satisfying_event_time(
    target_timeline: list[dict[str, Any]],
    predicate: Any,
) -> float | None:
    for row in target_timeline:
        if predicate(row):
            try:
                return float(row.get("event_time"))
            except (TypeError, ValueError):
                return None
    return None


def check_within_timeout(event_time: float | None, expected: dict[str, Any]) -> tuple[bool, str | None]:
    timeout = expected.get("within_timeout")
    if timeout is None:
        timeout = expected.get("max_event_time")
    if timeout is None:
        return True, None
    if event_time is None:
        return False, f"no satisfying event_time for within_timeout={timeout}"
    try:
        timeout_value = float(timeout)
    except (TypeError, ValueError):
        return False, f"invalid within_timeout={timeout!r}"
    if event_time <= timeout_value:
        return True, None
    return False, f"satisfying event_time {event_time:g} exceeds timeout {timeout_value:g}"


def evaluate_expected_condition(
    target_timeline: list[dict[str, Any]],
    expected: dict[str, Any],
) -> dict[str, Any]:
    expect = expected.get("expect")
    expected_from = expected.get("from")
    expected_to = expected.get("to")
    if expect is None:
        if expected_from is False and expected_to is True:
            expect = "false_to_true"
        elif expected_from is True and expected_to is False:
            expect = "true_to_false"
        elif "to" in expected:
            expect = "eventual_value"
        else:
            expect = "observed"

    values = [row.get("observed_value") for row in target_timeline]
    numeric_values = [value for value in (numeric_value(value) for value in values) if value is not None]
    result: dict[str, Any] = {
        "predicate_name": expected.get("predicate_name"),
        "arguments": expected.get("arguments") or [],
        "expect": expect,
        "ok": False,
        "event_count": len(target_timeline),
        "initial_value": values[0] if values else None,
        "final_value": values[-1] if values else None,
    }
    if numeric_values:
        result["initial_numeric_value"] = numeric_values[0]
        result["final_numeric_value"] = numeric_values[-1]
        result["min_numeric_value"] = min(numeric_values)
        result["max_numeric_value"] = max(numeric_values)

    if not target_timeline:
        result["reason"] = "no target timeline rows"
        return result

    min_delta = float(expected.get("min_delta", 0.0))
    threshold = expected.get("threshold", expected.get("target_value"))
    event_time: float | None = None
    ok = False
    reason = ""

    if expect == "false_to_true":
        expected_from = False
        expected_to = True
        has_from = any(row.get("observed_value") is expected_from for row in target_timeline)
        event_time = first_satisfying_event_time(
            target_timeline,
            lambda row: row.get("event_type") == "state_change" and row.get("observed_value") is expected_to,
        )
        has_to = any(row.get("observed_value") is expected_to for row in target_timeline)
        ok = bool(has_from and has_to and event_time is not None)
        reason = "requires false evidence and a true state_change"
    elif expect == "true_to_false":
        expected_from = True
        expected_to = False
        has_from = any(row.get("observed_value") is expected_from for row in target_timeline)
        event_time = first_satisfying_event_time(
            target_timeline,
            lambda row: row.get("event_type") == "state_change" and row.get("observed_value") is expected_to,
        )
        has_to = any(row.get("observed_value") is expected_to for row in target_timeline)
        ok = bool(has_from and has_to and event_time is not None)
        reason = "requires true evidence and a false state_change"
    elif expect in {"eventual_true", "eventual_value"}:
        expected_to = True if expect == "eventual_true" else expected.get("to")
        event_time = first_satisfying_event_time(
            target_timeline,
            lambda row: row.get("observed_value") == expected_to,
        )
        ok = event_time is not None
        reason = f"requires observed_value={expected_to!r}"
    elif expect == "eventual_false":
        event_time = first_satisfying_event_time(
            target_timeline,
            lambda row: row.get("observed_value") is False,
        )
        ok = event_time is not None
        reason = "requires observed_value=False"
    elif expect in {"increase", "numeric_increase"}:
        if len(numeric_values) >= 2:
            baseline = numeric_values[0]
            event_time = first_satisfying_event_time(
                target_timeline,
                lambda row: (
                    numeric_value(row.get("observed_value")) is not None
                    and numeric_value(row.get("observed_value")) > baseline + min_delta
                ),
            )
            ok = event_time is not None
            reason = f"requires numeric value > initial + {min_delta:g}"
        else:
            reason = "requires at least two numeric observations"
    elif expect in {"decrease", "numeric_decrease", "decrease_or_low"}:
        if len(numeric_values) >= 2:
            baseline = numeric_values[0]
            event_time = first_satisfying_event_time(
                target_timeline,
                lambda row: (
                    numeric_value(row.get("observed_value")) is not None
                    and numeric_value(row.get("observed_value")) < baseline - min_delta
                ),
            )
            ok = event_time is not None
            reason = f"requires numeric value < initial - {min_delta:g}"
        else:
            reason = "requires at least two numeric observations"
        if not ok and threshold is not None:
            try:
                threshold_value = float(threshold)
                event_time = first_satisfying_event_time(
                    target_timeline,
                    lambda row: (
                        numeric_value(row.get("observed_value")) is not None
                        and numeric_value(row.get("observed_value")) <= threshold_value
                    ),
                )
                ok = event_time is not None
                reason = f"requires numeric decrease or value <= {threshold_value:g}"
            except (TypeError, ValueError):
                reason = f"invalid threshold={threshold!r}"
    elif expect in {"threshold_min", "at_least", "gte"}:
        if threshold is None:
            reason = "missing threshold"
        else:
            threshold_value = float(threshold)
            event_time = first_satisfying_event_time(
                target_timeline,
                lambda row: (
                    numeric_value(row.get("observed_value")) is not None
                    and numeric_value(row.get("observed_value")) >= threshold_value
                ),
            )
            ok = event_time is not None
            reason = f"requires numeric value >= {threshold_value:g}"
    elif expect in {"threshold_max", "at_most", "lte"}:
        if threshold is None:
            reason = "missing threshold"
        else:
            threshold_value = float(threshold)
            event_time = first_satisfying_event_time(
                target_timeline,
                lambda row: (
                    numeric_value(row.get("observed_value")) is not None
                    and numeric_value(row.get("observed_value")) <= threshold_value
                ),
            )
            ok = event_time is not None
            reason = f"requires numeric value <= {threshold_value:g}"
    elif expect == "observed":
        ok = bool(target_timeline)
        event_time = float(target_timeline[0].get("event_time", 0.0))
        reason = "requires at least one observation"
    else:
        reason = f"unsupported expect={expect!r}"

    timeout_ok, timeout_reason = check_within_timeout(event_time, expected)
    result["first_satisfying_event_time"] = event_time
    result["ok"] = bool(ok and timeout_ok)
    result["reason"] = timeout_reason or reason
    return result


def target_transition_ok(target_timeline: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    expected_from = expected.get("from")
    expected_to = expected.get("to")
    has_from = any(row.get("observed_value") == expected_from for row in target_timeline)
    has_to = any(row.get("observed_value") == expected_to for row in target_timeline)
    has_change = any(
        row.get("event_type") == "state_change" and row.get("observed_value") == expected_to
        for row in target_timeline
    )
    return bool(has_from and has_to and has_change)


def evaluate_expected_conditions(episode_dir: Path, pilot: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for expected in expected_conditions(pilot):
        timeline = find_target_timeline(episode_dir, expected)
        check = evaluate_expected_condition(timeline, expected)
        check["label"] = condition_label(expected)
        check["target_timeline"] = [
            {
                "event_time": row.get("event_time"),
                "event_type": row.get("event_type"),
                "previous_observed_value": row.get("previous_observed_value"),
                "observed_value": row.get("observed_value"),
                "valid_from": row.get("valid_from"),
                "valid_to": row.get("valid_to"),
            }
            for row in timeline
        ]
        checks.append(check)
    return checks


def summarize_episode(
    *,
    pilot: dict[str, Any],
    command: list[str],
    returncode: int,
    elapsed_sec: float,
    run_dir: Path,
    episode_dir: Path,
    instance_id: int,
    seed: int,
    repeat_index: int,
) -> dict[str, Any]:
    report_path = episode_dir / "generation_report.json"
    report = read_json(report_path) if report_path.exists() else {}
    expected = primary_expected_transition(pilot)
    target_timeline = find_target_timeline(episode_dir, expected)
    status = report.get("status") or ("PASS" if returncode == 0 else "FAIL")
    target_checks = evaluate_expected_conditions(episode_dir, pilot) if status == "PASS" else []
    transition_ok = bool(target_checks) and all(check.get("ok") for check in target_checks)
    counts = report.get("counts") or {}
    return {
        "pilot_id": entry_id(pilot),
        "candidate_id": pilot.get("candidate_id"),
        "episode_id": episode_dir.name,
        "activity_name": pilot.get("activity_name"),
        "scene_model": pilot.get("scene_model"),
        "activity_instance_id": instance_id,
        "seed": seed,
        "repeat_index": repeat_index,
        "status": status,
        "transition_ok": transition_ok,
        "expected_transition": expected,
        "expected_targets": expected_conditions(pilot),
        "target_checks": target_checks,
        "target_timeline": [
            {
                "event_time": row.get("event_time"),
                "event_type": row.get("event_type"),
                "previous_observed_value": row.get("previous_observed_value"),
                "observed_value": row.get("observed_value"),
                "valid_from": row.get("valid_from"),
                "valid_to": row.get("valid_to"),
            }
            for row in target_timeline
        ],
        "counts": counts,
        "error": report.get("error"),
        "returncode": returncode,
        "elapsed_sec": round(elapsed_sec, 3),
        "episode_dir": str(episode_dir.relative_to(REPO_ROOT)),
        "run_dir": str(run_dir.relative_to(REPO_ROOT)),
        "generation_report": str(report_path.relative_to(REPO_ROOT)) if report_path.exists() else None,
        "clean_state_observations_bytes": (episode_dir / "clean_state_observations.jsonl").stat().st_size
        if (episode_dir / "clean_state_observations.jsonl").exists()
        else 0,
        "simulator_truth_snapshots_bytes": (episode_dir / "simulator_truth_snapshots.jsonl").stat().st_size
        if (episode_dir / "simulator_truth_snapshots.jsonl").exists()
        else 0,
        "command": command,
        "child_log_tail": tail_text(run_dir / "omnigibson_recorder_probe_child.log"),
    }


def write_markdown_summary(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Real Benchmark Pilot Generation Summary",
        "",
        f"generated_at: {summary['generated_at']}",
        "",
        "## Overall",
        "",
        f"- manifest: `{summary['manifest']}`",
        f"- output_dir: `{summary['output_dir']}`",
        f"- total_runs: {summary['total_runs']}",
        f"- pass_runs: {summary['pass_runs']}",
        f"- transition_ok_runs: {summary['transition_ok_runs']}",
        f"- focused_relations: {summary['focused_relations']}",
        f"- seeds: {summary['seeds']}",
        f"- activity_instance_ids: {summary['activity_instance_ids']}",
        "",
        "## Runs",
        "",
        "| episode | status | transition | snapshots | timeline | clean obs | clean size | target |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        counts = row.get("counts") or {}
        targets = row.get("expected_targets") or [row.get("expected_transition") or {}]
        target_text = "; ".join(
            f"{target.get('predicate_name')}({', '.join(target.get('arguments') or [])})"
            for target in targets
            if target
        )
        lines.append(
            "| "
            f"`{row['episode_id']}` | {row['status']} | {row['transition_ok']} | "
            f"{counts.get('simulator_truth_snapshots', 0)} | "
            f"{counts.get('hidden_state_timeline_events', 0)} | "
            f"{counts.get('clean_state_observations', 0)} | "
            f"{row.get('clean_state_observations_bytes', 0)} | "
            f"`{target_text}` |"
        )
    lines.extend(["", "## Failed / Non-Transition Runs", ""])
    problematic = [row for row in rows if row["status"] != "PASS" or not row["transition_ok"]]
    if not problematic:
        lines.append("None.")
    for row in problematic:
        lines.append(f"### {row['episode_id']}")
        lines.append("")
        lines.append(f"- status: {row['status']}")
        lines.append(f"- transition_ok: {row['transition_ok']}")
        if row.get("target_checks"):
            lines.append("- target_checks:")
            for check in row["target_checks"]:
                lines.append(
                    f"  - {check.get('label')}: ok={check.get('ok')} "
                    f"reason={check.get('reason')}"
                )
        if row.get("error"):
            lines.append(f"- error: {row['error'].get('type')}: {row['error'].get('message')}")
        lines.append(f"- report: `{row.get('generation_report')}`")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.resolve()
    if args.clean_output and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    include_statuses = set(args.include_status)
    pilots = [row for row in load_manifest(args.manifest) if row.get("status") in include_statuses]
    if args.only:
        allowed = set(args.only)
        pilots = [row for row in pilots if entry_id(row) in allowed]

    seeds = parse_csv_ints(args.seeds)
    instance_ids = parse_csv_ints(args.activity_instance_ids)
    rows: list[dict[str, Any]] = []

    for pilot in pilots:
        for instance_id in instance_ids:
            for repeat_index, seed in enumerate(seeds):
                command, run_dir, episode_dir = build_command(
                    pilot=pilot,
                    output_dir=output_dir,
                    instance_id=instance_id,
                    seed=seed,
                    repeat_index=repeat_index,
                    args=args,
                )
                print(f"[run] {episode_dir.name}", flush=True)
                started = time.perf_counter()
                env = os.environ.copy()
                env.setdefault("VK_ICD_FILENAMES", "/etc/vulkan/icd.d/my_nvidia_icd.json")
                env["PYTHONHASHSEED"] = str(seed)
                proc = subprocess.run(command, cwd=REPO_ROOT, env=env)
                elapsed = time.perf_counter() - started
                rows.append(
                    summarize_episode(
                        pilot=pilot,
                        command=command,
                        returncode=proc.returncode,
                        elapsed_sec=elapsed,
                        run_dir=run_dir,
                        episode_dir=episode_dir,
                        instance_id=instance_id,
                        seed=seed,
                        repeat_index=repeat_index,
                    )
                )
                write_jsonl(output_dir / "episode_run_summaries.jsonl", rows)

    summary = {
        "generated_at": utc_now(),
        "manifest": str(args.manifest.resolve().relative_to(REPO_ROOT)),
        "output_dir": str(output_dir.relative_to(REPO_ROOT)),
        "total_runs": len(rows),
        "pass_runs": sum(1 for row in rows if row["status"] == "PASS"),
        "transition_ok_runs": sum(1 for row in rows if row["transition_ok"]),
        "focused_relations": args.focused_relations,
        "seeds": seeds,
        "activity_instance_ids": instance_ids,
        "pilot_ids": [entry_id(row) for row in pilots],
    }
    write_json(output_dir / "benchmark_generation_summary.json", {"summary": summary, "runs": rows})
    write_markdown_summary(output_dir / "benchmark_generation_summary.md", summary, rows)
    write_jsonl(output_dir / "episode_run_summaries.jsonl", rows)
    return 0 if summary["pass_runs"] == summary["total_runs"] and summary["transition_ok_runs"] == summary["total_runs"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument("--seeds", default="0,1")
    parser.add_argument("--activity-instance-ids", default="0")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--include-status", action="append", default=["selected_validated"])
    parser.add_argument("--focused-relations", action="store_true", default=True)
    parser.add_argument("--no-focused-relations", dest="focused_relations", action="store_false")
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--max-objects", type=int, default=0)
    parser.add_argument("--max-states-per-object", type=int, default=0)
    parser.add_argument("--max-runtime-steps", type=int, default=380)
    parser.add_argument("--max-primitive-low-level-steps", type=int, default=220)
    parser.add_argument("--runtime-timeout", type=int, default=800)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
