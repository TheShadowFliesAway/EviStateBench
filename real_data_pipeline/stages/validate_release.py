#!/usr/bin/env python3
"""Release-grade validation for EviStateBench public artifacts.

This stage is stricter than the public artifact sanitizer.  It checks whether
an artifact is ready to be treated as a reproducible benchmark release package,
while still allowing a pilot artifact to pass with documented limitations.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "public_v7_scale72_seed6_ideal_full"
)

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

PUBLIC_OBSERVATION_BANNED_KEYS = {
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
PUBLIC_QUERY_BANNED_KEYS = {
    "truth",
    "truth_value",
    "ground_truth",
    "answer",
    "answer_type",
    "goal_state_count",
    "goal_states",
    "source_file",
}
PUBLIC_TASK_SPEC_BANNED_KEYS = {
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
VALID_ANSWER_TYPES = {"STATE_ANSWER", "STATE_DIFF_ANSWER", "GOAL_ANSWER"}
EXPECTED_RELEASE_STREAMS = {
    "clean",
    "delay",
    "out_of_order",
    "missing",
    "low_confidence",
    "conflict",
    "mixed",
}
FINAL_REQUIRED_QUERY_TYPES = {
    "CHECK_STATE",
    "AS_OF_STATE",
    "STATE_DIFF",
    "CHECK_GOAL",
    "WHY_STATE",
    "FIND_UNCERTAIN_STATES",
    "CHECK_PRECONDITION",
    "FAILURE_LOCALIZATION",
}
FINAL_TASK_SPECS = 450
FINAL_QUERIES = 8000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def open_text(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with open_text(path) as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def stream_name_for_path(path: Path) -> str:
    name = path.name
    if name.endswith(".jsonl.gz"):
        return name[: -len(".jsonl.gz")]
    if name.endswith(".jsonl"):
        return name[: -len(".jsonl")]
    return path.stem


def resolve_artifact_path(artifact_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = REPO_ROOT / path
    if candidate.exists():
        return candidate
    return artifact_dir / path


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


def collect_banned_keys(value: Any, banned: set[str], prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            if key in banned:
                hits.append(next_prefix)
            hits.extend(collect_banned_keys(item, banned, next_prefix))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(collect_banned_keys(item, banned, f"{prefix}[{index}]"))
    return hits


def add_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    category: str,
    message: str,
    path: Path | None = None,
    row: int | None = None,
) -> None:
    issue = {
        "severity": severity,
        "category": category,
        "message": message,
    }
    if path is not None:
        issue["path"] = rel(path)
    if row is not None:
        issue["row"] = row
    issues.append(issue)


def count_jsonl(path: Path) -> int:
    rows = 0
    with open_text(path) as f:
        for line in f:
            if line.strip():
                rows += 1
    return rows


def collect_public_queries(path: Path, issues: list[dict[str, Any]]) -> tuple[set[str], Counter[str]]:
    query_ids: set[str] = set()
    query_counts: Counter[str] = Counter()
    seen: set[str] = set()
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        query_id = row.get("query_id")
        query_type = str(row.get("query_type", "unknown"))
        query_counts[query_type] += 1
        for field in ("query_id", "query_type", "episode_id", "task_id", "task_spec_id"):
            if field not in row:
                add_issue(
                    issues,
                    severity="error",
                    category="public_query_schema",
                    message=f"missing required field {field}",
                    path=path,
                    row=row_number,
                )
        if query_id in seen:
            add_issue(
                issues,
                severity="error",
                category="public_query_schema",
                message=f"duplicate query_id {query_id}",
                path=path,
                row=row_number,
            )
        if query_id:
            seen.add(query_id)
            query_ids.add(str(query_id))
        banned_hits = collect_banned_keys(row, PUBLIC_QUERY_BANNED_KEYS)
        if banned_hits:
            add_issue(
                issues,
                severity="error",
                category="public_hidden_leakage",
                message=f"banned query keys: {', '.join(banned_hits[:8])}",
                path=path,
                row=row_number,
            )
        if contains_absolute_local_path(row):
            add_issue(
                issues,
                severity="error",
                category="public_hidden_leakage",
                message="public query row contains absolute local path",
                path=path,
                row=row_number,
            )
    return query_ids, query_counts


def validate_task_specs(path: Path, issues: list[dict[str, Any]]) -> tuple[set[str], int]:
    task_spec_ids: set[str] = set()
    seen: set[str] = set()
    rows = 0
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        rows += 1
        for field in ("task_spec_id", "episode_id", "task_id", "goal_states"):
            if field not in row:
                add_issue(
                    issues,
                    severity="error",
                    category="public_task_spec_schema",
                    message=f"missing required field {field}",
                    path=path,
                    row=row_number,
                )
        task_spec_id = row.get("task_spec_id")
        if task_spec_id in seen:
            add_issue(
                issues,
                severity="error",
                category="public_task_spec_schema",
                message=f"duplicate task_spec_id {task_spec_id}",
                path=path,
                row=row_number,
            )
        if task_spec_id:
            seen.add(task_spec_id)
            task_spec_ids.add(str(task_spec_id))
        banned_hits = collect_banned_keys(row, PUBLIC_TASK_SPEC_BANNED_KEYS)
        if banned_hits:
            add_issue(
                issues,
                severity="error",
                category="public_hidden_leakage",
                message=f"banned task spec keys: {', '.join(banned_hits[:8])}",
                path=path,
                row=row_number,
            )
        if contains_absolute_local_path(row):
            add_issue(
                issues,
                severity="error",
                category="public_hidden_leakage",
                message="public task spec row contains absolute local path",
                path=path,
                row=row_number,
            )
    return task_spec_ids, rows


def validate_public_stream(path: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    rows = 0
    by_episode: Counter[str] = Counter()
    by_predicate: Counter[str] = Counter()
    late_rows = 0
    low_confidence_rows = 0
    min_event_time: float | None = None
    max_event_time: float | None = None
    max_arrival_delay = 0.0
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        rows += 1
        extra = set(row) - PUBLIC_OBSERVATION_KEYS
        missing = PUBLIC_OBSERVATION_REQUIRED_KEYS - set(row)
        if extra:
            add_issue(
                issues,
                severity="error",
                category="public_observation_schema",
                message=f"unexpected observation keys: {', '.join(sorted(extra))}",
                path=path,
                row=row_number,
            )
        if missing:
            add_issue(
                issues,
                severity="error",
                category="public_observation_schema",
                message=f"missing observation keys: {', '.join(sorted(missing))}",
                path=path,
                row=row_number,
            )
        obs_id = row.get("obs_id")
        if obs_id in seen:
            add_issue(
                issues,
                severity="error",
                category="public_observation_schema",
                message=f"duplicate obs_id {obs_id}",
                path=path,
                row=row_number,
            )
        if obs_id:
            seen.add(str(obs_id))
        banned_hits = collect_banned_keys(row, PUBLIC_OBSERVATION_BANNED_KEYS)
        if banned_hits:
            add_issue(
                issues,
                severity="error",
                category="public_hidden_leakage",
                message=f"banned observation keys: {', '.join(banned_hits[:8])}",
                path=path,
                row=row_number,
            )
        if contains_absolute_local_path(row):
            add_issue(
                issues,
                severity="error",
                category="public_hidden_leakage",
                message="public observation row contains absolute local path",
                path=path,
                row=row_number,
            )
        try:
            event_time = float(row.get("event_time", 0.0) or 0.0)
            arrival_time = float(row.get("arrival_time", event_time) or event_time)
            confidence = float(row.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            add_issue(
                issues,
                severity="error",
                category="timestamp_or_confidence",
                message="event_time, arrival_time, or confidence is not numeric",
                path=path,
                row=row_number,
            )
            event_time = 0.0
            arrival_time = 0.0
            confidence = 0.0
        if arrival_time < event_time:
            add_issue(
                issues,
                severity="error",
                category="timestamp_or_confidence",
                message="arrival_time is earlier than event_time",
                path=path,
                row=row_number,
            )
        if not 0.0 <= confidence <= 1.0:
            add_issue(
                issues,
                severity="error",
                category="timestamp_or_confidence",
                message=f"confidence outside [0,1]: {confidence}",
                path=path,
                row=row_number,
            )
        delay = arrival_time - event_time
        if delay > 0:
            late_rows += 1
            max_arrival_delay = max(max_arrival_delay, delay)
        if confidence < 0.8:
            low_confidence_rows += 1
        min_event_time = event_time if min_event_time is None else min(min_event_time, event_time)
        max_event_time = event_time if max_event_time is None else max(max_event_time, event_time)
        by_episode[str(row.get("episode_id", "unknown"))] += 1
        by_predicate[str(row.get("predicate_name", "unknown"))] += 1
    return {
        "rows": rows,
        "episodes": len(by_episode),
        "top_predicates": dict(by_predicate.most_common(12)),
        "late_rows": late_rows,
        "low_confidence_rows": low_confidence_rows,
        "min_event_time": min_event_time,
        "max_event_time": max_event_time,
        "max_arrival_delay": max_arrival_delay,
    }


def validate_answer_sets(
    *,
    answer_dir: Path,
    public_query_ids: set[str],
    public_stream_names: set[str],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    answer_stats: dict[str, Any] = {}
    if not answer_dir.exists():
        add_issue(
            issues,
            severity="error",
            category="answer_sets",
            message="answer_sets_v0 directory missing",
            path=answer_dir,
        )
        return answer_stats

    answer_paths = sorted(answer_dir.glob("*.jsonl"))
    answer_streams = {path.stem for path in answer_paths}
    missing_streams = sorted(public_stream_names - answer_streams)
    extra_streams = sorted(answer_streams - public_stream_names)
    if missing_streams:
        add_issue(
            issues,
            severity="error",
            category="answer_sets",
            message=f"answer sets missing public streams: {', '.join(missing_streams)}",
            path=answer_dir,
        )
    if extra_streams:
        add_issue(
            issues,
            severity="error",
            category="answer_sets",
            message=f"answer sets include non-public streams: {', '.join(extra_streams)}",
            path=answer_dir,
        )

    for path in answer_paths:
        query_ids: set[str] = set()
        duplicate_ids: list[str] = []
        answer_type_counts: Counter[str] = Counter()
        query_type_counts: Counter[str] = Counter()
        status_counts: Counter[str] = Counter()
        for row_number, row in enumerate(iter_jsonl(path), start=1):
            query_id = row.get("query_id")
            if query_id in query_ids:
                duplicate_ids.append(str(query_id))
            if query_id:
                query_ids.add(str(query_id))
            answer_type = str(row.get("answer_type", "unknown"))
            query_type = str(row.get("query_type", "unknown"))
            answer_type_counts[answer_type] += 1
            query_type_counts[query_type] += 1
            status_counts[str(row.get("status", "n/a"))] += 1
            if answer_type not in VALID_ANSWER_TYPES:
                add_issue(
                    issues,
                    severity="error",
                    category="answer_sets",
                    message=f"unsupported answer_type {answer_type}",
                    path=path,
                    row=row_number,
                )
        missing_ids = public_query_ids - query_ids
        extra_ids = query_ids - public_query_ids
        if missing_ids:
            add_issue(
                issues,
                severity="error",
                category="answer_sets",
                message=f"{len(missing_ids)} public queries missing answers",
                path=path,
            )
        if extra_ids:
            add_issue(
                issues,
                severity="error",
                category="answer_sets",
                message=f"{len(extra_ids)} extra answer query ids",
                path=path,
            )
        if duplicate_ids:
            add_issue(
                issues,
                severity="error",
                category="answer_sets",
                message=f"duplicate answer query ids: {', '.join(duplicate_ids[:8])}",
                path=path,
            )
        answer_stats[path.stem] = {
            "rows": len(query_ids),
            "answer_type_counts": dict(answer_type_counts),
            "query_type_counts": dict(query_type_counts),
            "status_counts": dict(status_counts),
            "missing_public_query_ids": len(missing_ids),
            "extra_query_ids": len(extra_ids),
            "duplicate_query_ids": len(duplicate_ids),
        }
    return answer_stats


def validate_manifests(
    artifact_dir: Path,
    public_manifest: dict[str, Any],
    public_counts: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    manifest_path = artifact_dir / "public_v0" / "manifest.json"
    if contains_absolute_local_path(public_manifest):
        add_issue(
            issues,
            severity="error",
            category="public_hidden_leakage",
            message="public manifest contains absolute local path",
            path=manifest_path,
        )
    if public_manifest.get("task_specs", {}).get("count") != public_counts.get("task_specs"):
        add_issue(
            issues,
            severity="error",
            category="manifest_count_mismatch",
            message="task_specs count does not match manifest",
            path=manifest_path,
        )
    if public_manifest.get("queries", {}).get("count") != public_counts.get("queries"):
        add_issue(
            issues,
            severity="error",
            category="manifest_count_mismatch",
            message="queries count does not match manifest",
            path=manifest_path,
        )
    manifest_streams = public_manifest.get("observation_streams", {})
    for name, stats in public_counts.get("streams", {}).items():
        manifest_rows = manifest_streams.get(name, {}).get("observations")
        if manifest_rows != stats.get("rows"):
            add_issue(
                issues,
                severity="error",
                category="manifest_count_mismatch",
                message=f"stream {name} count {stats.get('rows')} does not match manifest {manifest_rows}",
                path=manifest_path,
            )


def scan_evaluator_only_manifests(artifact_dir: Path, issues: list[dict[str, Any]]) -> None:
    """Flag portability issues outside public input without treating them as leakage."""
    for rel_path in ("answer_sets_v0/manifest.json", "build_commands.json"):
        path = artifact_dir / rel_path
        if not path.exists():
            continue
        try:
            payload = read_json(path)
        except json.JSONDecodeError:
            add_issue(
                issues,
                severity="warning",
                category="release_portability",
                message=f"{rel_path} is not valid JSON",
                path=path,
            )
            continue
        if contains_absolute_local_path(payload):
            add_issue(
                issues,
                severity="warning",
                category="release_portability",
                message=f"{rel_path} contains local absolute paths; sanitize before external release",
                path=path,
            )


def collect_release_files(artifact_dir: Path, output_dir: Path) -> list[Path]:
    roots = [
        artifact_dir / "public_v0",
        artifact_dir / "answer_sets_v0",
        artifact_dir / "reports",
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if output_dir in path.parents:
                continue
            files.append(path)
    return sorted(files)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(path: Path, files: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines: list[str] = []
    for file_path in files:
        digest = sha256_file(file_path)
        rel_path = rel(file_path)
        rows.append({"sha256": digest, "path": rel_path})
        lines.append(f"{digest}  {rel_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def load_optional_profile(artifact_dir: Path) -> dict[str, Any]:
    path = artifact_dir / "reports" / "benchmark_profile_summary_v1.json"
    return read_json(path) if path.exists() else {}


def determine_status(issues: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    if any(issue["severity"] == "error" for issue in issues):
        return "FAIL"
    if any(issue["severity"] == "warning" for issue in issues):
        return "PASS_WITH_LIMITS"
    if profile.get("scale_readiness", {}).get("status") == "PASS_WITH_LIMITS":
        return "PASS_WITH_LIMITS"
    return "PASS"


def build_public_hidden_audit(
    *,
    status: str,
    public_counts: dict[str, Any],
    issues: list[dict[str, Any]],
) -> str:
    leakage_issues = [
        issue for issue in issues if issue["category"] in {"public_hidden_leakage", "release_portability"}
    ]
    rows = ["| severity | category | path | message |", "| --- | --- | --- | --- |"]
    if leakage_issues:
        for issue in leakage_issues[:100]:
            rows.append(
                f"| `{issue['severity']}` | `{issue['category']}` | "
                f"`{issue.get('path', '')}` | {issue['message']} |"
            )
    else:
        rows.append("| n/a | n/a | n/a | none |")
    return f"""# Public-Hidden Boundary Audit v0

本报告由 `real_data_pipeline/stages/validate_release.py` 生成。

## Status

```text
{status}
```

## Public Input Checked

```text
public_v0/manifest.json
public_v0/task_specs.jsonl
public_v0/queries.jsonl
public_v0/observation_streams/*.jsonl.gz
```

## Public Counts

| item | value |
| --- | ---: |
| task specs | {public_counts.get('task_specs', 0)} |
| queries | {public_counts.get('queries', 0)} |
| streams | {len(public_counts.get('streams', {}))} |

## Boundary Issues

{chr(10).join(rows)}

## Interpretation

`public_v0/` 是 baseline 运行时唯一允许读取的输入。`answer_sets_v0/` 是
evaluator-only 标准答案；它可以随 benchmark 给 baseline 作者做自评，但不能参与
prediction generation。
"""


def build_artifact_card(
    *,
    artifact_dir: Path,
    status: str,
    public_counts: dict[str, Any],
    answer_stats: dict[str, Any],
    profile: dict[str, Any],
    issues: list[dict[str, Any]],
) -> str:
    query_counts = public_counts.get("query_type_counts", {})
    stream_rows = ["| stream | observations | answer rows |", "| --- | ---: | ---: |"]
    for name, stats in sorted(public_counts.get("streams", {}).items()):
        stream_rows.append(
            f"| `{name}` | {stats.get('rows', 0)} | {answer_stats.get(name, {}).get('rows', 0)} |"
        )
    query_rows = ["| query_type | count |", "| --- | ---: |"]
    for query_type, count in sorted(query_counts.items()):
        query_rows.append(f"| `{query_type}` | {count} |")
    limitations = [
        "activity_instance_id coverage is limited in the current v7 pilot artifact.",
        "queries are target-scoped, not full task-level BDDL semantics.",
        "no perception-derived or low-level rollout subset is included yet.",
        "formal baseline predictions are not part of this artifact.",
    ]
    for issue in issues:
        if issue["severity"] == "warning":
            limitations.append(issue["message"])
    limitation_text = "\n".join(f"- {item}" for item in dict.fromkeys(limitations))
    return f"""# EviStateBench Artifact Card v0

## Artifact

```text
{rel(artifact_dir)}
```

## Release Validation Status

```text
{status}
```

## Intended Use

This artifact is intended for evaluating temporal task-state view maintenance
over BEHAVIOR / OmniGibson-derived structured embodied observation streams.

It is not an end-to-end robot control benchmark, not a VLM benchmark, and not a
complete BEHAVIOR-1K benchmark.

## Counts

| item | value |
| --- | ---: |
| episodes | {profile.get('counts', {}).get('episodes', 'n/a')} |
| task specs | {public_counts.get('task_specs', 0)} |
| queries | {public_counts.get('queries', 0)} |
| public streams | {len(public_counts.get('streams', {}))} |
| clean observations | {public_counts.get('streams', {}).get('clean', {}).get('rows', 'n/a')} |

## Query Types

{chr(10).join(query_rows)}

## Streams

{chr(10).join(stream_rows)}

## Public / Evaluator-Only Boundary

Baseline systems may read only `public_v0/`.

Evaluator-only files:

```text
answer_sets_v0/
reports/
```

## Known Limitations

{limitation_text}
"""


def build_data_statement(
    *,
    artifact_dir: Path,
    status: str,
    public_counts: dict[str, Any],
    profile: dict[str, Any],
) -> str:
    predicate_counts = profile.get("target_predicate_counts", {})
    predicate_rows = ["| predicate | target events |", "| --- | ---: |"]
    for predicate, count in sorted(predicate_counts.items(), key=lambda item: (-item[1], item[0])):
        predicate_rows.append(f"| `{predicate}` | {count} |")
    return f"""# EviStateBench Data Statement v0

## Dataset Name

```text
EviStateBench real benchmark artifact
```

## Artifact Path

```text
{rel(artifact_dir)}
```

## Validation Status

```text
{status}
```

## Source

The artifact is generated from BEHAVIOR / OmniGibson-derived simulator episodes.
The benchmark uses simulator truth to construct hidden state timelines and
ground-truth answer sets. Public observation streams are structured
StateObservation streams derived from clean simulator-state observations and
controlled perturbation regimes.

## Public Data

```text
public_v0/task_specs.jsonl
public_v0/queries.jsonl
public_v0/observation_streams/*.jsonl.gz
```

## Evaluator-Only Data

```text
answer_sets_v0/*.jsonl
```

These files are distributed for local self-evaluation and official evaluation.
They must not be read by baseline systems when generating predictions.

## Current Scale

| item | value |
| --- | ---: |
| task specs | {public_counts.get('task_specs', 0)} |
| queries | {public_counts.get('queries', 0)} |
| streams | {len(public_counts.get('streams', {}))} |
| clean observations | {public_counts.get('streams', {}).get('clean', {}).get('rows', 'n/a')} |

## Target Predicates

{chr(10).join(predicate_rows)}

## Limitations And Biases

- The current artifact is simulator-grounded and does not claim real-world robot deployment validity.
- Clean observations are structured state observations, not raw RGB / depth / VLM observations.
- Current query semantics are mainly target-scoped.
- Current v7 should be treated as a pilot release candidate until diversity, query semantics, and baseline discriminativeness are expanded.
"""


def build_reproducibility_report(
    *,
    artifact_dir: Path,
    output_dir: Path,
    checksum_rows: list[dict[str, str]],
    status: str,
) -> str:
    env_candidates = [
        REPO_ROOT / "real_data_pipeline" / "env_behavior.sh",
        REPO_ROOT / "pyproject.toml",
    ]
    env_rows = ["| file | exists |", "| --- | --- |"]
    for path in env_candidates:
        env_rows.append(f"| `{rel(path)}` | `{path.exists()}` |")
    return f"""# Reproducibility Report v0

## Status

```text
{status}
```

## Artifact

```text
{rel(artifact_dir)}
```

## Checksums

Checksum file:

```text
{rel(output_dir / 'checksums.sha256')}
```

Files covered:

```text
{len(checksum_rows)}
```

The checksum list covers release-visible files under `public_v0/`,
`answer_sets_v0/`, and pre-existing `reports/`. It excludes hidden
`intermediate/` files.

## Environment Pointers

{chr(10).join(env_rows)}

## Reproduction Boundary

This validation confirms the packaged artifact can be checked and evaluated. It
does not prove that the full BEHAVIOR / OmniGibson generation can be rerun on a
fresh machine without installing the upstream simulator, assets, and GPU
runtime.
"""


def build_license_and_source_statement(*, artifact_dir: Path, status: str) -> str:
    return f"""# License And Source Statement v0

## Status

```text
{status}
```

## Artifact

```text
{rel(artifact_dir)}
```

## EviStateBench Files

The EviStateBench code, schemas, benchmark manifests, generated public
observation streams, query files, answer sets, evaluator scripts, and reports
are project artifacts. Their release license must be declared by the project
repository before external distribution.

## Upstream Sources

The benchmark is derived from BEHAVIOR / OmniGibson task definitions,
simulator state, and generated episodes. Upstream simulator code, task assets,
and official datasets are not re-licensed by this artifact.

Required upstream source information for a final release:

```text
BEHAVIOR-1K repository commit / tag
OmniGibson version
BDDL version
BEHAVIOR assets snapshot or asset lock report
official demo/rawdata dataset revision when used
local patches required for headless generation or replay
```

## Redistribution Boundary

Public benchmark inputs:

```text
public_v0/
```

Evaluator-only data:

```text
answer_sets_v0/
reports/
```

Hidden generator intermediates such as simulator truth timelines are not public
input to baseline systems. Any external release must preserve this boundary.

## Citation Boundary

Papers using this artifact should cite EviStateBench and the upstream
BEHAVIOR / OmniGibson sources used to generate or validate the episodes.
"""


def write_csv_issues(path: Path, issues: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["severity", "category", "path", "row", "message"],
        )
        writer.writeheader()
        for issue in issues:
            writer.writerow(
                {
                    "severity": issue.get("severity", ""),
                    "category": issue.get("category", ""),
                    "path": issue.get("path", ""),
                    "row": issue.get("row", ""),
                    "message": issue.get("message", ""),
                }
            )


def build_release_report(
    *,
    artifact_dir: Path,
    status: str,
    public_counts: dict[str, Any],
    answer_stats: dict[str, Any],
    issues: list[dict[str, Any]],
    output_dir: Path,
) -> str:
    issue_counts = Counter(issue["severity"] for issue in issues)
    issue_rows = ["| severity | category | path | message |", "| --- | --- | --- | --- |"]
    if issues:
        for issue in issues[:100]:
            issue_rows.append(
                f"| `{issue['severity']}` | `{issue['category']}` | "
                f"`{issue.get('path', '')}` | {issue['message']} |"
            )
    else:
        issue_rows.append("| n/a | n/a | n/a | none |")
    stream_rows = ["| stream | observations | answer rows |", "| --- | ---: | ---: |"]
    for stream, stats in sorted(public_counts.get("streams", {}).items()):
        stream_rows.append(
            f"| `{stream}` | {stats.get('rows', 0)} | {answer_stats.get(stream, {}).get('rows', 0)} |"
        )
    return f"""# Release Validation Report v0

本报告由 `real_data_pipeline/stages/validate_release.py` 生成。

## Status

```text
{status}
```

## Artifact

```text
{rel(artifact_dir)}
```

## Summary

| item | value |
| --- | ---: |
| task specs | {public_counts.get('task_specs', 0)} |
| queries | {public_counts.get('queries', 0)} |
| streams | {len(public_counts.get('streams', {}))} |
| errors | {issue_counts.get('error', 0)} |
| warnings | {issue_counts.get('warning', 0)} |

## Stream Coverage

{chr(10).join(stream_rows)}

## Generated Release Files

```text
{rel(output_dir / 'release_validation_summary.json')}
{rel(output_dir / 'release_validation_report.md')}
{rel(output_dir / 'public_hidden_boundary_audit.md')}
{rel(output_dir / 'artifact_card.md')}
{rel(output_dir / 'data_statement.md')}
{rel(output_dir / 'license_and_source_statement.md')}
{rel(output_dir / 'reproducibility_report.md')}
{rel(output_dir / 'checksums.sha256')}
{rel(output_dir / 'issues.csv')}
```

## Issues

{chr(10).join(issue_rows)}

## Interpretation

`PASS` means no release validator errors or warnings were found. `PASS_WITH_LIMITS`
means the package is structurally usable but has documented limitations that
must be disclosed. `FAIL` means the artifact should not be used as a release
candidate until errors are fixed.
"""


def add_final_release_requirements(
    *,
    artifact_dir: Path,
    public_counts: dict[str, Any],
    profile: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Enforce the strong-version release contract from ICDE_BENCHMARK_ENRICHMENT_PLAN.md."""
    task_specs = int(public_counts.get("task_specs", 0) or 0)
    queries = int(public_counts.get("queries", 0) or 0)
    query_types = set(public_counts.get("query_type_counts", {}))
    streams = set(public_counts.get("streams", {}))

    if task_specs != FINAL_TASK_SPECS:
        add_issue(
            issues,
            severity="error",
            category="final_release_contract",
            message=f"final release requires {FINAL_TASK_SPECS} task specs / episodes, found {task_specs}",
            path=artifact_dir / "public_v0" / "task_specs.jsonl",
        )
    if queries != FINAL_QUERIES:
        add_issue(
            issues,
            severity="error",
            category="final_release_contract",
            message=f"final release requires {FINAL_QUERIES} queries, found {queries}",
            path=artifact_dir / "public_v0" / "queries.jsonl",
        )

    missing_query_types = sorted(FINAL_REQUIRED_QUERY_TYPES - query_types)
    if missing_query_types:
        add_issue(
            issues,
            severity="error",
            category="final_release_contract",
            message=f"final release missing query types: {', '.join(missing_query_types)}",
            path=artifact_dir / "public_v0" / "queries.jsonl",
        )

    missing_streams = sorted(EXPECTED_RELEASE_STREAMS - streams)
    if missing_streams:
        add_issue(
            issues,
            severity="error",
            category="final_release_contract",
            message=f"final release missing streams: {', '.join(missing_streams)}",
            path=artifact_dir / "public_v0" / "observation_streams",
        )

    if profile.get("scale_readiness", {}).get("status") != "PASS":
        add_issue(
            issues,
            severity="error",
            category="final_release_contract",
            message="final release requires benchmark profile scale_readiness PASS",
            path=artifact_dir / "reports" / "benchmark_profile_summary_v1.json",
        )

    baseline_format_path = artifact_dir / "baseline_prediction_format.md"
    if not baseline_format_path.exists():
        add_issue(
            issues,
            severity="error",
            category="final_release_contract",
            message="final release requires baseline_prediction_format.md",
            path=baseline_format_path,
        )


def validate_release(artifact_dir: Path, output_dir: Path, *, final_release: bool = False) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    required_paths = [
        artifact_dir / "public_v0" / "manifest.json",
        artifact_dir / "public_v0" / "task_specs.jsonl",
        artifact_dir / "public_v0" / "queries.jsonl",
        artifact_dir / "public_v0" / "observation_streams",
        artifact_dir / "answer_sets_v0",
        artifact_dir / "reports",
    ]
    for path in required_paths:
        if not path.exists():
            add_issue(
                issues,
                severity="error",
                category="required_path",
                message="required release path missing",
                path=path,
            )

    public_manifest_path = artifact_dir / "public_v0" / "manifest.json"
    public_manifest = read_json(public_manifest_path) if public_manifest_path.exists() else {}
    task_spec_ids, task_spec_count = (
        validate_task_specs(artifact_dir / "public_v0" / "task_specs.jsonl", issues)
        if (artifact_dir / "public_v0" / "task_specs.jsonl").exists()
        else (set(), 0)
    )
    public_query_ids, query_type_counts = (
        collect_public_queries(artifact_dir / "public_v0" / "queries.jsonl", issues)
        if (artifact_dir / "public_v0" / "queries.jsonl").exists()
        else (set(), Counter())
    )
    query_rows = sum(query_type_counts.values())

    stream_stats: dict[str, Any] = {}
    stream_dir = artifact_dir / "public_v0" / "observation_streams"
    if stream_dir.exists():
        stream_paths = sorted([*stream_dir.glob("*.jsonl"), *stream_dir.glob("*.jsonl.gz")])
        for path in stream_paths:
            stream_name = stream_name_for_path(path)
            if stream_name in stream_stats:
                add_issue(
                    issues,
                    severity="error",
                    category="public_streams",
                    message=f"duplicate stream name {stream_name}",
                    path=path,
                )
            stream_stats[stream_name] = validate_public_stream(path, issues)

    public_stream_names = set(stream_stats)
    missing_expected_streams = sorted(EXPECTED_RELEASE_STREAMS - public_stream_names)
    if missing_expected_streams:
        add_issue(
            issues,
            severity="warning",
            category="release_coverage",
            message=f"missing expected diagnostic streams: {', '.join(missing_expected_streams)}",
            path=stream_dir,
        )

    public_counts = {
        "task_specs": task_spec_count,
        "queries": query_rows,
        "query_type_counts": dict(query_type_counts),
        "streams": stream_stats,
    }
    validate_manifests(artifact_dir, public_manifest, public_counts, issues)
    answer_stats = validate_answer_sets(
        answer_dir=artifact_dir / "answer_sets_v0",
        public_query_ids=public_query_ids,
        public_stream_names=public_stream_names,
        issues=issues,
    )
    scan_evaluator_only_manifests(artifact_dir, issues)

    for query_path in (artifact_dir / "public_v0" / "queries.jsonl",):
        if query_path.exists():
            for row_number, row in enumerate(iter_jsonl(query_path), start=1):
                if row.get("task_spec_id") not in task_spec_ids:
                    add_issue(
                        issues,
                        severity="error",
                        category="public_query_schema",
                        message=f"unknown task_spec_id {row.get('task_spec_id')}",
                        path=query_path,
                        row=row_number,
                    )

    profile = load_optional_profile(artifact_dir)
    profile_status = profile.get("scale_readiness", {}).get("status")
    if profile_status == "PASS_WITH_LIMITS":
        add_issue(
            issues,
            severity="warning",
            category="scale_readiness",
            message="profile report status is PASS_WITH_LIMITS; disclose pilot limitations",
            path=artifact_dir / "reports" / "benchmark_profile_summary_v1.json",
        )
    if not (artifact_dir / "reports" / "paper_tables_v0" / "baseline_results.csv").exists():
        add_issue(
            issues,
            severity="warning",
            category="baseline_results",
            message="baseline results table missing; benchmark discriminativeness is not established",
            path=artifact_dir / "reports" / "paper_tables_v0",
        )
    else:
        baseline_csv = artifact_dir / "reports" / "paper_tables_v0" / "baseline_results.csv"
        if count_jsonl_like_csv_data_rows(baseline_csv) == 0:
            add_issue(
                issues,
                severity="warning",
                category="baseline_results",
                message="baseline results table has no data rows; benchmark discriminativeness is not established",
                path=baseline_csv,
            )

    release_files = collect_release_files(artifact_dir, output_dir)
    checksum_rows = write_checksums(output_dir / "checksums.sha256", release_files)
    if final_release:
        add_final_release_requirements(
            artifact_dir=artifact_dir,
            public_counts=public_counts,
            profile=profile,
            issues=issues,
        )

    status = determine_status(issues, profile)

    summary = {
        "generated_at": utc_now(),
        "artifact_dir": rel(artifact_dir),
        "output_dir": rel(output_dir),
        "status": status,
        "public_counts": public_counts,
        "answer_stats": answer_stats,
        "issue_counts": dict(Counter(issue["severity"] for issue in issues)),
        "issues": issues,
        "checksums": {
            "path": rel(output_dir / "checksums.sha256"),
            "files": len(checksum_rows),
        },
        "release_interpretation": {
            "public_input": "public_v0 only",
            "evaluator_only": ["answer_sets_v0", "reports"],
            "baseline_disclaimer": "answer_sets_v0 must not be read when generating predictions",
            "final_release_mode": final_release,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "release_validation_summary.json", summary)
    write_csv_issues(output_dir / "issues.csv", issues)
    (output_dir / "release_validation_report.md").write_text(
        build_release_report(
            artifact_dir=artifact_dir,
            status=status,
            public_counts=public_counts,
            answer_stats=answer_stats,
            issues=issues,
            output_dir=output_dir,
        ),
        encoding="utf-8",
    )
    (output_dir / "public_hidden_boundary_audit.md").write_text(
        build_public_hidden_audit(status=status, public_counts=public_counts, issues=issues),
        encoding="utf-8",
    )
    (output_dir / "artifact_card.md").write_text(
        build_artifact_card(
            artifact_dir=artifact_dir,
            status=status,
            public_counts=public_counts,
            answer_stats=answer_stats,
            profile=profile,
            issues=issues,
        ),
        encoding="utf-8",
    )
    (output_dir / "data_statement.md").write_text(
        build_data_statement(
            artifact_dir=artifact_dir,
            status=status,
            public_counts=public_counts,
            profile=profile,
        ),
        encoding="utf-8",
    )
    (output_dir / "license_and_source_statement.md").write_text(
        build_license_and_source_statement(artifact_dir=artifact_dir, status=status),
        encoding="utf-8",
    )
    (output_dir / "reproducibility_report.md").write_text(
        build_reproducibility_report(
            artifact_dir=artifact_dir,
            output_dir=output_dir,
            checksum_rows=checksum_rows,
            status=status,
        ),
        encoding="utf-8",
    )
    return summary


def count_jsonl_like_csv_data_rows(path: Path) -> int:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    return max(0, len(rows) - 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an EviStateBench release artifact.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--final-release",
        action="store_true",
        help="Enforce the strong-version final release contract.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless status is PASS.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = artifact_dir / "reports" / "release_validation_v0"
    else:
        output_dir = output_dir.resolve()
    summary = validate_release(artifact_dir, output_dir, final_release=args.final_release)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "artifact_dir": summary["artifact_dir"],
                "output_dir": summary["output_dir"],
                "issue_counts": summary["issue_counts"],
                "checksums": summary["checksums"],
                "report": rel(output_dir / "release_validation_report.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.strict and summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
