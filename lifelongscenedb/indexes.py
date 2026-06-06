from __future__ import annotations

from collections import defaultdict

from .schema import Fact


class MemoryIndexes:
    """内存事实索引。

    这些索引用 fact_id 指向 MemoryStore.facts 中的 Fact，用于避免查询时扫描全部事实。
    当前 MVP 里 object_index 已被查询实际使用，其他索引主要是为时间、区域和证据查询加速预留。
    """

    def __init__(self) -> None:
        # 对象/位置索引：subject、object、location 及 subject 分词 -> fact_id 集合。
        # 例如 cup_1、cup、1、table_1 都可能指向同一条事实。
        self.object_index: dict[str, set[str]] = defaultdict(set)
        # 时间索引：subject -> 按 valid_start 排序的 fact_id 列表。
        # 目标是加速 as-of 查询或对象时间线查询；当前代码暂未直接使用。
        self.temporal_index: dict[str, list[str]] = defaultdict(list)
        # 区域索引：room、location、object -> fact_id 集合。
        # 目标是加速按房间/区域过滤的查询；当前代码暂未直接使用。
        self.region_index: dict[str, set[str]] = defaultdict(set)
        # 证据索引：fact_id -> 支持该事实的 observation id 列表。
        # 目标是加速 provenance/evidence 查询；当前代码主要直接读取 Fact.supporting_obs_ids。
        self.provenance_index: dict[str, list[str]] = defaultdict(list)

    def clear(self) -> None:
        """清空所有索引。"""

        self.object_index.clear()
        self.temporal_index.clear()
        self.region_index.clear()
        self.provenance_index.clear()

    def rebuild(self, facts: dict[str, Fact]) -> None:
        """根据当前所有 facts 重建索引。"""

        self.clear()
        for fact in facts.values():
            self.update_fact(fact)

    def update_fact(self, fact: Fact) -> None:
        """把一条新增或更新后的 Fact 写入各类索引。"""

        # object_index 用多个 token 指向同一个 fact，方便用对象名、位置名或粗粒度词查候选。
        tokens = {fact.subject, fact.object, fact.location}
        # 额外把 subject 按下划线拆开，例如 cup_1 会拆成 cup 和 1。
        tokens.update(part for part in fact.subject.split("_") if part)
        for token in tokens:
            self.object_index[token.lower()].add(fact.fact_id)

        # temporal_index 保存同一个 subject 的所有 fact_id，并按 valid_start 排序。
        ids = self.temporal_index[fact.subject]
        if fact.fact_id not in ids:
            ids.append(fact.fact_id)
        ids.sort(key=lambda fid: facts_sort_key(fid, fact))

        # region_index 用 room、location、object 做区域/位置入口，方便后续区域过滤。
        for key in {fact.room, fact.location, fact.object}:
            if key:
                self.region_index[key.lower()].add(fact.fact_id)

        # provenance_index 保存该 fact 当前的支持观察列表，方便后续证据查询。
        self.provenance_index[fact.fact_id] = list(fact.supporting_obs_ids)


def facts_sort_key(fid: str, fact: Fact) -> tuple[float, str]:
    """temporal_index 内 fact_id 的排序键。"""

    return (fact.valid_start, fid)
