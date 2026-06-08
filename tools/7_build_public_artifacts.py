#!/usr/bin/env python3
"""Build sanitized public benchmark artifacts for EviStateBench v0.

This script is the minimal cleanup pass after the synthetic v0 pipeline.

Existing intermediate files still contain generator/oracle provenance such as
``source_section`` and ``synthetic_reason``.  Those fields are useful for
debugging the generator, but they should not be visible to a benchmarked
system.  This script creates a clean public package:

public task specs + sanitized observation streams + sanitized query set

Hidden timelines and answer sets remain outside this public package.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.schema import PREDICATE_CATEGORY_V0  # noqa: E402


DEFAULT_TASK_INSTANCE_PATH = REPO_ROOT / "data" / "task_predicate_instances_v0.jsonl"
DEFAULT_TIMELINE_PATH = REPO_ROOT / "data" / "synthetic_ground_truth_timelines_v0.jsonl"
DEFAULT_QUERY_PATH = REPO_ROOT / "data" / "query_sets_v0" / "queries.jsonl"
DEFAULT_CLEAN_STREAM_PATH = REPO_ROOT / "data" / "clean_state_observations_v0.jsonl"
DEFAULT_STREAM_DIR = REPO_ROOT / "data" / "observation_streams_v0"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "public_v0"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "public_artifacts_v0.md"


PUBLIC_OBSERVATION_KEYS = (
    "obs_id",
    "episode_id",
    "task_id",
    "event_time",
    "arrival_time",
    "source",
    "predicate_name",
    "arguments",
    "observed_value",
    "confidence",
    "evidence_ref",
    "polarity",
    "metadata",
)

SOURCE_REWRITE = {
    "synthetic_truth_sensor": "sim_state_sensor",
    "synthetic_conflict_sensor": "rgb_relation_detector",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def has_instance_suffix(argument: str) -> bool:
    return bool(re.search(r"_\d+$", argument))


def normalize_argument(argument: str, instance_id: str, argument_index: int) -> str:
    """Use the same goal-variable normalization as the query generator."""
    if not argument.startswith("?"):
        return argument

    stripped = argument[1:]
    if has_instance_suffix(stripped):
        return stripped

    occurrence_suffix = instance_id.split("__", maxsplit=2)[-1].replace("__", "_")
    return f"{stripped}__goalvar_{occurrence_suffix}_arg{argument_index}"


def task_spec_id_for_episode(episode_id: str) -> str:
    return f"{episode_id}__task_spec"


def load_episode_metadata(timeline_path: Path) -> dict[str, dict[str, Any]]:
    """Load episode-level metadata from the hidden timeline for spec packaging."""
    episodes: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(timeline_path):
        episode = episodes.setdefault(
            row["episode_id"],
            {
                "episode_id": row["episode_id"],
                "task_spec_id": task_spec_id_for_episode(row["episode_id"]),
                "task_id": row["task_id"],
                "task_file_id": row["task_file_id"],
                "task_family": row["task_family"],
                "final_time": 0.0,
                "timeline_event_count": 0,
            },
        )
        episode["final_time"] = max(float(episode["final_time"]), float(row["event_time"]))
        episode["timeline_event_count"] += 1
    return episodes


def build_task_specs(
    *,
    task_instance_path: Path,
    timeline_path: Path,
) -> list[dict[str, Any]]:
    """Build episode-scoped public task specs from BDDL-derived instances."""
    episode_metadata = load_episode_metadata(timeline_path)

    instances_by_task_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(task_instance_path):
        instances_by_task_file[row["task_file_id"]].append(row)

    specs: list[dict[str, Any]] = []
    for episode_id, episode in sorted(episode_metadata.items()):
        task_file_id = episode["task_file_id"]
        instances = instances_by_task_file.get(task_file_id, [])
        object_scope: set[str] = set()
        predicate_vocabulary: set[str] = set()
        goal_seen: set[tuple[str, tuple[str, ...], bool]] = set()
        goal_states: list[dict[str, Any]] = []

        for row in instances:
            predicate_vocabulary.add(row["predicate_name"])
            normalized_args = tuple(
                normalize_argument(argument, row["instance_id"], index)
                for index, argument in enumerate(row["arguments"])
            )
            object_scope.update(normalized_args)
            if row["section"] != "goal":
                continue

            desired_value = bool(row["truth_value"])
            goal_key = (row["predicate_name"], normalized_args, desired_value)
            if goal_key in goal_seen:
                continue
            goal_seen.add(goal_key)
            goal_states.append(
                {
                    "predicate_name": row["predicate_name"],
                    "arguments": list(normalized_args),
                    "desired_value": desired_value,
                    "predicate_category": row.get(
                        "predicate_category",
                        PREDICATE_CATEGORY_V0.get(row["predicate_name"], "unknown"),
                    ),
                }
            )

        specs.append(
            {
                "task_spec_id": episode["task_spec_id"],
                "episode_id": episode_id,
                "task_id": episode["task_id"],
                "task_family": episode["task_family"],
                "task_file_id": task_file_id,
                "object_scope": sorted(object_scope),
                "predicate_vocabulary": sorted(predicate_vocabulary),
                "goal_states": sorted(
                    goal_states,
                    key=lambda goal: (
                        goal["predicate_name"],
                        goal["arguments"],
                        goal["desired_value"],
                    ),
                ),
                "metadata": {
                    "source": "bddl_task_spec",
                    "spec_version": "v0",
                },
            }
        )
    return specs


def clean_query_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {}
    for key in ("query_family", "task_family", "time_probe", "window", "target_event_time"):
        if key in metadata:
            allowed[key] = metadata[key]
    return allowed


def sanitize_queries(
    *,
    query_path: Path,
    task_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove answer-like goal payloads from queries and add task_spec_id refs."""
    spec_id_by_episode = {spec["episode_id"]: spec["task_spec_id"] for spec in task_specs}
    public_queries: list[dict[str, Any]] = []
    for row in read_jsonl(query_path):
        public = {key: value for key, value in row.items() if key != "metadata"}
        public["task_spec_id"] = spec_id_by_episode[row["episode_id"]]
        public["metadata"] = clean_query_metadata(row.get("metadata", {}))
        public_queries.append(public)
    return public_queries


def clean_observation_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata", {}) or {}
    public_metadata: dict[str, Any] = {}

    predicate_category = row.get("predicate_category") or metadata.get("predicate_category")
    if predicate_category:
        public_metadata["predicate_category"] = predicate_category

    for key in ("task_family", "stream_order"):
        if key in metadata:
            public_metadata[key] = metadata[key]

    return public_metadata


def sanitize_observation(row: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: row.get(key)
        for key in PUBLIC_OBSERVATION_KEYS
        if key != "metadata"
    }
    public["source"] = SOURCE_REWRITE.get(str(public["source"]), public["source"])
    public["arguments"] = list(public["arguments"])
    public["metadata"] = clean_observation_metadata(row)
    return public


def sanitize_stream(input_path: Path, output_path: Path) -> int:
    rows = [sanitize_observation(row) for row in read_jsonl(input_path)]
    write_jsonl(output_path, rows)
    return len(rows)


def sanitize_streams(
    *,
    clean_stream_path: Path,
    stream_dir: Path,
    output_dir: Path,
) -> dict[str, dict[str, Any]]:
    streams: dict[str, Path] = {"clean": clean_stream_path}
    for path in sorted(stream_dir.glob("*.jsonl")):
        streams[path.stem] = path

    output_stream_dir = output_dir / "observation_streams"
    summary: dict[str, dict[str, Any]] = {}
    for name, input_path in sorted(streams.items()):
        output_path = output_stream_dir / f"{name}.jsonl"
        count = sanitize_stream(input_path, output_path)
        summary[name] = {
            "path": relative(output_path),
            "observations": count,
        }
    return summary


def write_manifest(
    *,
    output_dir: Path,
    task_specs_path: Path,
    queries_path: Path,
    streams: dict[str, dict[str, Any]],
    task_specs: list[dict[str, Any]],
    queries: list[dict[str, Any]],
) -> None:
    manifest = {
        "artifact_version": "public_v0",
        "description": "Public EviStateBench v0 inputs visible to benchmarked systems.",
        "task_specs": {
            "path": relative(task_specs_path),
            "count": len(task_specs),
        },
        "queries": {
            "path": relative(queries_path),
            "count": len(queries),
            "query_type_counts": dict(Counter(row["query_type"] for row in queries)),
        },
        "observation_streams": streams,
        "system_output": {
            "expected": "predicted QueryAnswers JSONL keyed by query_id",
            "evaluated_against": "hidden ground-truth answer sets",
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def table_from_counter(counter: Counter[str]) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common():
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def build_report(
    *,
    output_dir: Path,
    task_specs: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    streams: dict[str, dict[str, Any]],
) -> str:
    query_counts = Counter(row["query_type"] for row in queries)
    family_counts = Counter(spec["task_family"] for spec in task_specs)
    stream_rows = [
        "| stream | observations | path |",
        "| --- | ---: | --- |",
    ]
    for name, info in sorted(streams.items()):
        stream_rows.append(f"| `{name}` | {info['observations']} | `{info['path']}` |")

    return f"""# Public Artifacts v0

本报告由 `tools/7_build_public_artifacts.py` 生成。

它对应 artifact boundary cleanup：

```text
public task specs + public observation streams + public query set
```

## Public Inputs

| artifact | path | count |
| --- | --- | ---: |
| task specs | `{relative(output_dir / "task_specs.jsonl")}` | {len(task_specs)} |
| queries | `{relative(output_dir / "queries.jsonl")}` | {len(queries)} |

## Observation Streams

{chr(10).join(stream_rows)}

## Query Types

{table_from_counter(query_counts)}

## Task Families

{table_from_counter(family_counts)}

## Boundary

这些文件可以提供给被测系统：

```text
data/public_v0/task_specs.jsonl
data/public_v0/queries.jsonl
data/public_v0/observation_streams/*.jsonl
```

这些文件是 hidden / oracle / evaluation-only，不应提供给被测系统：

```text
data/synthetic_ground_truth_timelines_v0.jsonl
data/task_predicate_instances_v0.jsonl
data/answer_sets_v0/*.jsonl
data/evaluation_v0/*
```

清理规则：

1. `CHECK_GOAL` query 不再内嵌 `goal_states`，只通过 `task_spec_id` 引用任务规格。
2. public observation 不包含 `truth_value`、`source_section`、`source_event_type`、`synthetic_reason` 等 generator/oracle 字段。
3. public manifest 使用相对路径，避免把本机路径暴露给 benchmark 使用者。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sanitized public EviStateBench v0 artifacts.")
    parser.add_argument("--task-instances", type=Path, default=DEFAULT_TASK_INSTANCE_PATH)
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE_PATH)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_PATH)
    parser.add_argument("--clean-stream", type=Path, default=DEFAULT_CLEAN_STREAM_PATH)
    parser.add_argument("--stream-dir", type=Path, default=DEFAULT_STREAM_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_specs = build_task_specs(
        task_instance_path=args.task_instances,
        timeline_path=args.timeline,
    )
    queries = sanitize_queries(query_path=args.queries, task_specs=task_specs)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    task_specs_path = args.output_dir / "task_specs.jsonl"
    queries_path = args.output_dir / "queries.jsonl"
    write_jsonl(task_specs_path, task_specs)
    write_jsonl(queries_path, queries)
    streams = sanitize_streams(
        clean_stream_path=args.clean_stream,
        stream_dir=args.stream_dir,
        output_dir=args.output_dir,
    )
    write_manifest(
        output_dir=args.output_dir,
        task_specs_path=task_specs_path,
        queries_path=queries_path,
        streams=streams,
        task_specs=task_specs,
        queries=queries,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            output_dir=args.output_dir,
            task_specs=task_specs,
            queries=queries,
            streams=streams,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "task_specs": len(task_specs),
                "queries": len(queries),
                "streams": streams,
                "report": str(args.report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
