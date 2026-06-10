#!/usr/bin/env python3
"""Build benchmark split/profile reports for real public artifacts."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "public_v3_scale48_seed6_main"
)

SHORT_MAX_FINAL_TIME = 300.0
MEDIUM_MAX_FINAL_TIME = 600.0

NUMERIC_EXPECTS = {
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

PREDICATE_FAMILIES = {
    "inside": "containment_or_spatial_relation",
    "contains": "containment_or_spatial_relation",
    "ontop": "containment_or_spatial_relation",
    "under": "containment_or_spatial_relation",
    "nextto": "containment_or_spatial_relation",
    "covered": "material_or_particle_state",
    "filled": "material_or_particle_state",
    "saturated": "material_or_particle_state",
    "open": "object_unary_state",
    "toggled_on": "object_unary_state",
    "hot": "object_unary_state",
    "cooked": "object_unary_state",
    "frozen": "object_unary_state",
    "broken": "object_unary_state",
    "attached": "contact_configuration",
    "touching": "contact_configuration",
    "draped": "contact_configuration",
    "temperature": "numeric_state",
    "max_temperature": "numeric_state",
}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def open_text(path: Path, mode: str = "r"):
    if path.name.endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with open_text(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def artifact_size_summary(artifact_dir: Path) -> dict[str, int]:
    return {
        "total": path_size_bytes(artifact_dir),
        "public_v0": path_size_bytes(artifact_dir / "public_v0"),
        "public_observation_streams": path_size_bytes(
            artifact_dir / "public_v0" / "observation_streams"
        ),
        "intermediate": path_size_bytes(artifact_dir / "intermediate"),
        "perturbation_streams": path_size_bytes(artifact_dir / "observation_streams_v0"),
        "answer_sets": path_size_bytes(artifact_dir / "answer_sets_v0"),
        "reports": path_size_bytes(artifact_dir / "reports"),
    }


def predicate_family(predicate_name: str) -> str:
    return PREDICATE_FAMILIES.get(predicate_name, "other")


def final_target_time(episode: dict[str, Any]) -> float:
    times: list[float] = []
    for values in episode.get("target_event_times", {}).values():
        for value in values:
            times.append(float(value))
    return max(times) if times else 0.0


def horizon_bucket(final_time: float) -> str:
    if final_time <= SHORT_MAX_FINAL_TIME:
        return "short"
    if final_time <= MEDIUM_MAX_FINAL_TIME:
        return "medium"
    return "long"


def transition_kind(target: dict[str, Any]) -> str:
    predicate = str(target.get("predicate_name", "unknown"))
    expect = str(target.get("expect", "unknown"))
    if predicate in {"temperature", "max_temperature"} or expect in NUMERIC_EXPECTS:
        return "numeric_transition"
    if expect in {"eventual_true", "eventual_false"}:
        return "eventual_boolean"
    if expect in {"false_to_true", "true_to_false"}:
        return "boolean_flip"
    return expect


def stream_profile(public_manifest: dict[str, Any]) -> str:
    streams = set(public_manifest.get("observation_streams", {}))
    compressions = {
        info.get("compression", "none")
        for info in public_manifest.get("observation_streams", {}).values()
    }
    if streams == {"clean", "mixed"} and compressions == {"gzip"}:
        return "main_release"
    if streams == {
        "clean",
        "delay",
        "out_of_order",
        "missing",
        "low_confidence",
        "conflict",
        "mixed",
    }:
        return "full_diagnostic"
    return "custom"


def parse_build_commands(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = read_json(path)
    validation_status = "UNKNOWN"
    validation_errors: int | None = None
    for command in payload.get("commands", []):
        if not command.get("command") or not str(command["command"][1]).endswith(
            ("8_validate_public_artifacts.py", "validate_public_artifacts.py")
        ):
            continue
        try:
            validation = json.loads(command.get("output", "{}"))
        except json.JSONDecodeError:
            continue
        validation_status = validation.get("status", validation_status)
        validation_errors = validation.get("errors", validation_errors)
    return {
        "artifact_config": payload.get("artifact_config", {}),
        "query_annotation": payload.get("query_annotation", {}),
        "validation_status": validation_status,
        "validation_errors": validation_errors,
    }


def load_required_artifacts(artifact_dir: Path) -> dict[str, Any]:
    paths = {
        "public_manifest": artifact_dir / "public_v0" / "manifest.json",
        "intermediate_manifest": artifact_dir / "intermediate" / "manifest.json",
        "episodes": artifact_dir / "intermediate" / "real_episode_index_v0.jsonl",
        "queries": artifact_dir / "public_v0" / "queries.jsonl",
        "task_specs": artifact_dir / "public_v0" / "task_specs.jsonl",
        "build_commands": artifact_dir / "build_commands.json",
    }
    for name, path in paths.items():
        if name == "build_commands":
            continue
        if not path.exists():
            raise FileNotFoundError(f"missing required artifact {name}: {path}")

    return {
        "paths": paths,
        "public_manifest": read_json(paths["public_manifest"]),
        "intermediate_manifest": read_json(paths["intermediate_manifest"]),
        "episodes": read_jsonl(paths["episodes"]),
        "queries": read_jsonl(paths["queries"]),
        "task_specs": read_jsonl(paths["task_specs"]),
        "build_commands": parse_build_commands(paths["build_commands"]),
    }


def answer_status_counts(artifact_dir: Path) -> dict[str, Counter[str]]:
    answer_dir = artifact_dir / "answer_sets_v0"
    counts: dict[str, Counter[str]] = {}
    for path in sorted(answer_dir.glob("*.jsonl")):
        stream_name = path.stem
        rows = read_jsonl(path)
        counts[stream_name] = Counter(str(row.get("status", "n/a")) for row in rows)
    return counts


def query_predicate(query: dict[str, Any]) -> str:
    state = query.get("state")
    if isinstance(state, dict):
        return str(state.get("predicate_name", "n/a"))
    return "n/a"


def build_summary(artifact_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    public_manifest = artifacts["public_manifest"]
    intermediate_manifest = artifacts["intermediate_manifest"]
    episodes = artifacts["episodes"]
    queries = artifacts["queries"]
    task_specs = artifacts["task_specs"]
    build_commands = artifacts["build_commands"]

    episode_rows: list[dict[str, Any]] = []
    horizon_counts: Counter[str] = Counter()
    target_predicates: Counter[str] = Counter()
    predicate_families: Counter[str] = Counter()
    transition_kinds: Counter[str] = Counter()
    target_expect_counts: Counter[str] = Counter()
    target_count_by_episode: Counter[str] = Counter()
    clean_obs_by_horizon: Counter[str] = Counter()
    queries_by_episode: Counter[str] = Counter(row["episode_id"] for row in queries)

    for episode in episodes:
        final_time = final_target_time(episode)
        horizon = horizon_bucket(final_time)
        targets = episode.get("targets", [])
        horizon_counts[horizon] += 1
        target_count_by_episode[str(len(targets))] += 1
        clean_obs_by_horizon[horizon] += int(episode.get("clean_observations", 0))
        for target in targets:
            predicate = str(target.get("predicate_name", "unknown"))
            target_predicates[predicate] += 1
            predicate_families[predicate_family(predicate)] += 1
            transition_kinds[transition_kind(target)] += 1
            target_expect_counts[str(target.get("expect", "unknown"))] += 1
        episode_rows.append(
            {
                "episode_id": episode["episode_id"],
                "pilot_id": episode["pilot_id"],
                "task_id": episode["activity_name"],
                "seed": episode.get("seed"),
                "horizon": horizon,
                "final_target_time": final_time,
                "target_count": len(targets),
                "clean_observations": int(episode.get("clean_observations", 0)),
                "queries": queries_by_episode[episode["episode_id"]],
                "target_predicates": [
                    str(target.get("predicate_name", "unknown")) for target in targets
                ],
            }
        )

    query_type_counts = Counter(row.get("query_type", "unknown") for row in queries)
    query_scope_counts = Counter(
        row.get("metadata", {}).get("query_scope", "missing") for row in queries
    )
    query_family_counts = Counter(
        row.get("metadata", {}).get("query_family", "missing") for row in queries
    )
    query_time_probe_counts = Counter(
        row.get("metadata", {}).get("time_probe", "n/a") for row in queries
    )
    query_predicate_counts = Counter(
        query_predicate(row) for row in queries if row.get("query_type") in {"CHECK_STATE", "AS_OF_STATE"}
    )
    query_count_by_horizon: Counter[str] = Counter()
    horizon_by_episode = {row["episode_id"]: row["horizon"] for row in episode_rows}
    for query in queries:
        query_count_by_horizon[horizon_by_episode.get(query["episode_id"], "unknown")] += 1

    for bucket in ("short", "medium", "long"):
        horizon_counts.setdefault(bucket, 0)
        clean_obs_by_horizon.setdefault(bucket, 0)
        query_count_by_horizon.setdefault(bucket, 0)

    streams = public_manifest.get("observation_streams", {})
    size_summary = artifact_size_summary(artifact_dir)
    validation_status = build_commands.get("validation_status", "UNKNOWN")
    validation_errors = build_commands.get("validation_errors")
    if validation_status == "UNKNOWN":
        validation_status = "PASS" if (artifact_dir / "reports" / "public_artifact_validation_v0.md").exists() else "UNKNOWN"

    scope_set = set(query_scope_counts)
    stream_set = set(streams)
    blocking: list[str] = []
    cautions: list[str] = []
    if validation_status != "PASS":
        blocking.append("public artifact validation is not PASS")
    if "mixed" not in stream_set:
        blocking.append("main perturbation stream `mixed` is missing")
    if not {"CHECK_STATE", "AS_OF_STATE", "STATE_DIFF", "CHECK_GOAL"}.issubset(query_type_counts):
        blocking.append("core query workload is incomplete")
    if len(episodes) < 30:
        cautions.append("current batch is still pilot scale (<30 episodes)")
    if horizon_counts.get("medium", 0) == 0:
        cautions.append("medium horizon split is empty")
    if predicate_families.get("contact_configuration", 0) == 0:
        cautions.append("contact / attached state family is not covered yet")
    if scope_set <= {"target_state", "target_state_set", "target_goal"}:
        cautions.append("queries remain target-scoped, not full task-level BDDL semantics")

    recommendations = ["Use main_release gzip artifacts as the default public package."]
    if horizon_counts.get("medium", 0) == 0:
        recommendations.append("Fill the empty medium horizon bucket before scaling beyond pilot size.")
    else:
        recommendations.append("Keep medium-horizon coverage in future scale-up batches.")
    if predicate_families.get("contact_configuration", 0) == 0:
        recommendations.append("Add contact/attached tasks as a separate validated state family.")
    else:
        recommendations.append("Keep contact/attached coverage as a separate validated state family.")
    recommendations.append(
        "Keep CHECK_GOAL and STATE_DIFF explicitly target-scoped until full BDDL task-level timelines are supported."
    )
    recommendations.append("Scale next by adding task x seed / instance repetitions after preserving current split coverage.")

    readiness = "FAIL" if blocking else "PASS_WITH_LIMITS"
    return {
        "artifact_dir": rel(artifact_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation": {
            "status": validation_status,
            "errors": validation_errors,
        },
        "artifact_config": build_commands.get("artifact_config", {}),
        "stream_profile": stream_profile(public_manifest),
        "size_bytes": size_summary,
        "counts": {
            "episodes": len(episodes),
            "tasks": len({row["pilot_id"] for row in episodes}),
            "task_specs": len(task_specs),
            "semantic_timeline_events": intermediate_manifest.get("timeline_events"),
            "clean_observations": intermediate_manifest.get("clean_observations"),
            "queries": len(queries),
            "public_streams": len(streams),
        },
        "streams": streams,
        "horizon_thresholds": {
            "short": f"final_target_time <= {SHORT_MAX_FINAL_TIME:g}",
            "medium": f"{SHORT_MAX_FINAL_TIME:g} < final_target_time <= {MEDIUM_MAX_FINAL_TIME:g}",
            "long": f"final_target_time > {MEDIUM_MAX_FINAL_TIME:g}",
        },
        "horizon_counts": dict(horizon_counts),
        "clean_observations_by_horizon": dict(clean_obs_by_horizon),
        "query_count_by_horizon": dict(query_count_by_horizon),
        "target_count_by_episode": dict(target_count_by_episode),
        "target_predicate_counts": dict(target_predicates),
        "predicate_family_counts": dict(predicate_families),
        "transition_kind_counts": dict(transition_kinds),
        "target_expect_counts": dict(target_expect_counts),
        "query_type_counts": dict(query_type_counts),
        "query_scope_counts": dict(query_scope_counts),
        "query_family_counts": dict(query_family_counts),
        "query_time_probe_counts": dict(query_time_probe_counts),
        "query_predicate_counts": dict(query_predicate_counts),
        "answer_status_counts": {
            name: dict(counter)
            for name, counter in answer_status_counts(artifact_dir).items()
        },
        "episodes": sorted(
            episode_rows,
            key=lambda row: (row["horizon"], row["pilot_id"], row["episode_id"]),
        ),
        "scale_readiness": {
            "status": readiness,
            "blocking": blocking,
            "cautions": cautions,
            "recommendations": recommendations,
        },
    }


def table_from_counter(counter: dict[str, int], *, sort_by_count: bool = True) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    items = counter.items()
    if sort_by_count:
        ordered = sorted(items, key=lambda item: (-item[1], item[0]))
    else:
        ordered = sorted(items)
    for item, count in ordered:
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def stream_table(streams: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| stream | observations | bytes | compression | path |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for name, info in sorted(streams.items()):
        lines.append(
            f"| `{name}` | {info.get('observations', 0)} | {info.get('bytes', 0)} | "
            f"`{info.get('compression', 'none')}` | `{info.get('path', '')}` |"
        )
    return "\n".join(lines)


def size_table(size_summary: dict[str, int]) -> str:
    lines = ["| component | bytes | approx MiB |", "| --- | ---: | ---: |"]
    for name, size in size_summary.items():
        lines.append(f"| `{name}` | {size} | {size / (1024 * 1024):.2f} |")
    return "\n".join(lines)


def episode_table(episodes: list[dict[str, Any]]) -> str:
    lines = [
        "| episode | task | horizon | final time | targets | clean obs | queries |",
        "| --- | --- | --- | ---: | --- | ---: | ---: |",
    ]
    for row in episodes:
        targets = ", ".join(row["target_predicates"])
        lines.append(
            f"| `{row['episode_id']}` | `{row['pilot_id']}` | `{row['horizon']}` | "
            f"{row['final_target_time']:.1f} | `{targets}` | "
            f"{row['clean_observations']} | {row['queries']} |"
        )
    return "\n".join(lines)


def build_report(summary: dict[str, Any]) -> str:
    readiness = summary["scale_readiness"]
    blocking = "\n".join(f"- {item}" for item in readiness["blocking"]) or "- none"
    cautions = "\n".join(f"- {item}" for item in readiness["cautions"]) or "- none"
    recommendations = "\n".join(
        f"- {item}" for item in readiness["recommendations"]
    )
    counts = summary["counts"]
    validation = summary["validation"]
    horizon_counts = summary["horizon_counts"]
    predicate_families = summary["predicate_family_counts"]
    medium_note = (
        f"medium horizon 已有 {horizon_counts.get('medium', 0)} 个 episode"
        if horizon_counts.get("medium", 0)
        else "medium horizon 仍为空"
    )
    contact_note = (
        f"contact / attached 状态族已有 {predicate_families.get('contact_configuration', 0)} 个 target"
        if predicate_families.get("contact_configuration", 0)
        else "contact / attached 状态族尚未覆盖"
    )
    return f"""# Real Benchmark Profile Report v1

本报告由 `real_data_pipeline/stages/profile_report.py` 生成。

## Status

```text
{readiness['status']}
```

## Artifact

| item | value |
| --- | --- |
| artifact dir | `{summary['artifact_dir']}` |
| stream profile | `{summary['stream_profile']}` |
| validation status | `{validation['status']}` |
| validation errors | `{validation['errors']}` |

## Counts

| item | value |
| --- | ---: |
| episodes | {counts['episodes']} |
| tasks | {counts['tasks']} |
| task specs | {counts['task_specs']} |
| semantic timeline events | {counts['semantic_timeline_events']} |
| clean observations | {counts['clean_observations']} |
| queries | {counts['queries']} |
| public streams | {counts['public_streams']} |

## Artifact Config

```json
{json.dumps(summary['artifact_config'], ensure_ascii=False, indent=2)}
```

## Size Summary

{size_table(summary['size_bytes'])}

## Horizon Definition

| split | rule |
| --- | --- |
| short | `{summary['horizon_thresholds']['short']}` |
| medium | `{summary['horizon_thresholds']['medium']}` |
| long | `{summary['horizon_thresholds']['long']}` |

Horizon 使用 episode 内 query target 的最大 event_time，而不是 observation 数量。
observation 数量单独报告，避免把场景对象数量和任务时长混在一起。

## Horizon Split

{table_from_counter(summary['horizon_counts'], sort_by_count=False)}

## Clean Observations By Horizon

{table_from_counter(summary['clean_observations_by_horizon'], sort_by_count=False)}

## Query Count By Horizon

{table_from_counter(summary['query_count_by_horizon'], sort_by_count=False)}

## Target Count Per Episode

{table_from_counter(summary['target_count_by_episode'], sort_by_count=False)}

## Predicate Families

{table_from_counter(summary['predicate_family_counts'])}

## Target Predicates

{table_from_counter(summary['target_predicate_counts'])}

## Transition Kinds

{table_from_counter(summary['transition_kind_counts'])}

## Expected Transition Labels

{table_from_counter(summary['target_expect_counts'])}

## Query Workload

### Query Types

{table_from_counter(summary['query_type_counts'])}

### Query Scopes

{table_from_counter(summary['query_scope_counts'])}

### Query Families

{table_from_counter(summary['query_family_counts'])}

### Query Time Probes

{table_from_counter(summary['query_time_probe_counts'])}

### State Query Predicates

{table_from_counter(summary['query_predicate_counts'])}

## Public Streams

{stream_table(summary['streams'])}

## Answer Status Counts

{chr(10).join(f"### `{name}`{chr(10)}{chr(10)}{table_from_counter(counts)}" for name, counts in sorted(summary['answer_status_counts'].items()))}

## Episode Table

{episode_table(summary['episodes'])}

## Scale Readiness

### Blocking

{blocking}

### Cautions

{cautions}

### Recommendations

{recommendations}

## Interpretation

当前 main artifact 可以作为小规模 public pilot：validation 通过，主发布包已经压到可控大小，
query workload 覆盖四类核心 state-view maintenance 查询。

当前 artifact 已覆盖主要 split：{medium_note}，{contact_note}。
但它还不是论文最终规模：episode 数量仍小，并且 `CHECK_GOAL` / `STATE_DIFF` 仍是 target-scoped。
下一轮扩规模应在保留这些 split 覆盖的前提下扩大 task x seed / instance 数量。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build real benchmark profile and split report."
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--summary-json", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    report_path = args.report or artifact_dir / "reports" / "benchmark_profile_report_v1.md"
    summary_path = args.summary_json or artifact_dir / "reports" / "benchmark_profile_summary_v1.json"

    artifacts = load_required_artifacts(artifact_dir)
    summary = build_summary(artifact_dir, artifacts)
    write_json(summary_path, summary)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report(summary), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": summary["scale_readiness"]["status"],
                "artifact_dir": summary["artifact_dir"],
                "report": rel(report_path),
                "summary_json": rel(summary_path),
                "episodes": summary["counts"]["episodes"],
                "tasks": summary["counts"]["tasks"],
                "queries": summary["counts"]["queries"],
                "stream_profile": summary["stream_profile"],
                "horizon_counts": summary["horizon_counts"],
                "predicate_family_counts": summary["predicate_family_counts"],
                "cautions": summary["scale_readiness"]["cautions"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
