#!/usr/bin/env python3
"""Select v4 real benchmark task-diversity candidates from local templates."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K")
DEFAULT_OUTPUT_JSONL = (
    REPO_ROOT / "real_data_pipeline" / "manifests" / "real_benchmark_v4_diversity_candidates_v0.jsonl"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "real_data_pipeline"
    / "artifacts"
    / "v4_task_diversity_selection"
    / "v4_task_diversity_selection_report.md"
)


TEMPLATE_RE = re.compile(r"^(?P<scene>.+)_task_(?P<activity>.+)_(?P<definition>\d+)_(?P<instance>\d+)_template\.json$")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def iter_templates(behavior_root: Path) -> list[dict[str, Any]]:
    root = behavior_root / "datasets" / "2025-challenge-task-instances" / "scenes"
    templates: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/json/*_template.json")):
        match = TEMPLATE_RE.match(path.name)
        if not match:
            continue
        templates.append(
            {
                "path": str(path),
                "scene_model": match.group("scene"),
                "activity_name": match.group("activity"),
                "activity_definition_id": int(match.group("definition")),
                "activity_instance_id": int(match.group("instance")),
            }
        )
    return templates


def template_index(templates: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["scene_model"], row["activity_name"]): row for row in templates}


def candidate_specs(index: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        {
            "candidate_id": "v4_c0_boxing_books_inside",
            "status": "blocked_symbolic_place_inside_drop",
            "activity_name": "boxing_books_up_for_storage",
            "scene_model": "house_double_floor_upper",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": "real_data_pipeline/action_scripts/boxing_books_place_book_inside.jsonl",
            "record_relations": True,
            "max_relation_pairs": 0,
            "expected_targets": [
                {
                    "predicate_name": "inside",
                    "arguments": ["book.n.02_1", "box.n.01_1"],
                    "expect": "false_to_true",
                }
            ],
            "diversity_role": "new containment task with larger object scope than toolbox",
            "notes": "smoke validation 失败：PLACE_INSIDE sampled pose 后 book dropped，后续 attempts 因未 grasp 失败；需要更稳的 relation/state action source。",
        },
        {
            "candidate_id": "v4_c1_cook_bacon_heat",
            "status": "blocked_og_heating_sampling",
            "activity_name": "cook_bacon",
            "scene_model": "house_single_floor",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": "real_data_pipeline/action_scripts/cook_bacon_heat_one_bacon.jsonl",
            "record_relations": False,
            "max_relation_pairs": 0,
            "requires_enable_transition_rules": True,
            "expected_targets": [
                {
                    "predicate_name": "toggled_on",
                    "arguments": ["stove.n.01_1"],
                    "expect": "false_to_true",
                },
                {
                    "predicate_name": "temperature",
                    "arguments": ["bacon.n.01_1"],
                    "expect": "increase",
                },
                {
                    "predicate_name": "max_temperature",
                    "arguments": ["bacon.n.01_1"],
                    "expect": "increase",
                },
                {
                    "predicate_name": "cooked",
                    "arguments": ["bacon.n.01_1"],
                    "expect": "eventual_true",
                },
            ],
            "diversity_role": "stove heating / max_temperature coverage",
            "notes": "smoke validation 仍失败：PLACE_NEAR_HEATING_ELEMENT 进入下游 pose sampler 后继续 tensor conversion error；暂不进入 v4。",
        },
        {
            "candidate_id": "v4_c2_loading_dishwasher_inside",
            "status": "blocked_template_pose",
            "activity_name": "loading_the_dishwasher",
            "scene_model": "house_single_floor",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": "real_data_pipeline/action_scripts/loading_the_dishwasher_open_place_mug.jsonl",
            "record_relations": True,
            "max_relation_pairs": 0,
            "expected_targets": [
                {
                    "predicate_name": "inside",
                    "arguments": ["mug.n.04_1", "dishwasher.n.01_1"],
                    "expect": "false_to_true",
                }
            ],
            "diversity_role": "appliance containment",
            "notes": "历史 smoke report 显示 R1 robot_poses 缺失，reset 阶段失败；需补 template / robot pose 后再跑。",
        },
        {
            "candidate_id": "v4_c3_popcorn_bag_inside_microwave",
            "status": "blocked_sampling",
            "activity_name": "make_microwave_popcorn",
            "scene_model": "house_double_floor_lower",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": "real_data_pipeline/action_scripts/make_microwave_popcorn_place_bag_inside.jsonl",
            "record_relations": True,
            "max_relation_pairs": 0,
            "expected_targets": [
                {
                    "predicate_name": "inside",
                    "arguments": ["popcorn__bag.n.01_1", "microwave.n.02_1"],
                    "expect": "false_to_true",
                }
            ],
            "diversity_role": "same task as p0 but containment target",
            "notes": "历史 smoke report 显示 PLACE_INSIDE 找不到合法 inside pose，暂不作为 v4 ready candidate。",
        },
        {
            "candidate_id": "v4_c4_thawing_frozen_food",
            "status": "needs_primitive_design",
            "activity_name": "thawing_frozen_food",
            "scene_model": "house_single_floor",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": None,
            "record_relations": True,
            "max_relation_pairs": 0,
            "requires_enable_transition_rules": True,
            "expected_targets": [
                {
                    "predicate_name": "frozen",
                    "arguments": ["food.n.01_1"],
                    "expect": "eventual_false",
                },
                {
                    "predicate_name": "temperature",
                    "arguments": ["food.n.01_1"],
                    "expect": "increase",
                },
            ],
            "diversity_role": "reverse frozen / thaw transition",
            "notes": "很适合作为 v4 状态族扩展，但需要先确认 object names 和可控 heat/cool action source。",
        },
        {
            "candidate_id": "v4_c5_cool_cakes",
            "status": "needs_primitive_design",
            "activity_name": "cool_cakes",
            "scene_model": "house_double_floor_lower",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": None,
            "record_relations": False,
            "max_relation_pairs": 0,
            "requires_enable_transition_rules": True,
            "expected_targets": [
                {
                    "predicate_name": "temperature",
                    "arguments": ["cake.n.03_1"],
                    "expect": "decrease",
                }
            ],
            "diversity_role": "cooling numeric transition",
            "notes": "候选有模板，但需要先确认初始 hot/cooked state 和可控 wait/cool primitive。",
        },
        {
            "candidate_id": "v4_c6_sorting_household_items",
            "status": "deferred_large_scope",
            "activity_name": "sorting_household_items",
            "scene_model": "house_single_floor",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": None,
            "record_relations": True,
            "max_relation_pairs": 0,
            "expected_targets": [],
            "diversity_role": "multi-object relation / longer task",
            "notes": "适合后续 v5；当前先避免把 v4 变成大范围 relation explosion。",
        },
        {
            "candidate_id": "v4_c7_assembling_gift_baskets",
            "status": "blocked_import_timeout",
            "activity_name": "assembling_gift_baskets",
            "scene_model": "house_double_floor_lower",
            "robot_type": "R1",
            "action_source": "primitive_jsonl",
            "primitive_jsonl": None,
            "record_relations": True,
            "max_relation_pairs": 0,
            "expected_targets": [],
            "diversity_role": "large long-horizon relation task",
            "notes": "历史上 scene import 后超时，暂不进入 v4 controlled scale-up。",
        },
    ]
    for spec in specs:
        template = index.get((spec["scene_model"], spec["activity_name"]))
        spec["template_available"] = template is not None
        if template:
            spec["activity_definition_id"] = template["activity_definition_id"]
            spec["activity_instance_id"] = template["activity_instance_id"]
            spec["template_path"] = template["path"]
        else:
            spec["activity_definition_id"] = 0
            spec["activity_instance_id"] = 0
            spec["template_path"] = None
            if spec["status"] == "ready_for_validation":
                spec["status"] = "blocked_missing_template"
    return specs


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def table_from_counter(counter: dict[str, int]) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{key}` | {value} |")
    return "\n".join(lines)


def build_report(
    *,
    behavior_root: Path,
    templates: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    output_jsonl: Path,
) -> str:
    scene_counts = Counter(row["scene_model"] for row in templates)
    status_counts = Counter(row["status"] for row in candidates)
    lines = [
        "# V4 Task Diversity Selection Report",
        "",
        "本报告由 `real_data_pipeline/stages/select_task_diversity.py` 生成。",
        "",
        "## Local Template Inventory",
        "",
        f"- behavior_root: `{behavior_root}`",
        f"- local challenge templates: {len(templates)}",
        f"- output manifest: `{rel(output_jsonl)}`",
        "",
        "### Templates By Scene",
        "",
        table_from_counter(dict(scene_counts)),
        "",
        "## Candidate Status",
        "",
        table_from_counter(dict(status_counts)),
        "",
        "## V4 Candidates",
        "",
        "| candidate | status | task | scene | role | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in candidates:
        note = str(row.get("notes", "")).replace("|", "/")
        role = str(row.get("diversity_role", "")).replace("|", "/")
        lines.append(
            f"| `{row['candidate_id']}` | `{row['status']}` | `{row['activity_name']}` | "
            f"`{row['scene_model']}` | {role} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "v4 不建议继续扩 seed。优先做小规模 task-diversity validation：",
            "",
            "```text",
            "ready_for_validation candidates:",
            "  none after smoke validation",
            "```",
            "",
            "当前不应直接产出 v4 public artifact。下一步应先补稳定 action source，",
            "或者重新搜索能用现有 symbolic primitives 通过的 task。v3 仍是当前 validated public artifact。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select v4 real benchmark task candidates.")
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    templates = iter_templates(args.behavior_root)
    candidates = candidate_specs(template_index(templates))
    payload = []
    for row in candidates:
        out = dict(row)
        out["selected_at"] = datetime.now(timezone.utc).isoformat()
        payload.append(out)
    write_jsonl(args.output_jsonl, payload)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            behavior_root=args.behavior_root,
            templates=templates,
            candidates=payload,
            output_jsonl=args.output_jsonl,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "templates": len(templates),
                "output_jsonl": rel(args.output_jsonl),
                "report": rel(args.report),
                "candidate_status_counts": dict(Counter(row["status"] for row in payload)),
                "ready_for_validation": [
                    row["candidate_id"] for row in payload if row["status"] == "ready_for_validation"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
