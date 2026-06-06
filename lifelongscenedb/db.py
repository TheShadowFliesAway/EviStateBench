from __future__ import annotations

from typing import Any

import pandas as pd

from .indexes import MemoryIndexes
from .queries import choose_best, fact_claim_matches, match_object, result_from_fact
from .schema import Fact, Observation, QueryResult
from .store import MemoryStore
from .updater import SceneUpdater


DEFAULT_CONFIG: dict[str, Any] = {
    # 新观察的置信度达到该阈值时，才会被激活为新的 active fact。
    "activate_threshold": 0.6,
    # 旧事实被冲突观察衰减后，置信度低于该阈值时会被标记为 contradicted。
    "expire_threshold": 0.35,
    # 冲突衰减强度：越大，新冲突观察越容易推翻旧事实。
    "conflict_gamma": 0.7,
    # 重新观察阈值：当前最好结果低于该值时，should_reobserve 会建议重新观察。
    "reobserve_threshold": 0.6,
    # 是否启用内存索引；关闭后查询会退化为扫描所有 facts，用于 no-index 消融。
    "use_indexes": True,
}


class LifelongSceneDB:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.use_indexes = bool(self.config.get("use_indexes", True))
        self.store = MemoryStore()
        self.indexes = MemoryIndexes()
        self.updater = SceneUpdater(self.store, self.indexes, self.config, self.use_indexes)

    def ingest_observation(self, obs: Observation) -> None:
        self.updater.ingest_observation(obs)

    def ingest_many(self, observations: list[Observation]) -> None:
        self.updater.ingest_many(observations)

    def locate_current(self, object_desc: str, constraints: dict | None = None) -> QueryResult | None:
        """查询对象当前最可能的位置。

        只考虑 status == "active" 的 facts；如果传入 room/location 约束，
        会先过滤候选，再选出置信度和时间排序最优的一条。
        """

        # 先找与 object_desc 相关的候选 facts，再只保留当前仍 active 的事实。
        candidates = [f for f in self._candidate_facts(object_desc) if f.status == "active"]
        if constraints:
            location = constraints.get("location")
            room = constraints.get("room")
            # location 约束既匹配 fact.location，也匹配 fact.object。
            if location:
                candidates = [f for f in candidates if f.location == location or f.object == location]
            # room 约束用于限制房间或区域。
            if room:
                candidates = [f for f in candidates if f.room == room]
        # 从过滤后的候选中选出最佳事实。
        best = choose_best(candidates)
        if best is None:
            return None
        # 将内部 Fact 转成对外 QueryResult，并带上其他候选作为 alternatives。
        return result_from_fact(best, self.current_time(), candidates)

    def locate_asof(self, object_desc: str, time: float) -> QueryResult | None:
        """查询对象在某个场景时间点的位置。

        与 locate_current 不同，这里不只看当前 active facts，而是根据 valid_start / valid_end
        判断某条事实在给定 time 时是否仍然成立。
        """

        # 找出在给定 time 这个 valid time 上有效的候选 facts。
        candidates = [
            f
            for f in self._candidate_facts(object_desc)
            if f.valid_start <= time and (f.valid_end is None or time < f.valid_end)
        ]
        # 同一时间点可能仍有多个候选，继续按置信度和时间选择最佳事实。
        best = choose_best(candidates)
        if best is None:
            return None
        # 返回结果中的 time 使用用户查询的历史时间，而不是 current_time。
        return result_from_fact(best, time, candidates)

    def detect_changes(
        self,
        region: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> list[dict]:
        """检测对象位置或关系对象的历史变化。

        返回同一 subject/predicate 下相邻 facts 的变化记录，例如 cup_1 从 table_1 到 sink_1。

        Args:
            region: 可选区域过滤条件；会匹配 Fact.room、Fact.location 或 Fact.object。
            start_time: 可选起始场景时间；只返回 change_time >= start_time 的变化。
            end_time: 可选结束场景时间；只返回 change_time <= end_time 的变化。
        """

        # 变化检测需要历史 facts，因此这里读取全部 facts，而不是只看 active facts。
        facts = list(self.store.facts.values())
        if region:
            # region 可以匹配 room、location 或 object。
            facts = [f for f in facts if f.room == region or f.location == region or f.object == region]
        groups: dict[tuple[str, str], list[Fact]] = {}
        for fact in facts:
            # 只有同一 subject/predicate 下的 facts 才应该互相比较变化。
            groups.setdefault((fact.subject, fact.predicate), []).append(fact)
        changes: list[dict] = []
        for (subject, predicate), items in groups.items():
            # 按 valid time 排序；tx_start 作为同一 valid_start 下的稳定次序。
            items = sorted(items, key=lambda f: (f.valid_start, f.tx_start))
            # 两两比较相邻 facts：fact1->fact2, fact2->fact3, ...
            for old, new in zip(items, items[1:]):
                # object 和 location 都没变时，不算变化。
                if old.location == new.location and old.object == new.object:
                    continue
                # 变化时间定义为新 fact 开始成立的 valid_start。
                change_time = new.valid_start
                if start_time is not None and change_time < start_time:
                    continue
                if end_time is not None and change_time > end_time:
                    continue
                # 输出一条变化记录，包含变化前后位置、变化时间和新事实置信度。
                changes.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "old_location": old.location,
                        "new_location": new.location,
                        "old_object": old.object,
                        "new_object": new.object,
                        "change_time": change_time,
                        "confidence": new.confidence,
                    }
                )
        return changes

    def get_evidence(self, subject: str, predicate: str, object: str) -> list[dict]:
        """查询某个事实断言的支持证据。

        Args:
            subject: 被查询的实体，例如 cup_1。
            predicate: 关系谓词，例如 in。
            object: 关系对象，例如 sink_1。

        Returns:
            支持该断言的 Observation 摘要列表；当前只返回 support 证据，不返回 contradict 证据。
        """

        rows: list[dict] = []
        # 遍历所有 facts，找到与 subject/predicate/object 完全匹配的事实。
        for fact in self.store.facts.values():
            if not fact_claim_matches(fact, subject, predicate, object):
                continue
            # Fact 只保存 supporting observation id；这里再回到 store.observations 取原始观察详情。
            for obs_id in fact.supporting_obs_ids:
                obs = self.store.observations.get(obs_id)
                if obs:
                    # 返回证据所需的关键信息，方便定位原始帧和观察时间。
                    rows.append(
                        {
                            "obs_id": obs.obs_id,
                            "frame_id": obs.frame_id,
                            "event_time": obs.event_time,
                            "arrival_time": obs.arrival_time,
                            "confidence": obs.confidence,
                            "source": obs.source,
                            "location": obs.location,
                            "room": obs.room,
                        }
                    )
        # 按场景时间排序，obs_id 作为同一时间下的稳定排序键。
        return sorted(rows, key=lambda r: (r["event_time"], r["obs_id"]))

    def topk_locations(self, object_desc: str, k: int = 5) -> list[QueryResult]:
        """返回对象最可能位置的 top-k 候选结果。

        Args:
            object_desc: 要查询的对象描述，例如 cup_1。
            k: 最多返回多少个候选位置。
        """

        # 先取出与对象相关的所有候选 facts，不限于 active。
        candidates = self._candidate_facts(object_desc)
        # active 优先，其次按 confidence 和 valid_start 从高到低排序。
        ordered = sorted(
            candidates,
            key=lambda f: (f.status == "active", f.confidence, f.valid_start),
            reverse=True,
        )
        # 将前 k 个 fact 分别转成 QueryResult；每个结果里也会带上完整候选列表作为 alternatives。
        return [result_from_fact(f, self.current_time(), ordered) for f in ordered[:k]]

    def should_reobserve(self, object_desc: str, threshold: float = 0.6) -> dict:
        """判断是否应该重新观察某个对象。

        如果当前找不到该对象，或者当前最佳定位结果的置信度低于 threshold，
        就建议重新观察。
        """

        # 先查询当前最佳位置。
        result = self.locate_current(object_desc)
        # 没有结果，或结果置信度不足，都需要重新观察。
        should = result is None or result.confidence < threshold
        return {
            "should_reobserve": should,
            "object": object_desc,
            "best_location": result.location if result else None,
            "confidence": result.confidence if result else 0.0,
            "threshold": threshold,
        }

    def export_facts(self) -> pd.DataFrame:
        return self.store.export_facts()

    def export_observations(self) -> pd.DataFrame:
        return self.store.export_observations()

    def current_time(self) -> float | None:
        """返回当前记忆中最新的场景时间。

        这里使用所有 Observation 的最大 event_time，而不是 arrival_time。
        如果还没有任何观察，则返回 None。
        """

        if not self.store.observations:
            return None
        return max(obs.event_time for obs in self.store.observations.values())

    def _candidate_facts(self, object_desc: str) -> list[Fact]:
        """查找与 object_desc 相关的候选 facts。

        这里只负责缩小搜索范围，不判断 fact 是否 active，也不选择最佳结果。
        """

        if self.use_indexes:
            ids = set()
            desc = object_desc.lower()
            # 优先走 object_index 的精确匹配，例如 cup_1 -> {fact_id...}。
            exact_ids = self.indexes.object_index.get(desc, set())
            if exact_ids:
                return [self.store.facts[fid] for fid in exact_ids if fid in self.store.facts]
            # 如果没有精确命中，再做包含匹配，例如 cup 可以匹配 cup_1、cup_2。
            for token, fact_ids in self.indexes.object_index.items():
                if desc in token:
                    ids.update(fact_ids)
            if ids:
                return [self.store.facts[fid] for fid in ids if fid in self.store.facts]
        # 关闭索引或索引没有命中时，退化为扫描全部 facts。
        return [f for f in self.store.facts.values() if match_object(object_desc, f.subject)]
