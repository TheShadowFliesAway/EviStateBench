"""EviStateBench v0 的 query / answer 数据结构。

这个模块只定义 benchmark 查询负载的输入和输出形状，不实现查询执行逻辑。

设计上先把 CHECK / AS_OF / DIFF / WHY / GOAL 这些任务状态问题表达清楚，
后续 ground-truth answer generator、baseline 和 EviStateDB reference baseline engine
都应该围绕这些 public query / answer schema 来实现。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypeAlias

from evistatebench.schema import ObservedValue, PREDICATE_CATEGORY_V0


# query_type 表示 benchmark 要问哪一类问题。
# v0 先实现最核心的 5 类，后续再扩展 PRECONDITION / UNCERTAIN / FAILURE。
QueryType: TypeAlias = Literal[
    "CHECK_STATE",
    "AS_OF_STATE",
    "STATE_DIFF",
    "WHY_STATE",
    "CHECK_GOAL",
]

# status 不是状态值本身，而是系统对这个答案的认知状态。
# known: 有足够证据给出稳定判断。
# unknown: 没有足够 observation 支撑判断。
# uncertain: 证据不足或置信度较低，答案可用但不稳。
# conflict: support / contradict 证据明显冲突，需要上层重新观察或仲裁。
QueryStatus: TypeAlias = Literal["known", "unknown", "uncertain", "conflict"]

# STATE_DIFF 需要一个范围。v0 先保留抽象 scope，不急着绑定到具体索引实现。
DiffScope: TypeAlias = Literal[
    "target_state",
    "target_state_set",
    "task",
    "room",
    "object_set",
    "predicate_category",
]

# valid_interval / transaction_interval 都用这个结构。
# end=None 表示这个区间目前仍然开放，比如状态从 t=10 开始一直有效到当前。
TimeInterval: TypeAlias = tuple[float, float | None]

# answer 里的 value 允许为 None，用来表达 unknown。
AnswerValue: TypeAlias = ObservedValue | None


def _require_non_empty(value: str, field_name: str) -> None:
    """校验必须存在的字符串字段。"""
    if not value:
        raise ValueError(f"{field_name} must be non-empty")


def _normalize_str_tuple(values: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    """把 list/tuple 统一成 tuple，方便后续作为稳定 key 使用。"""
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


def _validate_interval(interval: TimeInterval | None, field_name: str) -> None:
    """校验时间区间；开放区间 end=None 是合法的。"""
    if interval is None:
        return
    start, end = interval
    if end is not None and end < start:
        raise ValueError(f"{field_name} end must be greater than or equal to start")


@dataclass(frozen=True, slots=True)
class StateInstance:
    """一个具体的任务状态实例。

    它对应 query_templates_v0.md 里的：

    ```text
    predicate_name
    arguments
    ```

    例子：

    ```text
    open(cabinet_1)                  -> predicate_name="open", arguments=("cabinet_1",)
    inside(cup_1, cabinet_1)         -> predicate_name="inside", arguments=("cup_1", "cabinet_1")
    covered(table_1, dust_1)         -> predicate_name="covered", arguments=("table_1", "dust_1")
    ```

    这里不再写 subject/object/location，是因为 EviStateBench v0 需要同时支持
    unary、binary、material relation 和未来的 numeric/categorical state。
    """

    predicate_name: str
    arguments: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.predicate_name, "predicate_name")
        object.__setattr__(
            self,
            "arguments",
            _normalize_str_tuple(self.arguments, "arguments"),
        )

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        """这个 key 用来标识“同一个状态实例”。"""
        return (self.predicate_name, self.arguments)

    @property
    def predicate_category(self) -> str:
        """返回这个 state 所属的 v0 predicate taxonomy 类别。"""
        return PREDICATE_CATEGORY_V0.get(self.predicate_name, "unknown")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便写 JSON/report。"""
        return {
            "predicate_name": self.predicate_name,
            "arguments": list(self.arguments),
            "predicate_category": self.predicate_category,
        }


@dataclass(frozen=True, slots=True)
class StateQuery:
    """CHECK_STATE query：问某个状态在某个 valid_time 是否成立。

    机器人任务含义：
    当前杯子是否在柜子里？工具是否仍然 covered by dirt？柜门是否 open？
    """

    query_id: str
    episode_id: str
    task_id: str
    state: StateInstance
    valid_time: float
    metadata: dict[str, Any] = field(default_factory=dict)

    query_type: QueryType = field(default="CHECK_STATE", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.task_id, "task_id")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 query set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AsOfStateQuery:
    """AS_OF_STATE query：问某个系统版本当时对历史状态的判断。

    这个 query 同时指定：

    ```text
    valid_time: 世界里状态发生/成立的时间
    transaction_time: 系统收到并维护到哪个 observation 版本的时间
    ```

    它是 late arrival / out-of-order repair 的核心评测接口。
    """

    query_id: str
    episode_id: str
    task_id: str
    state: StateInstance
    valid_time: float
    transaction_time: float
    metadata: dict[str, Any] = field(default_factory=dict)

    query_type: QueryType = field(default="AS_OF_STATE", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.task_id, "task_id")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 query set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StateDiffQuery:
    """STATE_DIFF query：问两个 valid_time 之间哪些任务状态发生变化。

    机器人任务含义：
    动作执行前后场景变了什么？失败前后哪些状态偏离目标？恢复任务时要修正哪些状态？
    """

    query_id: str
    episode_id: str
    task_id: str
    scope: DiffScope
    t1: float
    t2: float
    predicate_filter: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    query_type: QueryType = field(default="STATE_DIFF", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.task_id, "task_id")
        if self.t2 < self.t1:
            raise ValueError("t2 must be greater than or equal to t1")
        object.__setattr__(self, "predicate_filter", tuple(self.predicate_filter))

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 query set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WhyStateQuery:
    """WHY_STATE query：问系统为什么相信某个状态判断。

    它不是自然语言解释任务，而是 provenance query：
    返回 support / contradict observations、evidence_refs、confidence_trace 和 revision_history。
    """

    query_id: str
    episode_id: str
    task_id: str
    state: StateInstance
    valid_time: float
    transaction_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    query_type: QueryType = field(default="WHY_STATE", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.task_id, "task_id")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 query set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GoalQuery:
    """CHECK_GOAL query：问某个任务在某个时间是否已经满足目标条件。

    它不是单个 predicate query，而是 task-derived view query。
    后续需要从 BDDL goal condition 或更一般的 task spec 生成 goal predicates。
    """

    query_id: str
    episode_id: str
    task_id: str
    valid_time: float
    transaction_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    query_type: QueryType = field(default="CHECK_GOAL", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.task_id, "task_id")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 query set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StateAnswer:
    """CHECK_STATE / AS_OF_STATE 的标准答案结构。

    value 是系统维护出的状态值；confidence 是融合多条 observation 后的状态置信度；
    status 描述这个答案是否稳定、未知、不确定或冲突。
    """

    query_id: str
    state: StateInstance
    value: AnswerValue
    confidence: float
    status: QueryStatus
    valid_interval: TimeInterval | None = None
    transaction_time: float | None = None
    transaction_interval: TimeInterval | None = None
    state_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _validate_confidence(self.confidence)
        _validate_interval(self.valid_interval, "valid_interval")
        _validate_interval(self.transaction_interval, "transaction_interval")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 answer set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StateChange:
    """STATE_DIFF 中的一条状态变化记录。

    它记录同一个 state 在 t1 和 t2 的 value / confidence 对比，
    同时保留相关 support / contradict evidence id，方便后续评估 evidence correctness。
    """

    state: StateInstance
    value_at_t1: AnswerValue
    value_at_t2: AnswerValue
    confidence_at_t1: float
    confidence_at_t2: float
    support_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    contradict_observation_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence_at_t1, "confidence_at_t1")
        _validate_confidence(self.confidence_at_t2, "confidence_at_t2")
        object.__setattr__(
            self,
            "support_observation_ids",
            tuple(self.support_observation_ids),
        )
        object.__setattr__(
            self,
            "contradict_observation_ids",
            tuple(self.contradict_observation_ids),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 answer set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StateDiffAnswer:
    """STATE_DIFF 的答案结构。

    changed_states: t1 和 t2 都存在，但 value 发生变化的状态。
    added_states: t1 不存在或 unknown，t2 出现的状态。
    removed_states: t1 存在，t2 不再成立或消失的状态。
    unchanged_but_uncertain_states: value 没变，但证据质量不足或存在冲突的状态。
    """

    query_id: str
    changed_states: tuple[StateChange, ...] = field(default_factory=tuple)
    added_states: tuple[StateChange, ...] = field(default_factory=tuple)
    removed_states: tuple[StateChange, ...] = field(default_factory=tuple)
    unchanged_but_uncertain_states: tuple[StateChange, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        object.__setattr__(self, "changed_states", tuple(self.changed_states))
        object.__setattr__(self, "added_states", tuple(self.added_states))
        object.__setattr__(self, "removed_states", tuple(self.removed_states))
        object.__setattr__(
            self,
            "unchanged_but_uncertain_states",
            tuple(self.unchanged_but_uncertain_states),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 answer set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WhyStateAnswer:
    """WHY_STATE 的答案结构。

    这里重点不是生成解释文本，而是把系统判断背后的证据链交出来。
    confidence_trace 和 revision_history 暂时保留为 dict 列表，是因为具体字段要等
    EviStateDB 内部 TemporalStateView 和 repair 语义确定后再收紧。
    """

    query_id: str
    state: StateInstance
    value: AnswerValue
    confidence: float
    status: QueryStatus
    support_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    contradict_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    confidence_trace: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    revision_history: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _validate_confidence(self.confidence)
        object.__setattr__(self, "support_observation_ids", tuple(self.support_observation_ids))
        object.__setattr__(self, "contradict_observation_ids", tuple(self.contradict_observation_ids))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "confidence_trace", tuple(self.confidence_trace))
        object.__setattr__(self, "revision_history", tuple(self.revision_history))

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 answer set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GoalPredicateResult:
    """CHECK_GOAL 中某个 goal predicate 的局部判断。

    一个任务目标通常由多个 state predicate 组成。
    这个结构用于说明每个 goal predicate 是否满足、置信度多少、证据状态如何。
    """

    state: StateInstance
    required_value: AnswerValue = True
    value: AnswerValue = None
    confidence: float = 0.0
    status: QueryStatus = "unknown"
    support_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    contradict_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)
        object.__setattr__(self, "support_observation_ids", tuple(self.support_observation_ids))
        object.__setattr__(self, "contradict_observation_ids", tuple(self.contradict_observation_ids))

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 answer set 落盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GoalAnswer:
    """CHECK_GOAL 的答案结构。

    satisfied 是整个任务目标的判断；下面三个 predicate 列表说明这个整体判断从何而来：
    哪些 goal predicate 已满足、哪些违反、哪些由于缺失/冲突/低置信度而不确定。
    """

    query_id: str
    satisfied: bool | None
    confidence: float
    status: QueryStatus
    satisfied_predicates: tuple[GoalPredicateResult, ...] = field(default_factory=tuple)
    violated_predicates: tuple[GoalPredicateResult, ...] = field(default_factory=tuple)
    uncertain_predicates: tuple[GoalPredicateResult, ...] = field(default_factory=tuple)
    supporting_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    contradicting_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.query_id, "query_id")
        _validate_confidence(self.confidence)
        object.__setattr__(self, "satisfied_predicates", tuple(self.satisfied_predicates))
        object.__setattr__(self, "violated_predicates", tuple(self.violated_predicates))
        object.__setattr__(self, "uncertain_predicates", tuple(self.uncertain_predicates))
        object.__setattr__(self, "supporting_observation_ids", tuple(self.supporting_observation_ids))
        object.__setattr__(self, "contradicting_observation_ids", tuple(self.contradicting_observation_ids))

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便 answer set 落盘。"""
        return asdict(self)


Query: TypeAlias = StateQuery | AsOfStateQuery | StateDiffQuery | WhyStateQuery | GoalQuery
QueryAnswer: TypeAlias = StateAnswer | StateDiffAnswer | WhyStateAnswer | GoalAnswer


__all__ = [
    "AnswerValue",
    "AsOfStateQuery",
    "DiffScope",
    "GoalAnswer",
    "GoalPredicateResult",
    "GoalQuery",
    "Query",
    "QueryAnswer",
    "QueryStatus",
    "QueryType",
    "StateAnswer",
    "StateChange",
    "StateDiffAnswer",
    "StateDiffQuery",
    "StateInstance",
    "StateQuery",
    "TimeInterval",
    "WhyStateAnswer",
    "WhyStateQuery",
]
