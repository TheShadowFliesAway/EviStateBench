from __future__ import annotations

from collections import defaultdict

from .confidence import conflict_decay, support_update
from .indexes import MemoryIndexes
from .schema import Fact, Observation
from .store import MemoryStore


def make_fact_id(obs: Observation, ordinal: int) -> str:
    return f"{obs.subject}|{obs.predicate}|{obs.object}|{obs.location}|{obs.event_time:.6f}|{ordinal}"


class SceneUpdater:
    def __init__(self, store: MemoryStore, indexes: MemoryIndexes, config: dict, use_indexes: bool = True) -> None:
        self.store = store
        self.indexes = indexes
        self.config = config
        self.use_indexes = use_indexes
        # 精确活跃事实表：(subject, predicate, object, location) -> fact_id。
        # 用于快速判断新 Observation 是否和某条 active Fact 完全一致，从而作为 support 证据。
        self.active_by_key: dict[tuple[str, str, str, str], str] = {}
        # 粗粒度活跃事实表：(subject, predicate) -> active fact_id 集合。
        # 用于找到同一实体同一关系下的其他 active facts，从而判断新 Observation 是否产生 conflict。
        self.active_by_subject_predicate: dict[tuple[str, str], set[str]] = defaultdict(set)

    @property
    def activate_threshold(self) -> float:
        return float(self.config.get("activate_threshold", 0.6))

    @property
    def expire_threshold(self) -> float:
        return float(self.config.get("expire_threshold", 0.35))

    @property
    def conflict_gamma(self) -> float:
        return float(self.config.get("conflict_gamma", 0.7))

    def ingest_many(self, observations: list[Observation]) -> None:
        for obs in sorted(observations, key=lambda o: (o.arrival_time, o.obs_id)):
            self.ingest_observation(obs)

    def ingest_observation(self, obs: Observation) -> None:
        """写入一条观察，并据此更新场景事实。

        更新顺序：
        1. 先保存原始 Observation；
        2. 如果观察与某条 active Fact 完全一致，则作为 support 证据融合；
        3. 否则查找同 subject/predicate 下 object 或 location 不同的冲突事实；
        4. 根据观察置信度和冲突情况，决定是否创建新的 active Fact。
        """

        # 无论观察最终是否形成新事实，原始观察本身都要保存下来，方便后续溯源。
        self.store.add_observation(obs)

        # 如果已有完全相同的 active fact，这条观察就是支持证据，不需要创建新 fact。
        matching = self._find_active_same_key(obs)
        if matching:
            # 支持证据会提高已有事实置信度，并把该观察加入 supporting_obs_ids。
            matching.confidence = support_update(matching.confidence, obs.confidence)
            matching.supporting_obs_ids.append(obs.obs_id)
            matching.last_updated = obs.arrival_time
            self.store.add_provenance(matching.fact_id, obs, "support")
            # Fact 内容发生了变化，需要同步更新索引中的 provenance 等信息。
            self._update_index(matching)
            return

        # 查找同一 subject/predicate 下，与新观察 object 或 location 不同的 active facts。
        conflicts = self._find_active_conflicts(obs)
        # 观察置信度达到阈值时，才认为它有足够资格推翻旧事实并激活成强候选事实。
        should_activate = obs.confidence >= self.activate_threshold
        for old in conflicts:
            # 新观察与旧事实冲突时，会降低旧事实的置信度。
            old.confidence = conflict_decay(old.confidence, obs.confidence, self.conflict_gamma)
            old.contradicting_obs_ids.append(obs.obs_id)
            old.last_updated = obs.arrival_time
            self.store.add_provenance(old.fact_id, obs, "contradict")
            # 只有高置信冲突观察才能关闭旧事实；低置信冲突只会造成衰减，不会直接推翻。
            if should_activate and old.confidence < self.expire_threshold:
                if old.valid_end is None or obs.event_time < old.valid_end:
                    old.valid_end = obs.event_time
                old.status = "contradicted"
                old.tx_end = obs.arrival_time
                self._deactivate(old)
            self._update_index(old)

        # 创建新事实的条件：
        # - 高置信观察：即使存在冲突，也创建新 active fact；
        # - 无冲突观察：即使置信度较低，也先作为 active fact 存入，用 confidence 表达不确定性。
        if should_activate or not conflicts:
            ordinal = len(self.store.facts) + 1
            fact = Fact(
                fact_id=make_fact_id(obs, ordinal),
                subject=obs.subject,
                predicate=obs.predicate,
                object=obs.object,
                location=obs.location,
                valid_start=obs.event_time,
                valid_end=None,
                tx_start=obs.arrival_time,
                tx_end=None,
                confidence=obs.confidence,
                status="active",
                room=obs.room,
                supporting_obs_ids=[obs.obs_id],
                contradicting_obs_ids=[],
                last_updated=obs.arrival_time,
            )
            self.store.add_fact(fact)
            self.store.add_provenance(fact.fact_id, obs, "support")
            self._activate(fact)
            self._update_index(fact)

    def _find_active_same_key(self, obs: Observation) -> Fact | None:
        """查找与观察完全一致的 active Fact。

        如果找到，说明该观察支持已有事实，而不是创建新事实。
        """

        fact_id = self.active_by_key.get((obs.subject, obs.predicate, obs.object, obs.location))
        if not fact_id:
            return None
        fact = self.store.facts.get(fact_id)
        if fact and fact.status == "active":
            return fact
        return None

    def _find_active_conflicts(self, obs: Observation) -> list[Fact]:
        """查找与观察冲突的 active Facts。

        冲突定义：subject 和 predicate 相同，但 object 或 location 不同。
        例如旧事实是 cup_1 in table_1，新观察是 cup_1 in sink_1。
        """

        out: list[Fact] = []
        fact_ids = self.active_by_subject_predicate.get((obs.subject, obs.predicate), set())
        for fact_id in list(fact_ids):
            fact = self.store.facts[fact_id]
            if fact.object != obs.object or fact.location != obs.location:
                out.append(fact)
        return out

    def _activate(self, fact: Fact) -> None:
        """把 Fact 注册到活跃事实表中，供后续观察快速匹配。"""

        self.active_by_key[(fact.subject, fact.predicate, fact.object, fact.location)] = fact.fact_id
        self.active_by_subject_predicate[(fact.subject, fact.predicate)].add(fact.fact_id)

    def _deactivate(self, fact: Fact) -> None:
        """把 Fact 从活跃事实表中移除，通常发生在事实被冲突观察反驳后。"""

        self.active_by_key.pop((fact.subject, fact.predicate, fact.object, fact.location), None)
        self.active_by_subject_predicate[(fact.subject, fact.predicate)].discard(fact.fact_id)

    def _update_index(self, fact: Fact) -> None:
        if self.use_indexes:
            self.indexes.update_fact(fact)
