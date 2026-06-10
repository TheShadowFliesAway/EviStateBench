#!/usr/bin/env python3
"""Probe BEHAVIOR HuggingFace datasets before downloading large files.

The script only queries repository metadata and local metadata files.  It does
not download raw HDF5, parquet, or video payloads.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "download_probe"

RAWDATA_REPO = "behavior-1k/2025-challenge-rawdata"
DEMOS_REPO = "behavior-1k/2025-challenge-demos"
TASK_INSTANCES_REPO = "behavior-1k/2025-challenge-task-instances"
DEFAULT_TASK_IDS = [0, 19, 23, 35, 36, 40, 45, 46, 47]
HF_TREE_URL = "https://huggingface.co/api/datasets/{repo}/tree/main/{path}?recursive={recursive}&expand=1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def fetch_hf_tree(
    repo: str,
    path: str = "",
    *,
    recursive: bool = False,
    attempts: int = 4,
) -> list[dict[str, Any]]:
    quoted_repo = urllib.parse.quote(repo, safe="/")
    quoted_path = urllib.parse.quote(path.strip("/"), safe="/")
    url = HF_TREE_URL.format(
        repo=quoted_repo,
        path=quoted_path,
        recursive="1" if recursive else "0",
    )
    if not path:
        url = f"https://huggingface.co/api/datasets/{quoted_repo}/tree/main?recursive={'1' if recursive else '0'}&expand=1"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "EviStateBench-probe/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 * attempt, 8))
    assert last_error is not None
    raise last_error


def parse_task_ids(value: str) -> list[int]:
    task_ids: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        task_ids.append(int(item))
    return task_ids


def read_task_misc(path: Path) -> dict[int, dict[str, Any]]:
    tasks: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return tasks
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                task_id = int(row["Task ID"])
            except (KeyError, TypeError, ValueError):
                continue
            rooms = [
                room.strip()
                for room in (row.get("Rooms to inlcude") or "").splitlines()
                if room.strip()
            ]
            tasks[task_id] = {
                "task_id": task_id,
                "task_name": row.get("Task", ""),
                "rooms": rooms,
                "ready_for_local": row.get("Task Ready for local"),
                "ready_for_test": row.get("Task Ready to Test"),
            }
    return tasks


def read_test_instances(path: Path) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    if not path.exists():
        return result
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                task_id = int(row["Task ID"])
            except (KeyError, TypeError, ValueError):
                continue
            ids: list[int] = []
            for item in (row.get("Public Test Instance IDs") or "").split(","):
                item = item.strip()
                if item:
                    ids.append(int(item))
            result[task_id] = ids
    return result


def read_episode_metadata(path: Path) -> dict[int, dict[str, Any]]:
    by_task: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "episodes": 0,
            "length_min": None,
            "length_max": None,
            "length_sum": 0,
            "episode_indices": [],
        }
    )
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            episode_index = int(row.get("episode_index", -1))
            if episode_index < 0:
                continue
            task_id = episode_index // 10000
            length = int(row.get("length", 0) or 0)
            bucket = by_task[task_id]
            bucket["episodes"] += 1
            bucket["length_min"] = length if bucket["length_min"] is None else min(bucket["length_min"], length)
            bucket["length_max"] = length if bucket["length_max"] is None else max(bucket["length_max"], length)
            bucket["length_sum"] += length
            if len(bucket["episode_indices"]) < 20:
                bucket["episode_indices"].append(episode_index)
    final: dict[int, dict[str, Any]] = {}
    for task_id, stats in by_task.items():
        episodes = stats["episodes"]
        final[task_id] = {
            "episodes": episodes,
            "length_min": stats["length_min"],
            "length_max": stats["length_max"],
            "length_mean": stats["length_sum"] / episodes if episodes else None,
            "episode_indices_sample": stats["episode_indices"],
        }
    return final


def parse_raw_episode_path(path: str) -> tuple[int, int, int] | None:
    match = re.match(r"task-(\d{4})/episode_(\d{4})(\d{3})(\d)\.hdf5$", path)
    if not match:
        return None
    task_dir_id, task_file_id, instance_id, traj_id = match.groups()
    if task_dir_id != task_file_id:
        return None
    return int(task_dir_id), int(instance_id), int(traj_id)


def mib(size: int | float) -> float:
    return float(size) / (1024 * 1024)


def summarize_raw_task(
    *,
    task_id: int,
    task_info: dict[str, Any],
    test_instances: list[int],
    episode_meta: dict[str, Any],
    max_candidates_per_task: int,
) -> dict[str, Any]:
    path = f"task-{task_id:04d}"
    try:
        files = fetch_hf_tree(RAWDATA_REPO, path, recursive=True)
        fetch_error = None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        files = []
        fetch_error = f"{type(exc).__name__}: {exc}"

    hdf5_files: list[dict[str, Any]] = []
    instance_counts: Counter[int] = Counter()
    traj_counts: Counter[int] = Counter()
    total_size = 0
    for item in files:
        if item.get("type") != "file" or not str(item.get("path", "")).endswith(".hdf5"):
            continue
        size = int(item.get("size", 0) or 0)
        parsed = parse_raw_episode_path(str(item.get("path", "")))
        if parsed is None:
            continue
        _, instance_id, traj_id = parsed
        instance_counts[instance_id] += 1
        traj_counts[traj_id] += 1
        total_size += size
        hdf5_files.append(
            {
                "path": item["path"],
                "size_bytes": size,
                "size_mib": round(mib(size), 2),
                "instance_id": instance_id,
                "traj_id": traj_id,
            }
        )

    hdf5_files.sort(key=lambda row: (row["size_bytes"], row["instance_id"], row["traj_id"]))
    public_test_set = set(test_instances)
    preferred = [
        row for row in hdf5_files if not public_test_set or row["instance_id"] in public_test_set
    ]
    if not preferred:
        preferred = hdf5_files
    candidates = preferred[:max_candidates_per_task]
    return {
        "task_id": task_id,
        "task_dir": path,
        "task_name": task_info.get("task_name", f"task-{task_id:04d}"),
        "ready_for_local": task_info.get("ready_for_local"),
        "rooms": task_info.get("rooms", []),
        "fetch_error": fetch_error,
        "raw_hdf5_files": len(hdf5_files),
        "raw_total_size_bytes": total_size,
        "raw_total_size_gib": round(total_size / (1024**3), 3),
        "raw_min_file_mib": round(mib(min([row["size_bytes"] for row in hdf5_files] or [0])), 2),
        "raw_max_file_mib": round(mib(max([row["size_bytes"] for row in hdf5_files] or [0])), 2),
        "raw_instance_count": len(instance_counts),
        "raw_instance_ids_sample": sorted(instance_counts)[:20],
        "raw_traj_counts": dict(sorted(traj_counts.items())),
        "public_test_instance_ids_sample": test_instances[:20],
        "local_episode_metadata": episode_meta,
        "recommended_download_candidates": candidates,
        "recommended_download_size_mib": round(sum(row["size_bytes"] for row in candidates) / (1024 * 1024), 2),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_report(summary: dict[str, Any]) -> str:
    lines = [
        "# BEHAVIOR HuggingFace Dataset Probe v0",
        "",
        "本报告由 `real_data_pipeline/stages/probe_behavior_hf_datasets.py` 生成。",
        "",
        "## Status",
        "",
        "```text",
        summary["status"],
        "```",
        "",
        "## Purpose",
        "",
        "This probe checks remote HuggingFace metadata before downloading large BEHAVIOR files. It does not download HDF5, parquet, or videos.",
        "",
        "## Repositories",
        "",
        "```text",
        RAWDATA_REPO,
        DEMOS_REPO,
        TASK_INSTANCES_REPO,
        "```",
        "",
        "## Candidate Task Summary",
        "",
        "| task | name | raw files | raw GiB | instances | recommended files | recommended MiB |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for task in summary["tasks"]:
        lines.append(
            f"| {task['task_id']} | `{task['task_name']}` | {task['raw_hdf5_files']} | "
            f"{task['raw_total_size_gib']} | {task['raw_instance_count']} | "
            f"{len(task['recommended_download_candidates'])} | {task['recommended_download_size_mib']} |"
        )

    lines.extend(
        [
            "",
            "## Recommended First Download",
            "",
            "Use the JSONL file below as the source of selected HDF5 paths:",
            "",
            "```text",
            summary["candidate_jsonl"],
            "```",
            "",
            "Example command shape after installing `huggingface_hub[cli]`:",
            "",
            "```bash",
            "huggingface-cli download behavior-1k/2025-challenge-rawdata \\",
            "  --repo-type dataset \\",
            "  --include \"task-0045/episode_00450010.hdf5\" \\",
            "  --local-dir /root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-rawdata",
            "```",
            "",
            "## Notes",
            "",
            "- `rawdata` is the right source for replayable trajectories.",
            "- `tro_state` remains unsuitable as a main benchmark episode source.",
            "- The first download should stay small, then replay one episode before scaling.",
            "- If replay fails, keep instance diversity as a documented limitation and continue task/state diversity expansion from local templates.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe BEHAVIOR HuggingFace datasets.")
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--task-ids",
        type=parse_task_ids,
        default=DEFAULT_TASK_IDS,
        help="Comma-separated task ids, e.g. 0,40,45",
    )
    parser.add_argument("--max-candidates-per-task", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata_dir = args.behavior_root / "datasets" / "2025-challenge-task-instances" / "metadata"
    task_misc = read_task_misc(metadata_dir / "B50_task_misc.csv")
    test_instances = read_test_instances(metadata_dir / "test_instances.csv")
    episode_metadata = read_episode_metadata(metadata_dir / "episodes.jsonl")

    repo_roots: dict[str, Any] = {}
    status = "PASS"
    for repo in (TASK_INSTANCES_REPO, RAWDATA_REPO, DEMOS_REPO):
        try:
            tree = fetch_hf_tree(repo, "", recursive=False)
            repo_roots[repo] = {
                "ok": True,
                "items": len(tree),
                "paths": [item.get("path") for item in tree[:80]],
            }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            status = "FAIL"
            repo_roots[repo] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    tasks = [
        summarize_raw_task(
            task_id=task_id,
            task_info=task_misc.get(task_id, {}),
            test_instances=test_instances.get(task_id, []),
            episode_meta=episode_metadata.get(task_id, {}),
            max_candidates_per_task=args.max_candidates_per_task,
        )
        for task_id in args.task_ids
    ]
    if any(task["fetch_error"] for task in tasks):
        status = "PASS_WITH_LIMITS" if status == "PASS" else status

    candidate_rows: list[dict[str, Any]] = []
    for task in tasks:
        for candidate in task["recommended_download_candidates"]:
            candidate_rows.append(
                {
                    "repo": RAWDATA_REPO,
                    "task_id": task["task_id"],
                    "task_name": task["task_name"],
                    "path": candidate["path"],
                    "size_bytes": candidate["size_bytes"],
                    "size_mib": candidate["size_mib"],
                    "instance_id": candidate["instance_id"],
                    "traj_id": candidate["traj_id"],
                    "download_target_root": str(
                        args.behavior_root / "datasets" / "2025-challenge-rawdata"
                    ),
                }
            )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "behavior_hf_probe_v0.json"
    report_path = args.output_dir / "behavior_hf_probe_v0.md"
    candidate_path = args.output_dir / "rawdata_download_candidates_v0.jsonl"
    summary = {
        "generated_at": utc_now(),
        "status": status,
        "behavior_root": str(args.behavior_root),
        "metadata_dir": str(metadata_dir),
        "task_ids": args.task_ids,
        "repo_roots": repo_roots,
        "tasks": tasks,
        "candidate_jsonl": rel(candidate_path),
        "recommended_total_size_mib": round(sum(row["size_bytes"] for row in candidate_rows) / (1024 * 1024), 2),
        "outputs": {
            "json": rel(json_path),
            "report": rel(report_path),
            "candidate_jsonl": rel(candidate_path),
        },
    }
    write_json(json_path, summary)
    write_jsonl(candidate_path, candidate_rows)
    report_path.write_text(build_report(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "tasks": len(tasks),
                "candidate_files": len(candidate_rows),
                "recommended_total_size_mib": summary["recommended_total_size_mib"],
                "report": rel(report_path),
                "candidate_jsonl": rel(candidate_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
