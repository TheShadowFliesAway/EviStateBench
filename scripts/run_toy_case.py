from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lifelongscenedb import LifelongSceneDB, Observation
from lifelongscenedb.utils import ensure_dir, write_json


def build_toy_observations() -> list[Observation]:
    """构造一个最小 toy case，用来验证核心更新和查询逻辑。

    场景含义：
    1. 8.05 高置信观察到 cup_1 在 table_1；
    2. 8.25 低置信噪声仍声称 cup_1 在 table_1；
    3. 8.30 高置信观察到 cup_1 已移动到 sink_1。
    """

    return [
        # 初始事实：杯子在桌上，置信度高，会创建 active fact。
        Observation("toy_1", 8.05, 8.05, "robot_0", "kitchen", "cup_1", "in", "table_1", "table_1", 0.90, "frame_0805"),
        # 噪声观察：同样说杯子在桌上，但置信度低；用于测试支持融合和噪声标记。
        Observation("toy_2", 8.25, 8.25, "robot_0", "kitchen", "cup_1", "in", "table_1", "table_1", 0.25, "frame_0825", is_noisy=True),
        # 冲突观察：杯子出现在水槽，高置信度会推动新事实，并反驳旧位置。
        Observation("toy_3", 8.30, 8.30, "robot_0", "kitchen", "cup_1", "in", "sink_1", "sink_1", 0.88, "frame_0830"),
    ]


def run(out: str | Path) -> dict:
    """运行 toy case，并把中间事实、观察和查询结果写到输出目录。"""

    # 确保输出目录存在。
    out = ensure_dir(out)

    # 创建一份空的场景记忆数据库。
    db = LifelongSceneDB()

    # 按 arrival_time 顺序写入 toy observations，内部会更新 facts、provenance 和索引。
    db.ingest_many(build_toy_observations())

    # 查询 cup_1 当前最可能位置；预期是 sink_1。
    current = db.locate_current("cup_1")
    # 查询 cup_1 在 8.10 这个历史场景时间点的位置；预期仍是 table_1。
    asof = db.locate_asof("cup_1", 8.10)
    # 查询 “cup_1 in sink_1” 这个事实背后的支持证据。
    evidence = db.get_evidence("cup_1", "in", "sink_1")
    # 返回 cup_1 的多个候选位置，便于观察 alternatives 和置信度排序。
    topk = db.topk_locations("cup_1")

    # 导出内部状态，方便用 CSV 检查 Fact/Observation 是否符合预期。
    db.export_facts().to_csv(out / "facts.csv", index=False)
    db.export_observations().to_csv(out / "observations.csv", index=False)

    # 组装主要查询结果，写成 JSON 便于测试或人工查看。
    results = {
        "current": current.to_dict() if current else None,
        "asof": asof.to_dict() if asof else None,
        "evidence": evidence,
        "topk": [row.to_dict() for row in topk],
    }
    write_json(out / "results.json", results)

    # 在命令行输出几条关键结果，作为快速 sanity check。
    print(f"current cup_1 -> {current.location if current else None}")
    print(f"asof cup_1 at 8.10 -> {asof.location if asof else None}")
    print(f"evidence for cup_1 in sink_1 includes {[row['frame_id'] for row in evidence]}")
    return results


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser()
    # 指定输出目录，默认为 outputs/toy_case
    parser.add_argument("--out", default="outputs/toy_case")
    args = parser.parse_args()
    run(args.out)


if __name__ == "__main__":
    main()
