#!/usr/bin/env python3
"""Evaluate predicted EviStateBench answers against ground-truth answers.

This script implements Step 7 of the minimal pipeline:

predicted answers + ground-truth answers -> evaluation metrics

It supports both single-file evaluation and directory evaluation.  Directory
mode matches files by name, which is useful for clean / delay / missing /
conflict / mixed stream variants.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_PREDICTIONS_DIR = REPO_ROOT / "data" / "answer_sets_v0"
DEFAULT_GROUND_TRUTH_DIR = REPO_ROOT / "data" / "answer_sets_v0"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "evaluation_v0" / "self_check_metrics.json"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "evaluator_self_check_v0.md"


def read_jsonl_by_query_id(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read answer rows keyed by query_id and return duplicate ids."""
    rows: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            query_id = row.get("query_id")
            if not query_id:
                raise ValueError(f"Missing query_id in {path}:{line_number}")
            if query_id in rows:
                duplicate_ids.append(query_id)
            rows[query_id] = row
    return rows, duplicate_ids


def json_value(value: Any) -> str:
    """Stable JSON string used for set comparison."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def state_key(state: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    return (state["predicate_name"], tuple(state["arguments"]))


def state_key_text(state: dict[str, Any]) -> str:
    predicate_name, arguments = state_key(state)
    return f"{predicate_name}({','.join(arguments)})"


def safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def f1_from_sets(predicted: set[Any], truth: set[Any]) -> dict[str, float | None]:
    if not predicted and not truth:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    true_positive = len(predicted & truth)
    precision = safe_div(true_positive, len(predicted))
    recall = safe_div(true_positive, len(truth))
    if precision is None or recall is None or precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def confidence_error(predicted: dict[str, Any], truth: dict[str, Any]) -> float | None:
    if "confidence" not in predicted or "confidence" not in truth:
        return None
    try:
        return abs(float(predicted["confidence"]) - float(truth["confidence"]))
    except (TypeError, ValueError):
        return None


def state_answer_metrics(predicted: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    value_match = predicted.get("value") == truth.get("value")
    status_match = predicted.get("status") == truth.get("status")
    state_match = predicted.get("state") == truth.get("state")
    return {
        "value_match": value_match,
        "status_match": status_match,
        "state_match": state_match,
        "exact_match": value_match and status_match and state_match,
        "confidence_abs_error": confidence_error(predicted, truth),
    }


def goal_predicate_items(row: dict[str, Any]) -> set[tuple[str, str, str, str]]:
    items: set[tuple[str, str, str, str]] = set()
    for bucket in ("satisfied_predicates", "violated_predicates", "uncertain_predicates"):
        for result in row.get(bucket, []) or []:
            items.add(
                (
                    bucket,
                    state_key_text(result["state"]),
                    json_value(result.get("required_value")),
                    json_value(result.get("value")),
                )
            )
    return items


def goal_answer_metrics(predicted: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    satisfied_match = predicted.get("satisfied") == truth.get("satisfied")
    status_match = predicted.get("status") == truth.get("status")
    pred_items = goal_predicate_items(predicted)
    truth_items = goal_predicate_items(truth)
    predicate_prf = f1_from_sets(pred_items, truth_items)
    predicate_exact = pred_items == truth_items
    return {
        "satisfied_match": satisfied_match,
        "status_match": status_match,
        "predicate_exact_match": predicate_exact,
        "predicate_precision": predicate_prf["precision"],
        "predicate_recall": predicate_prf["recall"],
        "predicate_f1": predicate_prf["f1"],
        "exact_match": satisfied_match and status_match and predicate_exact,
        "confidence_abs_error": confidence_error(predicted, truth),
    }


def diff_items(row: dict[str, Any]) -> set[tuple[str, str, str, str]]:
    items: set[tuple[str, str, str, str]] = set()
    for bucket in ("changed_states", "added_states", "removed_states"):
        for change in row.get(bucket, []) or []:
            items.add(
                (
                    bucket,
                    state_key_text(change["state"]),
                    json_value(change.get("value_at_t1")),
                    json_value(change.get("value_at_t2")),
                )
            )
    return items


def diff_answer_metrics(predicted: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    pred_items = diff_items(predicted)
    truth_items = diff_items(truth)
    prf = f1_from_sets(pred_items, truth_items)
    return {
        "diff_exact_match": pred_items == truth_items,
        "diff_precision": prf["precision"],
        "diff_recall": prf["recall"],
        "diff_f1": prf["f1"],
        "exact_match": pred_items == truth_items,
    }


def compare_answer(predicted: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    answer_type = truth.get("answer_type")
    if predicted.get("answer_type") != answer_type:
        return {
            "exact_match": False,
            "answer_type_match": False,
            "expected_answer_type": answer_type,
            "predicted_answer_type": predicted.get("answer_type"),
        }

    if answer_type == "STATE_ANSWER":
        metrics = state_answer_metrics(predicted, truth)
    elif answer_type == "GOAL_ANSWER":
        metrics = goal_answer_metrics(predicted, truth)
    elif answer_type == "STATE_DIFF_ANSWER":
        metrics = diff_answer_metrics(predicted, truth)
    else:
        raise ValueError(f"Unsupported answer_type: {answer_type}")

    metrics["answer_type_match"] = True
    return metrics


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize_boolean(counter: Counter[str], true_key: str, denominator: int) -> float | None:
    return safe_div(counter[true_key], denominator)


def evaluate_pair(
    *,
    name: str,
    predictions_path: Path,
    ground_truth_path: Path,
) -> dict[str, Any]:
    predictions, prediction_duplicates = read_jsonl_by_query_id(predictions_path)
    truth, truth_duplicates = read_jsonl_by_query_id(ground_truth_path)

    missing_ids = sorted(set(truth) - set(predictions))
    extra_ids = sorted(set(predictions) - set(truth))
    matched_ids = sorted(set(truth) & set(predictions))

    by_query_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_answer_type: dict[str, Counter[str]] = defaultdict(Counter)
    confidence_errors: list[float] = []
    diff_f1_values: list[float] = []
    goal_predicate_f1_values: list[float] = []

    for query_id in matched_ids:
        pred = predictions[query_id]
        gt = truth[query_id]
        query_type = gt.get("query_type", "unknown")
        answer_type = gt.get("answer_type", "unknown")
        metrics = compare_answer(pred, gt)

        by_query_type[query_type]["matched"] += 1
        by_query_type[query_type]["exact"] += int(bool(metrics.get("exact_match")))
        by_answer_type[answer_type]["matched"] += 1
        by_answer_type[answer_type]["exact"] += int(bool(metrics.get("exact_match")))

        if "value_match" in metrics:
            by_query_type[query_type]["value_match"] += int(metrics["value_match"])
            by_query_type[query_type]["status_match"] += int(metrics["status_match"])
        if "satisfied_match" in metrics:
            by_query_type[query_type]["satisfied_match"] += int(metrics["satisfied_match"])
            by_query_type[query_type]["status_match"] += int(metrics["status_match"])
        if "diff_f1" in metrics and metrics["diff_f1"] is not None:
            diff_f1_values.append(float(metrics["diff_f1"]))
        if "predicate_f1" in metrics and metrics["predicate_f1"] is not None:
            goal_predicate_f1_values.append(float(metrics["predicate_f1"]))
        if metrics.get("confidence_abs_error") is not None:
            confidence_errors.append(float(metrics["confidence_abs_error"]))

    truth_query_counts = Counter(row.get("query_type", "unknown") for row in truth.values())
    truth_answer_counts = Counter(row.get("answer_type", "unknown") for row in truth.values())
    prediction_query_counts = Counter(
        row.get("query_type", "unknown") for row in predictions.values()
    )

    query_metrics: dict[str, dict[str, Any]] = {}
    for query_type, total in sorted(truth_query_counts.items()):
        counters = by_query_type[query_type]
        value_accuracy = (
            safe_div(counters["value_match"], total)
            if query_type in {"CHECK_STATE", "AS_OF_STATE"}
            else None
        )
        status_accuracy = (
            safe_div(counters["status_match"], total)
            if query_type in {"CHECK_STATE", "AS_OF_STATE", "CHECK_GOAL"}
            else None
        )
        satisfied_accuracy = (
            safe_div(counters["satisfied_match"], total)
            if query_type == "CHECK_GOAL"
            else None
        )
        query_metrics[query_type] = {
            "total": total,
            "matched": counters["matched"],
            "coverage": safe_div(counters["matched"], total),
            "exact_accuracy": safe_div(counters["exact"], total),
            "matched_exact_accuracy": safe_div(counters["exact"], counters["matched"]),
            "value_accuracy": value_accuracy,
            "status_accuracy": status_accuracy,
            "satisfied_accuracy": satisfied_accuracy,
        }

    total_truth = len(truth)
    exact_total = sum(counter["exact"] for counter in by_query_type.values())
    matched_total = len(matched_ids)
    return {
        "name": name,
        "predictions_path": str(predictions_path),
        "ground_truth_path": str(ground_truth_path),
        "total_ground_truth": total_truth,
        "total_predictions": len(predictions),
        "matched": matched_total,
        "missing": len(missing_ids),
        "extra": len(extra_ids),
        "coverage": safe_div(matched_total, total_truth),
        "exact_accuracy": safe_div(exact_total, total_truth),
        "matched_exact_accuracy": safe_div(exact_total, matched_total),
        "confidence_mae": average(confidence_errors),
        "state_diff_mean_f1": average(diff_f1_values),
        "goal_predicate_mean_f1": average(goal_predicate_f1_values),
        "truth_query_type_counts": dict(truth_query_counts),
        "prediction_query_type_counts": dict(prediction_query_counts),
        "truth_answer_type_counts": dict(truth_answer_counts),
        "query_metrics": query_metrics,
        "answer_type_exact": {
            answer_type: {
                "total": truth_answer_counts[answer_type],
                "matched": counters["matched"],
                "exact_accuracy": safe_div(counters["exact"], truth_answer_counts[answer_type]),
            }
            for answer_type, counters in sorted(by_answer_type.items())
        },
        "duplicate_query_ids": {
            "predictions": prediction_duplicates,
            "ground_truth": truth_duplicates,
        },
        "missing_query_ids_sample": missing_ids[:20],
        "extra_query_ids_sample": extra_ids[:20],
    }


def discover_pairs(
    *,
    predictions: Path | None,
    ground_truth: Path | None,
    predictions_dir: Path,
    ground_truth_dir: Path,
) -> list[tuple[str, Path, Path]]:
    if predictions or ground_truth:
        if not predictions or not ground_truth:
            raise ValueError("--predictions and --ground-truth must be provided together")
        return [(predictions.stem, predictions, ground_truth)]

    pairs: list[tuple[str, Path, Path]] = []
    for prediction_path in sorted(predictions_dir.glob("*.jsonl")):
        ground_truth_path = ground_truth_dir / prediction_path.name
        if not ground_truth_path.exists():
            raise FileNotFoundError(
                f"Missing matching ground-truth file for {prediction_path.name}: "
                f"{ground_truth_path}"
            )
        pairs.append((prediction_path.stem, prediction_path, ground_truth_path))
    if not pairs:
        raise FileNotFoundError(f"No prediction JSONL files found in {predictions_dir}")
    return pairs


def write_metrics(path: Path, metrics: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def build_report(metrics: dict[str, Any]) -> str:
    results = metrics["results"]
    lines = [
        "# Evaluation Report v0",
        "",
        "本报告由 `tools/artifacts/evaluate_answers.py` 生成。",
        "",
        "它对应最小验证计划的第 7 步：",
        "",
        "```text",
        "predicted answers + ground-truth answers -> evaluation metrics",
        "```",
        "",
        "## Summary",
        "",
        "| name | ground truth | predictions | coverage | exact accuracy | confidence MAE | diff F1 | goal predicate F1 | missing | extra |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            f"| `{result['name']}` | {result['total_ground_truth']} | "
            f"{result['total_predictions']} | {format_float(result['coverage'])} | "
            f"{format_float(result['exact_accuracy'])} | "
            f"{format_float(result['confidence_mae'])} | "
            f"{format_float(result['state_diff_mean_f1'])} | "
            f"{format_float(result['goal_predicate_mean_f1'])} | "
            f"{result['missing']} | {result['extra']} |"
        )

    lines.extend(
        [
            "",
            "## Query-Type Metrics",
            "",
        ]
    )
    for result in results:
        lines.extend(
            [
                f"### {result['name']}",
                "",
                "| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for query_type, values in sorted(result["query_metrics"].items()):
            lines.append(
                f"| `{query_type}` | {values['total']} | "
                f"{format_float(values['coverage'])} | "
                f"{format_float(values['exact_accuracy'])} | "
                f"{format_float(values.get('value_accuracy'))} | "
                f"{format_float(values.get('status_accuracy'))} | "
                f"{format_float(values.get('satisfied_accuracy'))} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "- `exact_accuracy` 以 ground-truth answer 总数为分母，missing prediction 算错。",
            "- `coverage` 表示 predicted answers 覆盖了多少 ground-truth query_id。",
            "- `STATE_DIFF` 使用 change-set exact match 和 mean F1。",
            "- `CHECK_GOAL` 除整体 satisfied/status 外，也计算 goal predicate set F1。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate predicted answer sets against EviStateBench ground truth."
    )
    parser.add_argument("--predictions", type=Path, default=None)
    parser.add_argument("--ground-truth", type=Path, default=None)
    parser.add_argument("--predictions-dir", type=Path, default=DEFAULT_PREDICTIONS_DIR)
    parser.add_argument("--ground-truth-dir", type=Path, default=DEFAULT_GROUND_TRUTH_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pairs = discover_pairs(
        predictions=args.predictions,
        ground_truth=args.ground_truth,
        predictions_dir=args.predictions_dir,
        ground_truth_dir=args.ground_truth_dir,
    )
    results = [
        evaluate_pair(
            name=name,
            predictions_path=prediction_path,
            ground_truth_path=ground_truth_path,
        )
        for name, prediction_path, ground_truth_path in pairs
    ]
    metrics = {
        "predictions": str(args.predictions) if args.predictions else None,
        "ground_truth": str(args.ground_truth) if args.ground_truth else None,
        "predictions_dir": str(args.predictions_dir),
        "ground_truth_dir": str(args.ground_truth_dir),
        "results": results,
    }
    write_metrics(args.output, metrics)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(build_report(metrics), encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(args.output),
                "report": str(args.report),
                "evaluated": len(results),
                "results": {
                    result["name"]: {
                        "coverage": result["coverage"],
                        "exact_accuracy": result["exact_accuracy"],
                        "missing": result["missing"],
                        "extra": result["extra"],
                    }
                    for result in results
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
