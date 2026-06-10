#!/usr/bin/env python3
"""Export paper-ready tables from a real benchmark artifact.

The output directory is intentionally simple: CSV files for plotting scripts
and a short Markdown report for human inspection.  This script does not draw
figures; it freezes the numeric data that final paper figures should consume.

Formal baseline result ingestion is intentionally left to a separate bridge
script once the baseline repository emits predicted QueryAnswers.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "public_v5_scale48_seed6_full"
)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def scalar_rows(values: dict[str, Any], *, group: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in sorted(values.items()):
        if isinstance(value, (dict, list)):
            continue
        rows.append({"group": group, "key": key, "value": value})
    return rows


def distribution_rows(values: dict[str, Any], *, distribution: str) -> list[dict[str, Any]]:
    return [
        {"distribution": distribution, "name": str(name), "count": count}
        for name, count in sorted(values.items())
    ]


def build_report(
    *,
    artifact_dir: Path,
    output_dir: Path,
    profile: dict[str, Any],
    quality: dict[str, Any] | None,
    baseline_results: list[dict[str, Any]],
    outputs: dict[str, str],
) -> str:
    counts = profile.get("counts", {})
    readiness = profile.get("scale_readiness", {})
    issues = [] if quality is None else quality.get("issues", [])
    core_rows = [
        row
        for row in baseline_results
        if row["stream"] in {"clean", "missing", "conflict", "mixed", "delay", "out_of_order"}
    ]
    lines = [
        "# Paper Table Export v0",
        "",
        "本报告由 `real_data_pipeline/stages/export_paper_tables.py` 生成。",
        "",
        "## Artifact",
        "",
        f"- artifact: `{rel(artifact_dir)}`",
        f"- output: `{rel(output_dir)}`",
        f"- episodes: `{counts.get('episodes')}`",
        f"- tasks: `{counts.get('tasks')}`",
        f"- queries: `{counts.get('queries')}`",
        f"- public streams: `{counts.get('public_streams')}`",
        f"- clean observations: `{counts.get('clean_observations')}`",
        f"- readiness: `{readiness.get('status', 'UNKNOWN')}`",
        "",
        "## Baseline Result Preview",
        "",
        "| baseline | stream | exact accuracy | state diff F1 | goal predicate F1 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in sorted(core_rows, key=lambda r: (r["baseline"], r["stream"])):
        lines.append(
            f"| `{row['baseline']}` | `{row['stream']}` | "
            f"{float(row['exact_accuracy']):.4f} | "
            f"{float(row['state_diff_mean_f1'] or 0.0):.4f} | "
            f"{float(row['goal_predicate_mean_f1'] or 0.0):.4f} |"
        )
    lines.extend(
        [
            "",
            "## Quality Notes",
            "",
        ]
    )
    if issues:
        for issue in issues:
            lines.append(
                f"- `{issue.get('severity')}` `{issue.get('kind')}`: {issue.get('message')}"
            )
    else:
        lines.append("- no quality issues recorded")
    lines.extend(["", "## Output Files", ""])
    for name, path in sorted(outputs.items()):
        lines.append(f"- `{name}`: `{path}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export paper-ready benchmark tables.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    output_dir = (
        args.output_dir
        or artifact_dir / "reports" / "paper_tables_v0"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_path = artifact_dir / "reports" / "benchmark_profile_summary_v1.json"
    quality_path = artifact_dir / "reports" / "quality_audit_v0.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"profile summary not found: {profile_path}")
    profile = read_json(profile_path)
    quality = read_json(quality_path) if quality_path.exists() else None

    outputs: dict[str, str] = {}
    outputs["artifact_counts"] = rel(output_dir / "artifact_counts.csv")
    write_csv(
        output_dir / "artifact_counts.csv",
        scalar_rows(profile.get("counts", {}), group="counts")
        + scalar_rows(profile.get("size_bytes", {}), group="size_bytes"),
        ["group", "key", "value"],
    )

    distributions: list[dict[str, Any]] = []
    for name in (
        "horizon_counts",
        "predicate_family_counts",
        "target_predicate_counts",
        "transition_kind_counts",
        "target_expect_counts",
        "query_type_counts",
        "query_scope_counts",
        "query_family_counts",
        "query_time_probe_counts",
        "query_predicate_counts",
    ):
        distributions.extend(distribution_rows(profile.get(name, {}), distribution=name))
    outputs["artifact_distributions"] = rel(output_dir / "artifact_distributions.csv")
    write_csv(
        output_dir / "artifact_distributions.csv",
        distributions,
        ["distribution", "name", "count"],
    )

    stream_rows = [
        {
            "stream": stream,
            "observations": info.get("observations"),
            "bytes": info.get("bytes"),
            "compression": info.get("compression"),
            "path": info.get("path"),
        }
        for stream, info in sorted(profile.get("streams", {}).items())
    ]
    outputs["stream_summary"] = rel(output_dir / "stream_summary.csv")
    write_csv(
        output_dir / "stream_summary.csv",
        stream_rows,
        ["stream", "observations", "bytes", "compression", "path"],
    )

    answer_rows: list[dict[str, Any]] = []
    for stream, counts in sorted(profile.get("answer_status_counts", {}).items()):
        for status, count in sorted(counts.items()):
            answer_rows.append({"stream": stream, "status": status, "count": count})
    outputs["answer_status"] = rel(output_dir / "answer_status.csv")
    write_csv(output_dir / "answer_status.csv", answer_rows, ["stream", "status", "count"])

    baseline_dirs: list[Path] = []
    baseline_result_rows: list[dict[str, Any]] = []
    query_metric_rows: list[dict[str, Any]] = []
    outputs["baseline_results"] = rel(output_dir / "baseline_results.csv")
    write_csv(
        output_dir / "baseline_results.csv",
        baseline_result_rows,
        [
            "baseline",
            "strategy",
            "stream",
            "coverage",
            "exact_accuracy",
            "matched_exact_accuracy",
            "confidence_mae",
            "state_diff_mean_f1",
            "goal_predicate_mean_f1",
            "total_ground_truth",
            "matched",
            "missing",
            "extra",
        ],
    )
    outputs["query_type_metrics"] = rel(output_dir / "query_type_metrics.csv")
    write_csv(
        output_dir / "query_type_metrics.csv",
        query_metric_rows,
        [
            "baseline",
            "strategy",
            "stream",
            "query_type",
            "total",
            "coverage",
            "exact_accuracy",
            "value_accuracy",
            "status_accuracy",
            "satisfied_accuracy",
        ],
    )

    issue_rows = []
    for issue in ([] if quality is None else quality.get("issues", [])):
        issue_rows.append(
            {
                "severity": issue.get("severity"),
                "kind": issue.get("kind"),
                "message": issue.get("message"),
                "details": json.dumps(issue.get("details", {}), ensure_ascii=False, sort_keys=True),
            }
        )
    outputs["quality_issues"] = rel(output_dir / "quality_issues.csv")
    write_csv(
        output_dir / "quality_issues.csv",
        issue_rows,
        ["severity", "kind", "message", "details"],
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_dir": rel(artifact_dir),
        "profile_summary": rel(profile_path),
        "quality_audit": rel(quality_path) if quality_path.exists() else None,
        "baseline_dirs": [rel(path) for path in baseline_dirs],
        "outputs": outputs,
        "recommended_paper_figures": {
            "artifact_characterization": [
                outputs["artifact_counts"],
                outputs["artifact_distributions"],
                outputs["stream_summary"],
            ],
            "robustness_and_baseline_comparison": [
                outputs["baseline_results"],
                outputs["query_type_metrics"],
                outputs["answer_status"],
            ],
        },
    }
    outputs["manifest"] = rel(output_dir / "manifest.json")
    write_json(output_dir / "manifest.json", manifest)

    report = build_report(
        artifact_dir=artifact_dir,
        output_dir=output_dir,
        profile=profile,
        quality=quality,
        baseline_results=baseline_result_rows,
        outputs=outputs,
    )
    outputs["report"] = rel(output_dir / "paper_tables_report.md")
    (output_dir / "paper_tables_report.md").write_text(report, encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact_dir": rel(artifact_dir),
                "output_dir": rel(output_dir),
                "baseline_dirs": [rel(path) for path in baseline_dirs],
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
