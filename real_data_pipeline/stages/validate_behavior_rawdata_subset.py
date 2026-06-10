#!/usr/bin/env python3
"""Validate downloaded BEHAVIOR raw HDF5 files without launching simulator."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATES = (
    REPO_ROOT
    / "real_data_pipeline"
    / "artifacts"
    / "download_probe_stage_b"
    / "rawdata_download_candidates_v0.jsonl"
)
DEFAULT_TARGET_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-rawdata")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "download_probe_stage_b"


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


def inspect_hdf5(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h5:
        if "data" not in h5:
            return {"valid_hdf5": False, "message": "missing /data group"}
        data = h5["data"]
        demo_keys = sorted(key for key in data.keys() if key.startswith("demo_"))
        if not demo_keys:
            return {"valid_hdf5": False, "message": "missing /data/demo_* group"}
        demo = data[demo_keys[0]]
        required = ["action", "state", "state_size", "reward", "terminated", "truncated"]
        missing = [key for key in required if key not in demo]
        if missing:
            return {"valid_hdf5": False, "message": f"missing datasets: {missing}"}
        action_shape = list(demo["action"].shape)
        state_shape = list(demo["state"].shape)
        valid_lengths = state_shape[0] == action_shape[0] + 1
        return {
            "valid_hdf5": bool(valid_lengths),
            "message": "" if valid_lengths else "state length is not action length + 1",
            "root_keys": list(h5.keys()),
            "data_attrs": {key: json_safe(data.attrs[key]) for key in data.attrs.keys()},
            "demo_key": demo_keys[0],
            "demo_attrs": {key: json_safe(demo.attrs[key]) for key in demo.attrs.keys()},
            "action_shape": action_shape,
            "action_dtype": str(demo["action"].dtype),
            "state_shape": state_shape,
            "state_dtype": str(demo["state"].dtype),
            "reward_shape": list(demo["reward"].shape),
            "terminated_shape": list(demo["terminated"].shape),
            "truncated_shape": list(demo["truncated"].shape),
        }


def json_safe(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def build_report(summary: dict[str, Any]) -> str:
    rows = ["| status | files |", "| --- | ---: |"]
    for status, count in sorted(summary["by_status"].items()):
        rows.append(f"| `{status}` | {count} |")
    examples = ["| path | action | state | samples |", "| --- | ---: | ---: | ---: |"]
    for row in summary["files"]:
        if row["status"] == "valid":
            examples.append(
                f"| `{row['path']}` | {row['action_shape']} | {row['state_shape']} | "
                f"{row.get('num_samples', 'n/a')} |"
            )
        if len(examples) >= 12:
            break
    issues = ["| path | status | message |", "| --- | --- | --- |"]
    issue_rows = [row for row in summary["files"] if row["status"] != "valid"]
    if issue_rows:
        for row in issue_rows[:50]:
            issues.append(f"| `{row['path']}` | `{row['status']}` | {row.get('message', '')} |")
    else:
        issues.append("| n/a | n/a | none |")
    return f"""# BEHAVIOR Raw HDF5 Validation Report v0

本报告只验证 raw HDF5 文件本身，不启动 OmniGibson simulator。

## Status

```text
{summary['status']}
```

## Summary

| item | value |
| --- | ---: |
| candidate files | {summary['candidate_files']} |
| exact-size files | {summary['exact_size_files']} |
| valid HDF5 files | {summary['valid_hdf5_files']} |
| invalid / incomplete files | {summary['invalid_or_incomplete_files']} |

## By Status

{chr(10).join(rows)}

## Valid Examples

{chr(10).join(examples)}

## Issues

{chr(10).join(issues)}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate downloaded BEHAVIOR raw HDF5 files.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_jsonl(args.candidates)
    files: list[dict[str, Any]] = []
    by_status: dict[str, int] = {}

    for row in rows:
        rel_path = row["path"]
        expected_size = int(row.get("size_bytes", 0) or 0)
        path = args.target_root / rel_path
        result = {"path": rel_path, "expected_size": expected_size, "actual_size": 0}
        if not path.exists():
            result["status"] = "missing"
            result["message"] = "file does not exist"
        else:
            actual_size = path.stat().st_size
            result["actual_size"] = actual_size
            if actual_size != expected_size:
                result["status"] = "incomplete"
                result["message"] = f"expected {expected_size}, got {actual_size}"
            else:
                try:
                    info = inspect_hdf5(path)
                    result.update(info)
                    result["status"] = "valid" if info["valid_hdf5"] else "invalid_hdf5"
                    result["num_samples"] = (
                        info.get("demo_attrs", {}).get("num_samples")
                        if isinstance(info.get("demo_attrs"), dict)
                        else None
                    )
                except Exception as exc:  # noqa: BLE001 - validation report should keep going.
                    result["status"] = "invalid_hdf5"
                    result["message"] = f"{type(exc).__name__}: {exc}"
        by_status[result["status"]] = by_status.get(result["status"], 0) + 1
        files.append(result)

    valid = [row for row in files if row["status"] == "valid"]
    exact_size = [row for row in files if row.get("actual_size") == row.get("expected_size")]
    summary = {
        "generated_at": utc_now(),
        "status": "PASS" if len(valid) == len(files) else "PASS_WITH_INCOMPLETE_DOWNLOADS",
        "candidate_jsonl": rel(args.candidates),
        "target_root": str(args.target_root),
        "candidate_files": len(files),
        "exact_size_files": len(exact_size),
        "valid_hdf5_files": len(valid),
        "invalid_or_incomplete_files": len(files) - len(valid),
        "by_status": by_status,
        "files": files,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "rawdata_hdf5_validation_v0.json"
    md_path = args.output_dir / "rawdata_hdf5_validation_v0.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_report(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": summary["status"],
                "candidate_files": summary["candidate_files"],
                "valid_hdf5_files": summary["valid_hdf5_files"],
                "invalid_or_incomplete_files": summary["invalid_or_incomplete_files"],
                "report": rel(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
