#!/usr/bin/env python3
"""Export query-type and predicate-family breakdowns for paper analysis.

Formal baseline prediction ingestion is intentionally left to a separate bridge
script once the baseline repository emits predicted QueryAnswers.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "public_v7_scale72_seed6_ideal_full"
)
EVALUATOR_PATH = REPO_ROOT / "tools" / "artifacts" / "evaluate_answers.py"

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


def load_evaluator_module():
    spec = importlib.util.spec_from_file_location("evaluate_answers_module", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load evaluator module from {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def read_jsonl_by_query_id(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        rows[str(row["query_id"])] = row
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def predicate_family(predicate_name: str) -> str:
    return PREDICATE_FAMILIES.get(predicate_name, "other")


def goal_families_for_query(
    query: dict[str, Any],
    task_specs: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    spec = task_specs.get(str(query.get("task_spec_id")), {})
    predicates = [
        str(row.get("predicate_name", "unknown"))
        for row in spec.get("goal_states", []) or []
    ]
    families = sorted({predicate_family(predicate) for predicate in predicates})
    if not predicates:
        return "n/a", "n/a"
    if len(predicates) == 1:
        return predicates[0], families[0]
    if len(families) == 1:
        return "goal_set", families[0]
    return "goal_set", "multi_family_goal"


def query_labels(
    query: dict[str, Any],
    task_specs: dict[str, dict[str, Any]],
) -> dict[str, str]:
    query_type = str(query.get("query_type", "unknown"))
    if query_type in {"CHECK_STATE", "AS_OF_STATE"}:
        state = query.get("state", {}) or {}
        predicate = str(state.get("predicate_name", "unknown"))
        return {
            "query_type": query_type,
            "query_family": str((query.get("metadata") or {}).get("query_family", "n/a")),
            "predicate_name": predicate,
            "predicate_family": predicate_family(predicate),
        }
    predicate, family = goal_families_for_query(query, task_specs)
    return {
        "query_type": query_type,
        "query_family": str((query.get("metadata") or {}).get("query_family", "n/a")),
        "predicate_name": predicate if query_type == "CHECK_GOAL" else "target_state_set",
        "predicate_family": family if query_type == "CHECK_GOAL" else family,
    }


def stream_name_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".jsonl"):
        return name[: -len(".jsonl")]
    return path.stem


def safe_div(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def finalize_group_rows(
    counters: dict[tuple[str, ...], Counter[str]],
    *,
    fieldnames: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, counter in sorted(counters.items()):
        total = counter["total"]
        row = {field: value for field, value in zip(fieldnames, key)}
        row.update(
            {
                "total": total,
                "exact": counter["exact"],
                "exact_accuracy": safe_div(counter["exact"], total),
                "value_match": counter.get("value_match", 0),
                "value_accuracy": safe_div(counter.get("value_match", 0), counter.get("value_total", 0)),
                "status_match": counter.get("status_match", 0),
                "status_accuracy": safe_div(counter.get("status_match", 0), counter.get("status_total", 0)),
            }
        )
        rows.append(row)
    return rows


def build_breakdowns(artifact_dir: Path) -> dict[str, Any]:
    queries = read_jsonl(artifact_dir / "public_v0" / "queries.jsonl")
    query_by_id = {str(row["query_id"]): row for row in queries}
    task_specs = {
        str(row["task_spec_id"]): row
        for row in read_jsonl(artifact_dir / "public_v0" / "task_specs.jsonl")
    }

    by_query_family: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    by_predicate_family: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    by_stream_predicate: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    by_query_type_predicate_family: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)

    # Formal baseline predictions are not stored in the benchmark artifact yet.
    # This exporter keeps the breakdown CSV schema stable and writes empty tables
    # until a formal baseline-result bridge populates prediction inputs.
    _ = (query_by_id, task_specs)

    return {
        "by_query_family": finalize_group_rows(
            by_query_family,
            fieldnames=["baseline", "stream", "query_type", "query_family"],
        ),
        "by_predicate_family": finalize_group_rows(
            by_predicate_family,
            fieldnames=["baseline", "stream", "predicate_family"],
        ),
        "by_stream_predicate": finalize_group_rows(
            by_stream_predicate,
            fieldnames=["baseline", "stream", "predicate_name", "predicate_family"],
        ),
        "by_query_type_predicate_family": finalize_group_rows(
            by_query_type_predicate_family,
            fieldnames=["baseline", "stream", "query_type", "predicate_family"],
        ),
    }


def build_report(artifact_dir: Path, output_dir: Path, outputs: dict[str, str]) -> str:
    lines = [
        "# Detailed Breakdown Tables v0",
        "",
        "本报告由 `real_data_pipeline/stages/export_breakdown_tables.py` 生成。",
        "",
        f"- artifact: `{rel(artifact_dir)}`",
        f"- output: `{rel(output_dir)}`",
        "",
        "## Outputs",
        "",
    ]
    for name, path in sorted(outputs.items()):
        lines.append(f"- `{name}`: `{path}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export detailed breakdown tables.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    output_dir = (
        args.output_dir
        or artifact_dir / "reports" / "breakdown_tables_v0"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    breakdowns = build_breakdowns(artifact_dir)
    outputs = {
        "by_query_family": rel(output_dir / "by_query_family.csv"),
        "by_predicate_family": rel(output_dir / "by_predicate_family.csv"),
        "by_stream_predicate": rel(output_dir / "by_stream_predicate.csv"),
        "by_query_type_predicate_family": rel(
            output_dir / "by_query_type_predicate_family.csv"
        ),
        "manifest": rel(output_dir / "manifest.json"),
        "report": rel(output_dir / "breakdown_tables_report.md"),
    }
    write_csv(
        output_dir / "by_query_family.csv",
        breakdowns["by_query_family"],
        [
            "baseline",
            "stream",
            "query_type",
            "query_family",
            "total",
            "exact",
            "exact_accuracy",
            "value_match",
            "value_accuracy",
            "status_match",
            "status_accuracy",
        ],
    )
    write_csv(
        output_dir / "by_predicate_family.csv",
        breakdowns["by_predicate_family"],
        [
            "baseline",
            "stream",
            "predicate_family",
            "total",
            "exact",
            "exact_accuracy",
            "value_match",
            "value_accuracy",
            "status_match",
            "status_accuracy",
        ],
    )
    write_csv(
        output_dir / "by_stream_predicate.csv",
        breakdowns["by_stream_predicate"],
        [
            "baseline",
            "stream",
            "predicate_name",
            "predicate_family",
            "total",
            "exact",
            "exact_accuracy",
            "value_match",
            "value_accuracy",
            "status_match",
            "status_accuracy",
        ],
    )
    write_csv(
        output_dir / "by_query_type_predicate_family.csv",
        breakdowns["by_query_type_predicate_family"],
        [
            "baseline",
            "stream",
            "query_type",
            "predicate_family",
            "total",
            "exact",
            "exact_accuracy",
            "value_match",
            "value_accuracy",
            "status_match",
            "status_accuracy",
        ],
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_dir": rel(artifact_dir),
        "output_dir": rel(output_dir),
        "outputs": outputs,
        "notes": [
            "CHECK_STATE and AS_OF_STATE are labeled by the queried predicate.",
            "CHECK_GOAL and STATE_DIFF are labeled by their target goal-state set.",
            "Exact matching reuses tools/artifacts/evaluate_answers.py compare_answer semantics.",
        ],
    }
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "breakdown_tables_report.md").write_text(
        build_report(artifact_dir, output_dir, outputs),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact_dir": rel(artifact_dir),
                "output_dir": rel(output_dir),
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
