#!/usr/bin/env python3
"""Download selected BEHAVIOR raw HDF5 files from HuggingFace.

The input is the JSONL produced by probe_behavior_hf_datasets.py.  The script
downloads only the listed files and preserves the task-XXXX/episode_*.hdf5
layout expected by OmniGibson replay_obs.py.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATES = (
    REPO_ROOT
    / "real_data_pipeline"
    / "artifacts"
    / "download_probe_stage_b"
    / "rawdata_download_candidates_v0.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "real_data_pipeline" / "artifacts" / "download_probe_stage_b"
)
DEFAULT_TARGET_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-rawdata")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def resolve_url(repo: str, path: str) -> str:
    quoted_repo = urllib.parse.quote(repo, safe="/")
    quoted_path = urllib.parse.quote(path, safe="/")
    return f"https://huggingface.co/datasets/{quoted_repo}/resolve/main/{quoted_path}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def download_with_curl(url: str, target: Path, expected_size: int) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_size = target.stat().st_size if target.exists() else 0
    if expected_size > 0 and existing_size > expected_size:
        target.unlink()
        existing_size = 0

    config_lines = ['user-agent = "EviStateBench-rawdata-downloader/0.1"']
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        config_lines.append(f'header = "Authorization: Bearer {hf_token}"')
    config = "\n".join(config_lines) + "\n"
    cmd = [
        "curl",
        "--config",
        "-",
        "--fail",
        "--location",
        "--continue-at",
        "-",
        "--retry",
        "8",
        "--retry-all-errors",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "30",
        "--max-time",
        "180",
        "--speed-time",
        "30",
        "--speed-limit",
        "1024",
        "--output",
        str(target),
        "--silent",
        "--show-error",
        url,
    ]
    proc = subprocess.run(cmd, input=config, text=True, capture_output=True, check=False)
    message = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
    return {"returncode": proc.returncode, "message": message[0], "resumed_from": existing_size}


def build_report(summary: dict[str, Any]) -> str:
    rows = ["| status | files | bytes |", "| --- | ---: | ---: |"]
    for status, values in sorted(summary["by_status"].items()):
        rows.append(f"| `{status}` | {values['files']} | {values['bytes']} |")
    failed = [row for row in summary["files"] if row["status"] not in {"downloaded", "skipped"}]
    failed_rows = ["| path | status | message |", "| --- | --- | --- |"]
    if failed:
        for row in failed[:100]:
            failed_rows.append(f"| `{row['path']}` | `{row['status']}` | {row.get('message', '')} |")
    else:
        failed_rows.append("| n/a | n/a | none |")
    return f"""# BEHAVIOR Rawdata Download Report v0

本报告由 `real_data_pipeline/stages/download_behavior_rawdata_subset.py` 生成。

## Status

```text
{summary['status']}
```

## Source Candidate File

```text
{summary['candidate_jsonl']}
```

## Target Root

```text
{summary['target_root']}
```

## Summary

| item | value |
| --- | ---: |
| requested files | {summary['requested_files']} |
| completed files | {summary['completed_files']} |
| failed files | {summary['failed_files']} |
| expected bytes | {summary['expected_bytes']} |
| completed bytes | {summary['completed_bytes']} |

## By Status

{chr(10).join(rows)}

## Failed / Incomplete

{chr(10).join(failed_rows)}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download selected BEHAVIOR rawdata HDF5 files.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def process_candidate(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    repo = row["repo"]
    rel_path = row["path"]
    expected_size = int(row.get("size_bytes", 0) or 0)
    target = args.target_root / rel_path
    url = resolve_url(repo, rel_path)
    file_result = {
        "path": rel_path,
        "target": str(target),
        "expected_size": expected_size,
        "url": url,
    }
    if target.exists() and target.stat().st_size == expected_size:
        file_result["status"] = "skipped"
        file_result["actual_size"] = target.stat().st_size
        return file_result
    if args.dry_run:
        file_result["status"] = "dry_run"
        file_result["actual_size"] = target.stat().st_size if target.exists() else 0
        return file_result

    download_result: dict[str, Any] = {"returncode": 1, "message": "not attempted"}
    attempts = 0
    while attempts < args.max_attempts:
        attempts += 1
        download_result = download_with_curl(url, target, expected_size)
        actual_size = target.stat().st_size if target.exists() else 0
        if actual_size == expected_size:
            break
        time.sleep(min(2 * attempts, 10))

    returncode = int(download_result["returncode"])
    actual_size = target.stat().st_size if target.exists() else 0
    file_result["actual_size"] = actual_size
    file_result["returncode"] = returncode
    file_result["attempts"] = attempts
    if download_result.get("resumed_from"):
        file_result["resumed_from"] = download_result["resumed_from"]
    if actual_size == expected_size:
        file_result["status"] = "downloaded"
    elif returncode == 0:
        file_result["status"] = "size_mismatch"
        file_result["message"] = f"expected {expected_size}, got {actual_size}"
    else:
        file_result["status"] = "failed"
        file_result["message"] = download_result.get("message", f"download returncode {returncode}")
    return file_result


def main() -> None:
    args = parse_args()
    if shutil.which("curl") is None:
        raise SystemExit("curl is required for resumable downloads")

    candidates = read_jsonl(args.candidates)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    files: list[dict[str, Any]] = []
    by_status: dict[str, dict[str, int]] = {}

    def add_status(status: str, size: int) -> None:
        bucket = by_status.setdefault(status, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += size

    worker_count = 1 if args.dry_run else max(1, args.workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(process_candidate, row, args): index
            for index, row in enumerate(candidates, start=1)
        }
        completed_count = 0
        for future in concurrent.futures.as_completed(future_to_index):
            completed_count += 1
            file_result = future.result()
            files.append(file_result)
            status = file_result["status"]
            status_size = (
                int(file_result.get("expected_size", 0) or 0)
                if status in {"downloaded", "skipped", "dry_run"}
                else int(file_result.get("actual_size", 0) or 0)
            )
            add_status(status, status_size)
            if not args.dry_run:
                print(
                    f"[{completed_count}/{len(candidates)}] {status} "
                    f"{file_result['path']} {file_result.get('actual_size', 0)}",
                    flush=True,
                )

    files.sort(key=lambda item: item["path"])

    completed = [row for row in files if row["status"] in {"downloaded", "skipped"}]
    failed = [row for row in files if row["status"] not in {"downloaded", "skipped", "dry_run"}]
    summary = {
        "generated_at": utc_now(),
        "status": "PASS" if not failed else "FAIL",
        "candidate_jsonl": rel(args.candidates),
        "target_root": str(args.target_root),
        "dry_run": args.dry_run,
        "requested_files": len(files),
        "completed_files": len(completed),
        "failed_files": len(failed),
        "expected_bytes": sum(int(row.get("expected_size", 0) or 0) for row in files),
        "completed_bytes": sum(int(row.get("actual_size", 0) or 0) for row in completed),
        "by_status": by_status,
        "files": files,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "rawdata_download_report_v0.json"
    report_path = args.output_dir / "rawdata_download_report_v0.md"
    write_json(json_path, summary)
    report_path.write_text(build_report(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": summary["status"],
                "requested_files": summary["requested_files"],
                "completed_files": summary["completed_files"],
                "failed_files": summary["failed_files"],
                "expected_gib": round(summary["expected_bytes"] / (1024**3), 3),
                "completed_gib": round(summary["completed_bytes"] / (1024**3), 3),
                "report": rel(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
