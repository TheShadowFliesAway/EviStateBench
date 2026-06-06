from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any

import pandas as pd

from .schema import Fact, Observation


class MemoryStore:
    """内存中的场景记忆存储层。

    MemoryStore 只负责保存数据，不负责判断观察是否可信、事实是否冲突，
    也不负责查询排序。这些逻辑分别由 SceneUpdater 和 LifelongSceneDB 处理。
    """

    def __init__(self) -> None:
        # 所有原始观察，key 是 obs_id。
        self.observations: dict[str, Observation] = {}
        # 所有融合后的事实，key 是 fact_id。
        self.facts: dict[str, Fact] = {}
        # 证据溯源记录：fact_id -> 该事实相关的 support / contradict 证据流水。
        self.provenance: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_observation(self, obs: Observation) -> None:
        """写入一条原始观察。"""

        self.observations[obs.obs_id] = obs

    def add_fact(self, fact: Fact) -> None:
        """写入一条融合后的场景事实。"""

        self.facts[fact.fact_id] = fact

    def add_provenance(self, fact_id: str, obs: Observation, relation: str) -> None:
        """记录某条观察和某条事实之间的证据关系。

        relation 通常是 support 或 contradict，表示该观察支持还是反驳该事实。
        """

        self.provenance[fact_id].append(
            {
                "fact_id": fact_id,
                "obs_id": obs.obs_id,
                "relation": relation,
                "event_time": obs.event_time,
                "arrival_time": obs.arrival_time,
                "confidence": obs.confidence,
            }
        )

    def export_facts(self) -> pd.DataFrame:
        """将所有 Fact 导出为 pandas 表格。"""

        return pd.DataFrame([asdict(fact) for fact in self.facts.values()])

    def export_observations(self) -> pd.DataFrame:
        """将所有 Observation 导出为 pandas 表格。"""

        return pd.DataFrame([asdict(obs) for obs in self.observations.values()])

    def export_provenance(self) -> pd.DataFrame:
        """将所有事实的证据流水摊平成一张 pandas 表格。"""

        rows = [row for rows in self.provenance.values() for row in rows]
        return pd.DataFrame(rows)
