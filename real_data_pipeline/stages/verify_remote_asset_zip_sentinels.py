#!/usr/bin/env python3
"""Verify selected asset hashes inside a remote ZIP without downloading it all."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, Iterable, Tuple

import requests


DEFAULT_URL = (
    "https://modelscope.cn/datasets/behavior-1k/zipped-datasets/resolve/master/"
    "behavior-1k-assets-3.7.2rc1.zip"
)
DEFAULT_SENTINELS = (
    "real_data_pipeline/artifacts/environment_freeze_20260610T124824Z/"
    "asset_sentinel_hashes_current.csv"
)
DEFAULT_OUTPUT = (
    "real_data_pipeline/artifacts/environment_freeze_20260610T124824Z/"
    "remote_modelscope_asset_sentinel_hash_check.csv"
)

EOCD_SIG = b"PK\x05\x06"
ZIP64_EOCD_LOC_SIG = b"PK\x06\x07"
ZIP64_EOCD_SIG = b"PK\x06\x06"
CD_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"


class RangeClient:
    def __init__(self, url: str, timeout: int) -> None:
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()
        # ModelScope is fastest from this AutoDL host without inherited proxies.
        self.session.trust_env = False

    def head(self) -> Tuple[int, Dict[str, str]]:
        r = self.session.head(self.url, allow_redirects=True, timeout=self.timeout)
        r.raise_for_status()
        return int(r.headers["Content-Length"]), dict(r.headers)

    def get_range(self, start: int, end: int) -> bytes:
        headers = {"Range": f"bytes={start}-{end}"}
        r = self.session.get(
            self.url, headers=headers, allow_redirects=True, timeout=self.timeout
        )
        r.raise_for_status()
        if r.status_code != 206:
            raise RuntimeError(f"server did not honor range request: HTTP {r.status_code}")
        return r.content


def le16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def le32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def le64(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def locate_central_directory(client: RangeClient, size: int) -> Tuple[int, int, int]:
    tail_len = min(size, 1024 * 1024)
    tail_start = size - tail_len
    tail = client.get_range(tail_start, size - 1)
    eocd_rel = tail.rfind(EOCD_SIG)
    if eocd_rel < 0:
        raise RuntimeError("ZIP EOCD not found")

    eocd = tail[eocd_rel : eocd_rel + 22]
    entries = le16(eocd, 10)
    cd_size = le32(eocd, 12)
    cd_offset = le32(eocd, 16)

    zip64 = entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF
    if not zip64:
        return cd_offset, cd_size, entries

    locator_rel = eocd_rel - 20
    locator = tail[locator_rel : locator_rel + 20]
    if len(locator) != 20 or not locator.startswith(ZIP64_EOCD_LOC_SIG):
        raise RuntimeError("ZIP64 EOCD locator not found")
    zip64_eocd_offset = le64(locator, 8)
    zip64_head = client.get_range(zip64_eocd_offset, zip64_eocd_offset + 55)
    if not zip64_head.startswith(ZIP64_EOCD_SIG):
        raise RuntimeError("ZIP64 EOCD not found")
    entries64 = le64(zip64_head, 32)
    cd_size64 = le64(zip64_head, 40)
    cd_offset64 = le64(zip64_head, 48)
    return cd_offset64, cd_size64, entries64


def iter_central_directory(cd: bytes) -> Iterable[Dict[str, int | str]]:
    off = 0
    while off < len(cd):
        if cd[off : off + 4] != CD_SIG:
            raise RuntimeError(f"bad central directory signature at offset {off}")
        method = le16(cd, off + 10)
        crc32 = le32(cd, off + 16)
        comp_size = le32(cd, off + 20)
        uncomp_size = le32(cd, off + 24)
        name_len = le16(cd, off + 28)
        extra_len = le16(cd, off + 30)
        comment_len = le16(cd, off + 32)
        local_offset = le32(cd, off + 42)
        name = cd[off + 46 : off + 46 + name_len].decode("utf-8")
        extra = cd[off + 46 + name_len : off + 46 + name_len + extra_len]

        if 0xFFFFFFFF in (comp_size, uncomp_size, local_offset):
            idx = 0
            while idx + 4 <= len(extra):
                header_id = le16(extra, idx)
                data_size = le16(extra, idx + 2)
                data = extra[idx + 4 : idx + 4 + data_size]
                if header_id == 0x0001:
                    pos = 0
                    if uncomp_size == 0xFFFFFFFF:
                        uncomp_size = le64(data, pos)
                        pos += 8
                    if comp_size == 0xFFFFFFFF:
                        comp_size = le64(data, pos)
                        pos += 8
                    if local_offset == 0xFFFFFFFF:
                        local_offset = le64(data, pos)
                    break
                idx += 4 + data_size

        yield {
            "name": name,
            "method": method,
            "crc32": crc32,
            "compressed_size": comp_size,
            "uncompressed_size": uncomp_size,
            "local_offset": local_offset,
        }
        off += 46 + name_len + extra_len + comment_len


def read_zip_member(client: RangeClient, entry: Dict[str, int | str]) -> bytes:
    local_offset = int(entry["local_offset"])
    head = client.get_range(local_offset, local_offset + 30 - 1)
    if not head.startswith(LOCAL_SIG):
        raise RuntimeError(f"bad local header for {entry['name']}")
    name_len = le16(head, 26)
    extra_len = le16(head, 28)
    data_start = local_offset + 30 + name_len + extra_len
    comp_size = int(entry["compressed_size"])
    comp = client.get_range(data_start, data_start + comp_size - 1)
    method = int(entry["method"])
    if method == 0:
        data = comp
    elif method == 8:
        data = zlib.decompress(comp, -15)
    else:
        raise RuntimeError(f"unsupported compression method {method} for {entry['name']}")
    if len(data) != int(entry["uncompressed_size"]):
        raise RuntimeError(f"size mismatch after decompressing {entry['name']}")
    crc = zlib.crc32(data) & 0xFFFFFFFF
    if crc != int(entry["crc32"]):
        raise RuntimeError(f"crc mismatch for {entry['name']}")
    return data


def sentinel_zip_names(path: str) -> Tuple[str, ...]:
    rel = path.split("/behavior-1k-assets/", 1)[-1]
    return (rel, f"behavior-1k-assets/{rel}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--sentinels", default=DEFAULT_SENTINELS)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    client = RangeClient(args.url, args.timeout)
    size, headers = client.head()
    cd_offset, cd_size, entries = locate_central_directory(client, size)
    cd = client.get_range(cd_offset, cd_offset + cd_size - 1)

    wanted_rows = list(csv.DictReader(open(args.sentinels, newline="")))
    wanted_names = {}
    for row in wanted_rows:
        for name in sentinel_zip_names(row["path"]):
            wanted_names[name] = row

    found = {}
    for entry in iter_central_directory(cd):
        name = str(entry["name"])
        if name in wanted_names:
            found[name] = entry

    results = []
    for row in wanted_rows:
        candidates = sentinel_zip_names(row["path"])
        entry = next((found[x] for x in candidates if x in found), None)
        if entry is None:
            results.append(
                {
                    **row,
                    "remote_zip_path": "",
                    "remote_md5": "",
                    "remote_match": "false",
                    "remote_status": "missing_in_zip",
                }
            )
            continue
        data = read_zip_member(client, entry)
        md5 = hashlib.md5(data).hexdigest()
        results.append(
            {
                **row,
                "remote_zip_path": entry["name"],
                "remote_md5": md5,
                "remote_match": str(md5 == row["expected_from_rawdata_probe"]).lower(),
                "remote_status": "ok",
            }
        )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    matched = sum(r["remote_match"] == "true" for r in results)
    summary = {
        "status": "PASS" if matched == len(results) else "HASH_MISMATCH",
        "url": args.url,
        "zip_size": size,
        "x_linked_etag": headers.get("x-linked-etag") or headers.get("X-Linked-Etag"),
        "central_directory_entries": entries,
        "sentinel_checked": len(results),
        "sentinel_matched": matched,
        "output": str(out),
    }
    print(json.dumps(summary, indent=2))
    return 0 if matched == len(results) else 2


if __name__ == "__main__":
    sys.exit(main())
