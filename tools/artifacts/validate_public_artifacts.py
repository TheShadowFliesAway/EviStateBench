#!/usr/bin/env python3
"""Validate that public EviStateBench artifacts do not expose oracle fields."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_PUBLIC_DIR = REPO_ROOT / "data" / "public_v0"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "public_artifact_validation_v0.md"

PUBLIC_OBSERVATION_KEYS = {
    "obs_id",
    "episode_id",
    "task_id",
    "event_time",
    "arrival_time",
    "source",
    "predicate_name",
    "arguments",
    "observed_value",
    "observation_kind",
    "confidence",
    "evidence_ref",
    "polarity",
    "metadata",
}
PUBLIC_OBSERVATION_OPTIONAL_KEYS = {"observation_kind"}
PUBLIC_OBSERVATION_REQUIRED_KEYS = PUBLIC_OBSERVATION_KEYS - PUBLIC_OBSERVATION_OPTIONAL_KEYS

PUBLIC_QUERY_BASE_KEYS = {
    "query_id",
    "query_type",
    "episode_id",
    "task_id",
    "task_spec_id",
    "metadata",
}

OBSERVATION_BANNED_KEYS = {
    "truth",
    "truth_value",
    "ground_truth",
    "answer",
    "answer_type",
    "is_support",
    "is_contradict",
    "source_section",
    "source_instance_id",
    "source_event_id",
    "source_event_index",
    "source_event_type",
    "source_clean_obs_id",
    "source_file",
    "synthetic_reason",
    "clean_generation",
    "previous_truth_value",
    "previous_value_source",
    "original_arguments",
    "original_confidence",
    "original_observed_value",
    "flipped_observed_value",
    "perturbation",
    "operations",
}

QUERY_BANNED_KEYS = {
    "truth",
    "truth_value",
    "ground_truth",
    "answer",
    "answer_type",
    "goal_state_count",
    "goal_states",
    "source_file",
}

TASK_SPEC_BANNED_KEYS = {
    "truth",
    "truth_value",
    "ground_truth",
    "answer",
    "answer_type",
    "source_file",
    "init_states",
    "initial_truth",
    "final_time",
    "timeline_event_count",
}


def open_text(path: Path, mode: str = "r"):
    if path.name.endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def stream_name_for_path(path: Path) -> str:
    name = path.name
    if name.endswith(".jsonl.gz"):
        return name[: -len(".jsonl.gz")]
    if name.endswith(".jsonl"):
        return name[: -len(".jsonl")]
    return path.stem


def iter_jsonl_paths(directory: Path) -> list[Path]:
    return sorted(
        [*directory.glob("*.jsonl"), *directory.glob("*.jsonl.gz")],
        key=lambda path: (stream_name_for_path(path), path.name),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with open_text(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def contains_absolute_local_path(value: Any) -> bool:
    if isinstance(value, str):
        return "/root/" in value or "/autodl-tmp/" in value
    if isinstance(value, list):
        return any(contains_absolute_local_path(item) for item in value)
    if isinstance(value, dict):
        return any(
            contains_absolute_local_path(key) or contains_absolute_local_path(item)
            for key, item in value.items()
        )
    return False


def collect_banned_keys(
    value: Any,
    banned: set[str],
    *,
    prefix: str = "",
) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            if key in banned:
                hits.append(next_prefix)
            hits.extend(collect_banned_keys(item, banned, prefix=next_prefix))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(collect_banned_keys(item, banned, prefix=f"{prefix}[{index}]"))
    return hits


def add_error(errors: list[str], path: Path, row_number: int | None, message: str) -> None:
    if row_number is None:
        errors.append(f"{path}: {message}")
    else:
        errors.append(f"{path}:{row_number}: {message}")


def validate_task_specs(path: Path, errors: list[str]) -> Counter[str]:
    rows = read_jsonl(path)
    counter: Counter[str] = Counter()
    seen_specs: set[str] = set()
    for index, row in enumerate(rows, start=1):
        counter["rows"] += 1
        for field in ("task_spec_id", "episode_id", "task_id", "goal_states"):
            if field not in row:
                add_error(errors, path, index, f"missing required field {field}")
        if row.get("task_spec_id") in seen_specs:
            add_error(errors, path, index, f"duplicate task_spec_id {row.get('task_spec_id')}")
        seen_specs.add(row.get("task_spec_id", ""))
        banned_hits = collect_banned_keys(row, TASK_SPEC_BANNED_KEYS)
        if banned_hits:
            add_error(errors, path, index, f"banned keys: {', '.join(banned_hits)}")
        if contains_absolute_local_path(row):
            add_error(errors, path, index, "contains absolute local path")
    return counter


def validate_queries(path: Path, task_spec_ids: set[str], errors: list[str]) -> Counter[str]:
    rows = read_jsonl(path)
    counter: Counter[str] = Counter()
    seen_queries: set[str] = set()
    for index, row in enumerate(rows, start=1):
        query_type = row.get("query_type", "unknown")
        counter[query_type] += 1
        if row.get("query_id") in seen_queries:
            add_error(errors, path, index, f"duplicate query_id {row.get('query_id')}")
        seen_queries.add(row.get("query_id", ""))
        for field in ("query_id", "query_type", "episode_id", "task_id", "task_spec_id"):
            if field not in row:
                add_error(errors, path, index, f"missing required field {field}")
        if row.get("task_spec_id") not in task_spec_ids:
            add_error(errors, path, index, f"unknown task_spec_id {row.get('task_spec_id')}")
        banned_hits = collect_banned_keys(row, QUERY_BANNED_KEYS)
        if banned_hits:
            add_error(errors, path, index, f"banned keys: {', '.join(banned_hits)}")
        if contains_absolute_local_path(row):
            add_error(errors, path, index, "contains absolute local path")
    return counter


def validate_observation_stream(path: Path, errors: list[str]) -> Counter[str]:
    rows = read_jsonl(path)
    counter: Counter[str] = Counter(rows=0)
    seen_obs: set[str] = set()
    for index, row in enumerate(rows, start=1):
        counter["rows"] += 1
        extra_keys = set(row) - PUBLIC_OBSERVATION_KEYS
        missing_keys = PUBLIC_OBSERVATION_REQUIRED_KEYS - set(row)
        if extra_keys:
            add_error(errors, path, index, f"unexpected keys: {', '.join(sorted(extra_keys))}")
        if missing_keys:
            add_error(errors, path, index, f"missing keys: {', '.join(sorted(missing_keys))}")
        if row.get("obs_id") in seen_obs:
            add_error(errors, path, index, f"duplicate obs_id {row.get('obs_id')}")
        seen_obs.add(row.get("obs_id", ""))
        if str(row.get("source", "")).startswith("synthetic_"):
            add_error(errors, path, index, f"synthetic source visible: {row.get('source')}")
        banned_hits = collect_banned_keys(row, OBSERVATION_BANNED_KEYS)
        if banned_hits:
            add_error(errors, path, index, f"banned keys: {', '.join(banned_hits)}")
        if contains_absolute_local_path(row):
            add_error(errors, path, index, "contains absolute local path")
    return counter


def validate_manifest(path: Path, errors: list[str]) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if contains_absolute_local_path(manifest):
        add_error(errors, path, None, "manifest contains absolute local path")
    for field in ("artifact_version", "task_specs", "queries", "observation_streams"):
        if field not in manifest:
            add_error(errors, path, None, f"missing manifest field {field}")
    return manifest


def build_report(
    *,
    public_dir: Path,
    manifest: dict[str, Any],
    task_count: int,
    query_counts: Counter[str],
    stream_counts: dict[str, int],
    errors: list[str],
) -> str:
    query_rows = ["| query_type | count |", "| --- | ---: |"]
    for query_type, count in sorted(query_counts.items()):
        query_rows.append(f"| `{query_type}` | {count} |")

    stream_rows = ["| stream | observations |", "| --- | ---: |"]
    for name, count in sorted(stream_counts.items()):
        stream_rows.append(f"| `{name}` | {count} |")

    error_text = "\n".join(f"- {error}" for error in errors[:50]) if errors else "- none"
    status = "PASS" if not errors else "FAIL"
    return f"""# Public Artifact Validation v0

本报告由 `tools/artifacts/validate_public_artifacts.py` 生成。

## Status

```text
{status}
```

## Public Directory

```text
{public_dir}
```

## Summary

| item | value |
| --- | ---: |
| task specs | {task_count} |
| query rows | {sum(query_counts.values())} |
| observation streams | {len(stream_counts)} |
| validation errors | {len(errors)} |

## Query Counts

{chr(10).join(query_rows)}

## Stream Counts

{chr(10).join(stream_rows)}

## Manifest Version

```text
{manifest.get("artifact_version", "unknown")}
```

## Errors

{error_text}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate sanitized public EviStateBench artifacts.")
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if validation fails.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []

    manifest_path = args.public_dir / "manifest.json"
    task_specs_path = args.public_dir / "task_specs.jsonl"
    queries_path = args.public_dir / "queries.jsonl"
    stream_dir = args.public_dir / "observation_streams"

    for path in (manifest_path, task_specs_path, queries_path):
        if not path.exists():
            add_error(errors, path, None, "required public artifact missing")
    if not stream_dir.exists():
        add_error(errors, stream_dir, None, "observation stream directory missing")

    manifest = validate_manifest(manifest_path, errors) if manifest_path.exists() else {}
    task_counter = (
        validate_task_specs(task_specs_path, errors)
        if task_specs_path.exists()
        else Counter()
    )
    task_spec_ids = {
        row.get("task_spec_id", "")
        for row in read_jsonl(task_specs_path)
    } if task_specs_path.exists() else set()
    query_counts = (
        validate_queries(queries_path, task_spec_ids, errors)
        if queries_path.exists()
        else Counter()
    )
    stream_counts: dict[str, int] = {}
    if stream_dir.exists():
        for path in iter_jsonl_paths(stream_dir):
            counts = validate_observation_stream(path, errors)
            stream_name = stream_name_for_path(path)
            if stream_name in stream_counts:
                add_error(errors, path, None, f"duplicate stream name {stream_name}")
            stream_counts[stream_name] = counts["rows"]

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            public_dir=args.public_dir,
            manifest=manifest,
            task_count=task_counter["rows"],
            query_counts=query_counts,
            stream_counts=stream_counts,
            errors=errors,
        ),
        encoding="utf-8",
    )

    result = {
        "status": "PASS" if not errors else "FAIL",
        "public_dir": str(args.public_dir),
        "report": str(args.report),
        "task_specs": task_counter["rows"],
        "queries": sum(query_counts.values()),
        "streams": stream_counts,
        "errors": len(errors),
        "error_sample": errors[:10],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
