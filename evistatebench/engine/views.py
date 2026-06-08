"""EviStateDB reference baseline engine 的 TemporalStateView 数据结构。

这个模块属于 reference baseline / internal engine layer，不属于
EviStateBench 的 public benchmark interface。

```text
StateObservation stream
        ↓
EviStateDB internal TemporalStateView
        ↓
predicted QueryAnswers
```

这里仍然只定义 schema，不实现 observation fusion、repair 或查询执行算法。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypeAlias

from evistatebench.schema import ObservedValue, PREDICATE_CATEGORY_V0, StateObservation


# TemporalStateView 对一个状态判断的认知状态。
# known: 当前证据足够稳定。
# unknown: 没有足够证据形成判断。
# uncertain: 有判断，但置信度低或证据稀疏。
# conflict: support / contradict 证据冲突明显。
ViewStatus: TypeAlias = Literal["known", "unknown", "uncertain", "conflict"]

# evidence 在当前 view 中扮演的角色。
# support: 支持 view.value。
# contradict: 反驳 view.value。
# correction: 迟到证据或修正证据，可能触发 transaction-time repair。
EvidenceRole: TypeAlias = Literal["support", "contradict", "correction"]

# valid_interval / transaction_interval 的统一表示。
# end=None 表示开放区间。
ViewTimeInterval: TypeAlias = tuple[float, float | None]

# view.value 允许为 None，用来表示系统尚未形成状态判断。
ViewValue: TypeAlias = ObservedValue | None


def _require_non_empty(value: str, field_name: str) -> None:
    """校验必须存在的字符串字段。"""
    if not value:
        raise ValueError(f"{field_name} must be non-empty")


def _normalize_str_tuple(values: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    """把 list/tuple 统一成 tuple，方便作为稳定 state key 使用。"""
    normalized = tuple(values)
    if not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    if any(not value for value in normalized):
        raise ValueError(f"{field_name} cannot contain empty values")
    return normalized


def _validate_confidence(value: float, field_name: str = "confidence") -> None:
    """confidence 在整个项目里统一约定为 [0, 1]。"""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be within [0, 1]")


def _validate_interval(start: float, end: float | None, field_name: str) -> None:
    """校验时间区间；开放区间 end=None 是合法的。"""
    if end is not None and end < start:
        raise ValueError(f"{field_name} end must be greater than or equal to start")


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """TemporalStateView 里保留的一条 observation 证据链接。

    它不是完整复制 observation，而是保留 WHY_STATE 和证据正确性评估最需要的信息：
    observation id、来源、时间、置信度、原始 evidence_ref，以及它在当前 view 中的角色。
    """

    # 对应 StateObservation.obs_id。WHY_STATE 最终要能回到原始 observation。
    obs_id: str

    # 这条证据支持、反驳，还是修正当前 view。
    role: EvidenceRole

    # observation 原本声称的 value。它可能和 view.value 相同，也可能相反。
    observed_value: ObservedValue

    # 单条 observation 自身的置信度，不是 view 融合后的置信度。
    confidence: float

    # observation 对应的真实事件时间。
    event_time: float

    # 系统收到 observation 的时间。
    arrival_time: float

    # observation 的来源，例如 simulator_state / rgb_detector / vlm_caption。
    source: str

    # 指向 frame、sim state、detector output、action log 等原始证据。
    evidence_ref: str | None = None

    # 证据级扩展字段，比如 noise type、detector score、frame range。
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.obs_id, "obs_id")
        _require_non_empty(self.source, "source")
        _validate_confidence(self.confidence)

    @classmethod
    def from_observation(
        cls,
        observation: StateObservation,
        role: EvidenceRole | None = None,
    ) -> "EvidenceLink":
        """从 StateObservation 生成 EvidenceLink。

        这只是结构转换，不做证据融合。
        如果调用方不显式指定 role，就沿用 observation.polarity。
        """
        return cls(
            obs_id=observation.obs_id,
            role=role or observation.polarity,
            observed_value=observation.observed_value,
            confidence=observation.confidence,
            event_time=observation.event_time,
            arrival_time=observation.arrival_time,
            source=observation.source,
            evidence_ref=observation.evidence_ref,
            metadata=dict(observation.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便写 JSON/report。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConfidenceStep:
    """view confidence 的一次变化记录。

    WHY_STATE 需要解释“置信度怎么来的”。这个结构用来记录：
    哪条 observation 在哪个 transaction_time 把 confidence 从多少更新到多少。
    """

    transaction_time: float
    obs_id: str
    role: EvidenceRole
    previous_confidence: float
    new_confidence: float
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.obs_id, "obs_id")
        _validate_confidence(self.previous_confidence, "previous_confidence")
        _validate_confidence(self.new_confidence, "new_confidence")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便写 JSON/report。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ViewRevision:
    """TemporalStateView 的一次版本修订记录。

    它服务 AS_OF_STATE 和 late-arrival repair：
    当迟到 observation 改写了历史状态时，旧 view 版本会在 transaction time 上关闭，
    新 view 版本会记录这次 revision。
    """

    revision_id: str
    transaction_time: float
    reason: str
    changed_by_obs_id: str | None = None
    previous_value: ViewValue = None
    new_value: ViewValue = None
    previous_confidence: float | None = None
    new_confidence: float | None = None
    previous_valid_interval: ViewTimeInterval | None = None
    new_valid_interval: ViewTimeInterval | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.revision_id, "revision_id")
        _require_non_empty(self.reason, "reason")
        if self.changed_by_obs_id is not None:
            _require_non_empty(self.changed_by_obs_id, "changed_by_obs_id")
        if self.previous_confidence is not None:
            _validate_confidence(self.previous_confidence, "previous_confidence")
        if self.new_confidence is not None:
            _validate_confidence(self.new_confidence, "new_confidence")
        if self.previous_valid_interval is not None:
            _validate_interval(*self.previous_valid_interval, "previous_valid_interval")
        if self.new_valid_interval is not None:
            _validate_interval(*self.new_valid_interval, "new_valid_interval")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便写 JSON/report。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TemporalStateView:
    """从 observation stream 维护出来的一段时态任务状态视图。

    这是真正连接输入层和查询层的中间对象：

    ```text
    多条 StateObservation
        -> 同一个 state_key
        -> 一个或多个 TemporalStateView 版本
        -> StateAnswer / WhyStateAnswer / StateDiffAnswer / GoalAnswer
    ```

    一个 TemporalStateView 表达的是：

    ```text
    在 valid time 的某段区间里，
    系统在 transaction time 的某个版本下，
    相信 predicate(arguments) = value，
    置信度为 confidence，
    并且这个判断由哪些证据支持或反驳。
    ```
    """

    # 这个 view 版本的唯一 id。
    view_id: str

    # view 所属 episode。benchmark evaluation 通常按 episode 切分。
    episode_id: str

    # view 所属任务。CHECK_GOAL / task family / query generation 会用到。
    task_id: str

    # 被维护的是哪个 predicate。
    predicate_name: str

    # predicate 的有序参数，例如 ("cup_1", "cabinet_1")。
    arguments: tuple[str, ...]

    # 维护后的状态值。None 表示系统还没有形成判断。
    value: ViewValue

    # 融合后的 view-level confidence，不是单条 observation 的 confidence。
    confidence: float

    # 当前 view 的认知状态：known / unknown / uncertain / conflict。
    status: ViewStatus

    # valid_start / valid_end 是世界时间：
    # 这个状态判断在真实任务时间里的有效区间。
    valid_start: float
    valid_end: float | None

    # transaction_start / transaction_end 是系统版本时间：
    # 这个 view 版本从系统什么时候开始生效，到什么时候被后续修订关闭。
    transaction_start: float
    transaction_end: float | None

    # 支持当前 value 的 observation 证据。
    support_evidence: tuple[EvidenceLink, ...] = field(default_factory=tuple)

    # 反驳当前 value 的 observation 证据。
    contradict_evidence: tuple[EvidenceLink, ...] = field(default_factory=tuple)

    # confidence 的变化轨迹，主要服务 WHY_STATE。
    confidence_trace: tuple[ConfidenceStep, ...] = field(default_factory=tuple)

    # view 版本的修订历史，主要服务 AS_OF_STATE 和 late repair 分析。
    revision_history: tuple[ViewRevision, ...] = field(default_factory=tuple)

    # view 级扩展字段。比如 task family、room、object synset、维护策略、noise regime。
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.view_id, "view_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.task_id, "task_id")
        _require_non_empty(self.predicate_name, "predicate_name")

        object.__setattr__(
            self,
            "arguments",
            _normalize_str_tuple(self.arguments, "arguments"),
        )
        _validate_confidence(self.confidence)
        _validate_interval(self.valid_start, self.valid_end, "valid_interval")
        _validate_interval(
            self.transaction_start,
            self.transaction_end,
            "transaction_interval",
        )

        object.__setattr__(self, "support_evidence", tuple(self.support_evidence))
        object.__setattr__(self, "contradict_evidence", tuple(self.contradict_evidence))
        object.__setattr__(self, "confidence_trace", tuple(self.confidence_trace))
        object.__setattr__(self, "revision_history", tuple(self.revision_history))

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        """标识这个 view 维护的是哪个状态实例。"""
        return (self.predicate_name, self.arguments)

    @property
    def predicate_category(self) -> str:
        """返回这个 predicate 在 v0 taxonomy 里的类别。"""
        return PREDICATE_CATEGORY_V0.get(self.predicate_name, "unknown")

    @property
    def valid_interval(self) -> ViewTimeInterval:
        """返回 valid-time 区间。"""
        return (self.valid_start, self.valid_end)

    @property
    def transaction_interval(self) -> ViewTimeInterval:
        """返回 transaction-time 区间。"""
        return (self.transaction_start, self.transaction_end)

    @property
    def is_current_transaction_version(self) -> bool:
        """transaction_end=None 表示这是当前仍然开放的系统版本。"""
        return self.transaction_end is None

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便写 JSON/report。"""
        data = asdict(self)
        data["arguments"] = list(self.arguments)
        data["predicate_category"] = self.predicate_category
        data["valid_interval"] = self.valid_interval
        data["transaction_interval"] = self.transaction_interval
        data["is_current_transaction_version"] = self.is_current_transaction_version
        return data


__all__ = [
    "ConfidenceStep",
    "EvidenceLink",
    "EvidenceRole",
    "TemporalStateView",
    "ViewRevision",
    "ViewStatus",
    "ViewTimeInterval",
    "ViewValue",
]
