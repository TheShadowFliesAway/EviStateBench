#!/usr/bin/env python3
"""Audit a real benchmark artifact for scale-up quality issues.

This report is intentionally diagnostic rather than pass/fail validation.  It
answers the practical question after a generation run: what should we fix or
expand next?
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_STAGE3_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "stage3_v3_scale48_seed6"
DEFAULT_ARTIFACT_DIR = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "public_v3_scale48_seed6_main"
)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with open_text(path) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def state_key(row: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    state = row.get("state") or row
    return (
        str(state.get("predicate_name", "")),
        tuple(str(arg) for arg in state.get("arguments", []) or []),
    )


def query_state_predicate(row: dict[str, Any]) -> str:
    return state_key(row)[0] or "n/a"


def targets_for_episode(row: dict[str, Any]) -> list[dict[str, Any]]:
    targets = row.get("expected_targets") or []
    if targets:
        return [dict(target) for target in targets]
    target = row.get("expected_transition")
    return [dict(target)] if target else []


def final_target_time(row: dict[str, Any]) -> float:
    times: list[float] = []
    for check in row.get("target_checks") or []:
        time_value = check.get("first_satisfying_event_time")
        if time_value is None:
            time_value = check.get("first_satisfying_time")
        if time_value is None:
            time_value = check.get("to_event_time")
        if time_value is not None:
            times.append(float(time_value))
    return max(times) if times else 0.0


def horizon_for(time_value: float) -> str:
    if time_value <= 300:
        return "short"
    if time_value <= 600:
        return "medium"
    return "long"


def load_stream_paths(artifact_dir: Path) -> dict[str, Path]:
    manifest = read_json(artifact_dir / "public_v0" / "manifest.json")
    paths: dict[str, Path] = {}
    for name, info in manifest.get("observation_streams", {}).items():
        path = Path(info["path"])
        if not path.is_absolute():
            path = REPO_ROOT / path
        paths[name] = path
    return paths


def answer_status_by_stream(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    answer_dir = artifact_dir / "answer_sets_v0"
    for path in sorted(answer_dir.glob("*.jsonl")):
        status_counts: Counter[str] = Counter()
        query_type_counts: Counter[str] = Counter()
        predicate_counts: Counter[str] = Counter()
        status_by_query_type: dict[str, Counter[str]] = defaultdict(Counter)
        status_by_predicate: dict[str, Counter[str]] = defaultdict(Counter)
        for row in iter_jsonl(path):
            query_type = str(row.get("query_type", "unknown"))
            status = str(row.get("status", "n/a"))
            predicate = query_state_predicate(row)
            if query_type == "CHECK_GOAL":
                predicate = "goal"
            if query_type == "STATE_DIFF":
                predicate = "diff"
            status_counts[status] += 1
            query_type_counts[query_type] += 1
            predicate_counts[predicate] += 1
            status_by_query_type[query_type][status] += 1
            status_by_predicate[predicate][status] += 1
        result[path.stem] = {
            "status_counts": dict(status_counts),
            "query_type_counts": dict(query_type_counts),
            "predicate_counts": dict(predicate_counts),
            "status_by_query_type": {k: dict(v) for k, v in status_by_query_type.items()},
            "status_by_predicate": {k: dict(v) for k, v in status_by_predicate.items()},
        }
    return result


def stream_observation_stats(stream_paths: dict[str, Path]) -> dict[str, Any]:
    streams: dict[str, Any] = {}
    for name, path in stream_paths.items():
        by_episode: Counter[str] = Counter()
        by_kind: Counter[str] = Counter()
        by_predicate: Counter[str] = Counter()
        confidence_bins: Counter[str] = Counter()
        delay_values: list[float] = []
        late_count = 0
        low_conf_count = 0
        conflict_added = 0
        rows = 0
        for row in iter_jsonl(path):
            rows += 1
            by_episode[str(row.get("episode_id", "unknown"))] += 1
            by_kind[str(row.get("observation_kind", "unknown"))] += 1
            by_predicate[str(row.get("predicate_name", "unknown"))] += 1
            confidence = float(row.get("confidence", 0.0) or 0.0)
            if confidence < 0.5:
                confidence_bins["<0.5"] += 1
            elif confidence < 0.8:
                confidence_bins["0.5-0.8"] += 1
            elif confidence < 1.0:
                confidence_bins["0.8-1.0"] += 1
            else:
                confidence_bins["1.0"] += 1
            if confidence < 0.8:
                low_conf_count += 1
            event_time = float(row.get("event_time", 0.0) or 0.0)
            arrival_time = float(row.get("arrival_time", event_time) or 0.0)
            delay = arrival_time - event_time
            delay_values.append(delay)
            if delay > 0:
                late_count += 1
            metadata = row.get("metadata", {}) or {}
            if metadata.get("perturbation") == "conflict_added":
                conflict_added += 1
        top_episodes = by_episode.most_common(10)
        streams[name] = {
            "rows": rows,
            "path": rel(path),
            "top_episodes_by_observations": top_episodes,
            "observation_kind_counts": dict(by_kind),
            "predicate_counts": dict(by_predicate),
            "confidence_bins": dict(confidence_bins),
            "low_confidence_rows": low_conf_count,
            "late_rows": late_count,
            "conflict_added_rows": conflict_added,
            "mean_arrival_delay": mean(delay_values) if delay_values else 0.0,
            "max_arrival_delay": max(delay_values) if delay_values else 0.0,
        }
    return streams


def build_summary(stage3_dir: Path, artifact_dir: Path) -> dict[str, Any]:
    episode_rows = read_jsonl(stage3_dir / "episode_run_summaries.jsonl")
    passed_rows = [row for row in episode_rows if row.get("status") == "PASS" and row.get("transition_ok")]
    profile_summary = read_json(artifact_dir / "reports" / "benchmark_profile_summary_v1.json")
    profile_episodes = {
        row["episode_id"]: row for row in profile_summary.get("episodes", [])
    }
    public_manifest = read_json(artifact_dir / "public_v0" / "manifest.json")
    build_commands = read_json(artifact_dir / "build_commands.json")
    queries = read_jsonl(artifact_dir / "public_v0" / "queries.jsonl")

    by_pilot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    episode_audit: list[dict[str, Any]] = []
    for row in passed_rows:
        pilot_id = str(row.get("pilot_id", "unknown"))
        profile_episode = profile_episodes.get(row["episode_id"], {})
        final_time = float(profile_episode.get("final_target_time", final_target_time(row)))
        horizon = str(profile_episode.get("horizon") or horizon_for(final_time))
        counts = row.get("counts", {}) or {}
        targets = targets_for_episode(row)
        audit_row = {
            "episode_id": row["episode_id"],
            "pilot_id": pilot_id,
            "seed": row.get("seed"),
            "activity_instance_id": row.get("activity_instance_id"),
            "final_target_time": final_time,
            "horizon": horizon,
            "targets": [
                {
                    "predicate_name": target.get("predicate_name"),
                    "arguments": target.get("arguments", []),
                    "expect": target.get("expect") or (
                        f"{target.get('from')}->{target.get('to')}"
                        if "from" in target and "to" in target
                        else None
                    ),
                }
                for target in targets
            ],
            "simulator_truth_snapshots": counts.get("simulator_truth_snapshots", 0),
            "hidden_state_timeline_events": counts.get("hidden_state_timeline_events", 0),
            "clean_state_observations": counts.get("clean_state_observations", 0),
            "elapsed_sec": row.get("elapsed_sec"),
        }
        episode_audit.append(audit_row)
        by_pilot[pilot_id].append(audit_row)

    pilot_audit: dict[str, Any] = {}
    for pilot_id, rows in sorted(by_pilot.items()):
        times = [float(row["final_target_time"]) for row in rows]
        clean_counts = [int(row["clean_state_observations"]) for row in rows]
        horizons = Counter(str(row["horizon"]) for row in rows)
        pilot_audit[pilot_id] = {
            "episodes": len(rows),
            "horizon_counts": dict(horizons),
            "final_target_time_min": min(times) if times else 0.0,
            "final_target_time_max": max(times) if times else 0.0,
            "final_target_time_mean": mean(times) if times else 0.0,
            "clean_observations_min": min(clean_counts) if clean_counts else 0,
            "clean_observations_max": max(clean_counts) if clean_counts else 0,
            "clean_observations_mean": mean(clean_counts) if clean_counts else 0.0,
            "horizon_is_stable": len(horizons) <= 1,
        }

    query_counts = Counter(str(row.get("query_type", "unknown")) for row in queries)
    query_family_counts = Counter(
        str((row.get("metadata") or {}).get("query_family", "unknown")) for row in queries
    )
    time_probe_counts = Counter(
        str((row.get("metadata") or {}).get("time_probe", "n/a")) for row in queries
    )
    query_predicates = Counter(
        query_state_predicate(row)
        for row in queries
        if row.get("query_type") in {"CHECK_STATE", "AS_OF_STATE"}
    )

    stream_paths = load_stream_paths(artifact_dir)
    stream_stats = stream_observation_stats(stream_paths)
    answer_stats = answer_status_by_stream(artifact_dir)

    outliers = {
        "top_clean_observation_episodes": sorted(
            episode_audit,
            key=lambda row: int(row["clean_state_observations"]),
            reverse=True,
        )[:10],
        "horizon_unstable_pilots": {
            pilot_id: audit
            for pilot_id, audit in pilot_audit.items()
            if not audit["horizon_is_stable"]
        },
        "longest_final_target_time_episodes": sorted(
            episode_audit,
            key=lambda row: float(row["final_target_time"]),
            reverse=True,
        )[:10],
    }

    issues: list[dict[str, Any]] = []
    for pilot_id, audit in outliers["horizon_unstable_pilots"].items():
        issues.append(
            {
                "severity": "medium",
                "kind": "horizon_seed_drift",
                "message": f"{pilot_id} crosses horizon buckets across seeds",
                "details": audit,
            }
        )
    for row in outliers["top_clean_observation_episodes"][:3]:
        if int(row["clean_state_observations"]) >= 50000:
            issues.append(
                {
                    "severity": "medium",
                    "kind": "large_clean_observation_episode",
                    "message": f"{row['episode_id']} has {row['clean_state_observations']} clean observations",
                    "details": {
                        "pilot_id": row["pilot_id"],
                        "final_target_time": row["final_target_time"],
                    },
                }
            )
    mixed = answer_stats.get("mixed", {})
    mixed_status = mixed.get("status_counts", {})
    degraded = sum(int(mixed_status.get(name, 0)) for name in ("unknown", "uncertain", "conflict"))
    if degraded:
        issues.append(
            {
                "severity": "info",
                "kind": "mixed_stream_degradation",
                "message": f"mixed stream has {degraded} unknown/uncertain/conflict answers",
                "details": mixed_status,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage3_dir": rel(stage3_dir),
        "artifact_dir": rel(artifact_dir),
        "generation": {
            "total_runs": len(episode_rows),
            "passed_transition_runs": len(passed_rows),
            "failed_or_non_transition_runs": len(episode_rows) - len(passed_rows),
        },
        "validation": {
            "status": build_commands.get("validation_status", profile_summary.get("validation", {}).get("status")),
            "errors": build_commands.get("validation_errors", profile_summary.get("validation", {}).get("errors")),
        },
        "public_manifest": {
            "task_specs": public_manifest.get("task_specs", {}).get("count"),
            "queries": public_manifest.get("queries", {}).get("count"),
            "streams": {
                name: {
                    "observations": info.get("observations"),
                    "bytes": info.get("bytes"),
                    "compression": info.get("compression"),
                }
                for name, info in public_manifest.get("observation_streams", {}).items()
            },
        },
        "profile": {
            "status": profile_summary.get("scale_readiness", {}).get("status"),
            "horizon_counts": profile_summary.get("horizon_counts", {}),
            "predicate_family_counts": profile_summary.get("predicate_family_counts", {}),
            "target_predicate_counts": profile_summary.get("target_predicate_counts", {}),
            "query_type_counts": profile_summary.get("query_type_counts", {}),
            "query_scope_counts": profile_summary.get("query_scope_counts", {}),
            "cautions": profile_summary.get("scale_readiness", {}).get("cautions", []),
        },
        "query_workload": {
            "query_type_counts": dict(query_counts),
            "query_family_counts": dict(query_family_counts),
            "time_probe_counts": dict(time_probe_counts),
            "state_query_predicates": dict(query_predicates),
        },
        "pilot_audit": pilot_audit,
        "episode_audit": episode_audit,
        "stream_observation_stats": stream_stats,
        "answer_status_by_stream": answer_stats,
        "outliers": outliers,
        "issues": issues,
    }


def table_from_counter(counter: dict[str, int], *, sort_by_count: bool = True) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    items = counter.items()
    ordered = (
        sorted(items, key=lambda item: (-item[1], item[0]))
        if sort_by_count
        else sorted(items)
    )
    for key, value in ordered:
        lines.append(f"| `{key}` | {value} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def format_float(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def build_report(summary: dict[str, Any]) -> str:
    profile = summary["profile"]
    public_manifest = summary["public_manifest"]
    lines = [
        "# Real Benchmark Quality Audit v0",
        "",
        "本报告由 `real_data_pipeline/stages/quality_audit.py` 生成。",
        "",
        "## Summary",
        "",
        f"- stage3_dir: `{summary['stage3_dir']}`",
        f"- artifact_dir: `{summary['artifact_dir']}`",
        f"- generation: {summary['generation']['passed_transition_runs']} / {summary['generation']['total_runs']} PASS + transition_ok",
        f"- validation: {summary['validation']['status']}，errors={summary['validation']['errors']}",
        f"- task_specs: {public_manifest['task_specs']}",
        f"- queries: {public_manifest['queries']}",
        f"- profile_status: {profile['status']}",
        "",
        "## Public Streams",
        "",
        "| stream | observations | bytes | compression |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, info in sorted(public_manifest["streams"].items()):
        lines.append(
            f"| `{name}` | {info['observations']} | {info['bytes']} | `{info['compression']}` |"
        )

    lines.extend(
        [
            "",
            "## Split Coverage",
            "",
            "### Horizon",
            "",
            table_from_counter(profile["horizon_counts"]),
            "",
            "### Predicate Families",
            "",
            table_from_counter(profile["predicate_family_counts"]),
            "",
            "### Target Predicates",
            "",
            table_from_counter(profile["target_predicate_counts"]),
            "",
            "## Query Workload",
            "",
            "### Query Types",
            "",
            table_from_counter(summary["query_workload"]["query_type_counts"]),
            "",
            "### Query Families",
            "",
            table_from_counter(summary["query_workload"]["query_family_counts"]),
            "",
            "### State Query Predicates",
            "",
            table_from_counter(summary["query_workload"]["state_query_predicates"]),
            "",
            "## Pilot Stability",
            "",
            "| pilot | episodes | horizons | final target time | clean observations | stable horizon |",
            "| --- | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for pilot_id, audit in sorted(summary["pilot_audit"].items()):
        lines.append(
            f"| `{pilot_id}` | {audit['episodes']} | `{audit['horizon_counts']}` | "
            f"{format_float(audit['final_target_time_min'])}-{format_float(audit['final_target_time_max'])} | "
            f"{format_float(audit['clean_observations_min'])}-{format_float(audit['clean_observations_max'])} | "
            f"{audit['horizon_is_stable']} |"
        )

    lines.extend(["", "## Observation Outliers", ""])
    lines.extend(
        [
            "| episode | pilot | horizon | final time | clean observations |",
            "| --- | --- | --- | ---: | ---: |",
        ]
    )
    for row in summary["outliers"]["top_clean_observation_episodes"]:
        lines.append(
            f"| `{row['episode_id']}` | `{row['pilot_id']}` | `{row['horizon']}` | "
            f"{format_float(row['final_target_time'])} | {row['clean_state_observations']} |"
        )

    lines.extend(["", "## Stream Diagnostics", ""])
    for name, stats in sorted(summary["stream_observation_stats"].items()):
        lines.extend(
            [
                f"### `{name}`",
                "",
                f"- rows: {stats['rows']}",
                f"- late_rows: {stats['late_rows']}",
                f"- low_confidence_rows: {stats['low_confidence_rows']}",
                f"- conflict_added_rows: {stats['conflict_added_rows']}",
                f"- mean_arrival_delay: {format_float(stats['mean_arrival_delay'])}",
                f"- max_arrival_delay: {format_float(stats['max_arrival_delay'])}",
                "",
                "Top episode observation counts:",
                "",
                "| episode | observations |",
                "| --- | ---: |",
            ]
        )
        for episode_id, count in stats["top_episodes_by_observations"]:
            lines.append(f"| `{episode_id}` | {count} |")
        lines.append("")

    lines.extend(["## Answer Status Diagnostics", ""])
    for name, stats in sorted(summary["answer_status_by_stream"].items()):
        lines.extend(
            [
                f"### `{name}`",
                "",
                table_from_counter(stats["status_counts"]),
                "",
                "By query type:",
                "",
            ]
        )
        for query_type, counter in sorted(stats["status_by_query_type"].items()):
            lines.append(f"- `{query_type}`: `{counter}`")
        lines.append("")

    lines.extend(["## Issues And Recommendations", ""])
    if not summary["issues"]:
        lines.append("- No audit issues detected beyond profile cautions.")
    else:
        for issue in summary["issues"]:
            lines.append(
                f"- **{issue['severity']} / {issue['kind']}**: {issue['message']}"
            )
    lines.extend(
        [
            "",
            "Recommended next actions:",
            "",
            "- Do not scale only by seeds again; add new tasks / state families before another large run.",
            "- Keep p6 freeze medium, but treat it as seed-sensitive around the 600-step horizon boundary.",
            "- Add a cheaper medium task whose final target time is comfortably below 600 to stabilize the split.",
            "- Use mixed stream degradation and baseline results as the first benchmark discriminativeness check.",
            "- Keep CHECK_GOAL / STATE_DIFF labeled target-scoped until full BDDL goal timelines are implemented.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit real benchmark artifact quality.")
    parser.add_argument("--stage3-dir", type=Path, default=DEFAULT_STAGE3_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stage3_dir = args.stage3_dir.resolve()
    artifact_dir = args.artifact_dir.resolve()
    output_json = args.output_json or artifact_dir / "reports" / "quality_audit_v0.json"
    report = args.report or artifact_dir / "reports" / "quality_audit_v0.md"

    summary = build_summary(stage3_dir, artifact_dir)
    write_json(output_json, summary)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_report(summary), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "PASS",
                "report": rel(report),
                "summary_json": rel(output_json),
                "episodes": summary["generation"]["passed_transition_runs"],
                "issues": len(summary["issues"]),
                "horizon_counts": summary["profile"]["horizon_counts"],
                "cautions": summary["profile"]["cautions"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
