#!/usr/bin/env python3
"""Select the 50-activity strong-version candidate manifest from closed_combo."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/behavior1k_closed_combo/BEHAVIOR-1K")
DEFAULT_OUTPUT_JSONL = (
    REPO_ROOT / "real_data_pipeline" / "manifests" / "real_benchmark_strong_activity_candidates_v0.jsonl"
)
DEFAULT_OUTPUT_CSV = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "task_diversity" / "strong_activity_candidates_v0.csv"
)

TEMPLATE_RE = re.compile(
    r"^(?P<scene>.+)_task_(?P<activity>.+)_(?P<definition>\d+)_(?P<instance>\d+)_template\.json$"
)
TRO_STATE_RE = re.compile(
    r"^(?P<scene>.+)_task_(?P<activity>.+)_(?P<definition>\d+)_(?P<instance>\d+)_template-tro_state\.json$"
)
PREDICATE_RE = re.compile(r"\(([a-zA-Z_][a-zA-Z0-9_]*)\s")

STATE_FAMILY_PREDICATES = {
    "open_toggle": {"open", "toggled_on"},
    "spatial_relation": {"inside", "contains", "ontop", "nextto", "under", "overlaid"},
    "thermal_numeric": {"cooked", "frozen", "hot", "on_fire"},
    "material_particle": {"covered", "filled", "saturated"},
    "contact_assembly": {"attached", "touching", "grasped", "draped"},
    "configuration": {"folded", "unfolded", "broken"},
}
ACTIVITY_FAMILY_KEYWORDS = {
    "cleanliness_visual": {
        "clean",
        "wash",
        "wiping",
        "brushing",
        "spraying",
        "trash",
        "broken_glass",
    },
    "storage_organization": {
        "storage",
        "storing",
        "packing",
        "box",
        "organ",
        "putting",
        "sorting",
        "tidying",
    },
    "cooking_food": {
        "cook",
        "bacon",
        "hot_dogs",
        "microwave",
        "pizza",
        "lunch",
        "vegetables",
        "cabbage",
        "onion",
    },
}
CORE_PREDICATES = set().union(*STATE_FAMILY_PREDICATES.values())


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def git_commit(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def read_asset_version(behavior_root: Path) -> str:
    version_path = behavior_root / "datasets" / "behavior-1k-assets" / "VERSION"
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return "unknown"


def iter_templates(behavior_root: Path) -> list[dict[str, Any]]:
    root = behavior_root / "datasets" / "2025-challenge-task-instances" / "scenes"
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/json/*_template.json")):
        match = TEMPLATE_RE.match(path.name)
        if not match:
            continue
        rows.append(
            {
                "activity_name": match.group("activity"),
                "scene_model": match.group("scene"),
                "activity_definition_id": int(match.group("definition")),
                "activity_instance_id": int(match.group("instance")),
                "template_path": str(path),
            }
        )
    return rows


def collect_tro_state_instances(behavior_root: Path) -> dict[str, list[int]]:
    root = behavior_root / "datasets" / "2025-challenge-task-instances" / "scenes"
    by_activity: dict[str, set[int]] = defaultdict(set)
    for path in sorted(root.glob("*/json/*_instances/*_template-tro_state.json")):
        match = TRO_STATE_RE.match(path.name)
        if not match:
            continue
        by_activity[match.group("activity")].add(int(match.group("instance")))
    return {activity: sorted(values) for activity, values in by_activity.items()}


def bddl_path_for(behavior_root: Path, activity_name: str, definition_id: int) -> Path:
    return behavior_root / "bddl3" / "bddl" / "activity_definitions" / activity_name / f"problem{definition_id}.bddl"


def parse_bddl_predicates(path: Path) -> Counter[str]:
    if not path.exists():
        return Counter()
    text = path.read_text(encoding="utf-8", errors="ignore")
    counts = Counter(PREDICATE_RE.findall(text))
    for ignored in ("define", "problem", "domain", "objects", "init", "goal", "and"):
        counts.pop(ignored, None)
    return counts


def infer_state_families(activity_name: str, predicates: set[str]) -> list[str]:
    families: set[str] = set()
    for family, names in STATE_FAMILY_PREDICATES.items():
        if predicates & names:
            families.add(family)
    lowered = activity_name.lower()
    for family, keywords in ACTIVITY_FAMILY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            families.add(family)
    return sorted(families)


def score_candidate(row: dict[str, Any]) -> int:
    score = 0
    score += 10 * len(row["state_families"])
    score += 3 * len(row["core_predicates"])
    if row["available_tro_state_instance_count"] >= 3:
        score += 20
    if row["activity_name"] in {
        "turning_on_radio",
        "make_microwave_popcorn",
        "clean_a_patio",
        "outfit_a_basic_toolbox",
        "cook_hot_dogs",
        "cook_bacon",
        "freeze_pies",
        "attach_a_camera_to_a_tripod",
    }:
        score += 30
    return score


def select_balanced(rows: list[dict[str, Any]], target_count: int) -> list[dict[str, Any]]:
    eligible_rows = [row for row in rows if row["available_tro_state_instance_count"] >= 3]
    if len(eligible_rows) < target_count:
        raise RuntimeError(
            f"Need {target_count} activities with at least 3 instances, "
            f"but only found {len(eligible_rows)}."
        )

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for family in [
        "open_toggle",
        "spatial_relation",
        "thermal_numeric",
        "material_particle",
        "contact_assembly",
        "configuration",
        "cleanliness_visual",
        "storage_organization",
        "cooking_food",
    ]:
        family_rows = [
            row for row in eligible_rows if family in row["state_families"] and row["activity_name"] not in seen
        ]
        if family_rows:
            best = max(family_rows, key=lambda row: (row["selection_score"], row["activity_name"]))
            selected.append(best)
            seen.add(best["activity_name"])

    for row in sorted(eligible_rows, key=lambda item: (-item["selection_score"], item["activity_name"])):
        if len(selected) >= target_count:
            break
        if row["activity_name"] in seen:
            continue
        selected.append(row)
        seen.add(row["activity_name"])
    return selected


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "candidate_id",
        "selected_for_strong_target",
        "selection_rank",
        "selection_score",
        "activity_name",
        "scene_model",
        "activity_definition_id",
        "base_activity_instance_id",
        "available_tro_state_instance_count",
        "candidate_instance_ids",
        "state_families",
        "core_predicates",
        "asset_runtime_status",
        "template_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: "|".join(map(str, row[key])) if isinstance(row.get(key), list) else row.get(key, "")
                    for key in fieldnames
                }
            )


def build_candidates(behavior_root: Path, target_count: int) -> list[dict[str, Any]]:
    templates = iter_templates(behavior_root)
    tro_instances = collect_tro_state_instances(behavior_root)
    asset_version = read_asset_version(behavior_root)
    code_commit = git_commit(behavior_root)
    rows: list[dict[str, Any]] = []
    for index, template in enumerate(templates):
        activity_name = template["activity_name"]
        definition_id = template["activity_definition_id"]
        predicates = parse_bddl_predicates(bddl_path_for(behavior_root, activity_name, definition_id))
        core_predicates = sorted(set(predicates) & CORE_PREDICATES)
        state_families = infer_state_families(activity_name, set(predicates))
        available_instances = tro_instances.get(activity_name, [])
        candidate_instance_ids = available_instances[:3]
        row = {
            "candidate_id": f"strong_c{index:03d}_{activity_name}",
            "source_env": "behavior1k_closed_combo",
            "behavior_root": str(behavior_root),
            "behavior_code_commit": code_commit,
            "asset_version_observed": asset_version,
            "asset_runtime_status": "not_validated_yet",
            "selected_for_strong_target": False,
            "selection_rank": None,
            "activity_name": activity_name,
            "scene_model": template["scene_model"],
            "activity_definition_id": definition_id,
            "base_activity_instance_id": template["activity_instance_id"],
            "available_tro_state_instance_count": len(available_instances),
            "candidate_instance_ids": candidate_instance_ids,
            "template_path": template["template_path"],
            "bddl_path": str(bddl_path_for(behavior_root, activity_name, definition_id)),
            "bddl_predicates": sorted(predicates),
            "core_predicates": core_predicates,
            "state_families": state_families,
            "selection_notes": "candidate selected from closed_combo templates; simulator runtime not validated in this step",
            "selected_at": datetime.now(timezone.utc).isoformat(),
        }
        row["selection_score"] = score_candidate(row)
        rows.append(row)

    selected = select_balanced(rows, target_count)
    selected_names = {row["activity_name"] for row in selected}
    rank_by_name = {row["activity_name"]: rank for rank, row in enumerate(selected, start=1)}
    for row in rows:
        row["selected_for_strong_target"] = row["activity_name"] in selected_names
        row["selection_rank"] = rank_by_name.get(row["activity_name"])
    return sorted(rows, key=lambda row: (not row["selected_for_strong_target"], row["selection_rank"] or 9999, row["activity_name"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select the strong-version 50-activity candidate set.")
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--target-count", type=int, default=50)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_candidates(args.behavior_root, args.target_count)
    write_jsonl(args.output_jsonl, rows)
    write_csv(args.output_csv, rows)
    selected = [row for row in rows if row["selected_for_strong_target"]]
    family_counts = Counter(family for row in selected for family in row["state_families"])
    predicate_counts = Counter(predicate for row in selected for predicate in row["core_predicates"])
    print(
        json.dumps(
            {
                "status": "PASS",
                "behavior_root": str(args.behavior_root),
                "templates": len(rows),
                "selected": len(selected),
                "output_jsonl": rel(args.output_jsonl),
                "output_csv": rel(args.output_csv),
                "state_family_counts": dict(sorted(family_counts.items())),
                "core_predicate_counts": dict(sorted(predicate_counts.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
