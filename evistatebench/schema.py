"""EviStateBench v0 的数据结构定义。

这个模块只放 public benchmark input schema，不写数据库维护逻辑。
这里的核心目标是先把“原始具身观察流”表达清楚。

EviStateBench 会把 StateObservation stream 提供给任意被测系统。
被测系统内部可以使用任何方法；只有 EviStateDB reference baseline engine
会选择把 observation 维护成 TemporalStateView。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypeAlias


# StateObservation 面向 public benchmark input，所以 observed_value 必须是
# JSON-compatible。v0 synthetic pipeline 主要用 bool；真实 BEHAVIOR / OmniGibson
# 数据还会出现 pose、velocity、joint state 这类 list/dict measurement。
JSONScalar: TypeAlias = bool | int | float | str | None
ObservedValue: TypeAlias = JSONScalar | list[Any] | dict[str, Any]

# observation_kind 描述这条 observation 是哪种“证据形态”。
# predicate_state: inside(cup, cabinet)=True 这类任务谓词状态。
# object_existence / object_pose / object_velocity / joint_state / robot_pose:
# simulator snapshot 或 perception pipeline 直接给出的测量证据。
# numeric_state / categorical_state: temperature、detector category 等值状态。
# simulator_diagnostic: 暂时保留的内部诊断证据，不一定直接参与任务指标。
ObservationKind: TypeAlias = str

# polarity 描述这条 observation 在维护引擎里的作用。
# 它和 observed_value 不是一回事：
# observed_value=False 也可以是 support，因为它支持的是“该状态为假”的声明。
ObservationPolarity: TypeAlias = Literal["support", "contradict", "correction"]


# 这些 predicate 集合来自 reports/task_space_v0.md。
# 放在代码里，是为了后续 generator / validator / query 模块能共用同一套 v0 边界。
CORE_STATE_PREDICATES_V0 = frozenset(
    {
        # Containment / content relation.
        "inside",
        "contains",
        # Placement / spatial relation.
        "ontop",
        "nextto",
        "under",
        "overlaid",
        # Material / particle state.
        "covered",
        "filled",
        "saturated",
        # Object unary state.
        "cooked",
        "frozen",
        "open",
        "folded",
        "unfolded",
        "toggled_on",
        "hot",
        "on_fire",
        "broken",
        # Contact / configuration relation.
        "attached",
        "draped",
        "touching",
    }
)

# 这些 predicate 对任务上下文或 BDDL 生成有用，但 v0 不把它们作为主查询和主指标对象。
CONTEXT_PREDICATES_V0 = frozenset({"inroom", "real", "future", "insource"})

# 这些状态对机器人任务很重要，但它们需要 runtime 证据，比如 action log、
# robot state 或 simulator sensor。仅靠 BDDL init/goal 统计目前拿不到。
RUNTIME_EXTENSION_PREDICATES_V0 = frozenset({"grasped"})

# 真实数据接入时出现的 observation-level / measurement-level predicates。
# 它们不一定都是 BDDL goal predicate，但可以作为维护 task-state view 的证据。
OBSERVATION_EXTENSION_PREDICATES_V0 = frozenset(
    {
        "object_exists",
        "object_pose",
        "object_velocity",
        "joint_state",
        "robot_pose",
        "temperature",
        "max_temperature",
        "slicer_active",
    }
)

PREDICATE_CATEGORY_V0: dict[str, str] = {
    # Context / bookkeeping.
    "future": "BDDL bookkeeping/source marker",
    "insource": "BDDL bookkeeping/source marker",
    "real": "BDDL bookkeeping/source marker",
    "inroom": "scene/localization context",
    # Contact / configuration relation.
    "attached": "contact/configuration relation",
    "draped": "contact/configuration relation",
    "touching": "contact/configuration relation",
    # Containment / content relation.
    "contains": "containment/content relation",
    "inside": "containment/content relation",
    # Material / particle state.
    "covered": "material/particle state",
    "filled": "material/particle state",
    "saturated": "material/particle state",
    # Object unary state.
    "broken": "object unary state",
    "cooked": "object unary state",
    "folded": "object unary state",
    "frozen": "object unary state",
    "hot": "object unary state",
    "on_fire": "object unary state",
    "open": "object unary state",
    "toggled_on": "object unary state",
    "unfolded": "object unary state",
    # Placement / spatial relation.
    "nextto": "placement/spatial relation",
    "ontop": "placement/spatial relation",
    "overlaid": "placement/spatial relation",
    "under": "placement/spatial relation",
    # Runtime extension.
    "grasped": "runtime robot interaction",
    # Observation / measurement extension.
    "object_exists": "object existence evidence",
    "object_pose": "object pose measurement",
    "object_velocity": "object velocity measurement",
    "joint_state": "joint state measurement",
    "robot_pose": "robot pose measurement",
    "temperature": "numeric object state",
    "max_temperature": "numeric simulator/object diagnostic",
    "slicer_active": "tool/action state",
}


def is_json_value(value: Any) -> bool:
    """Return whether value can safely live in a JSON benchmark artifact."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


@dataclass(frozen=True, slots=True)
class StateObservation:
    """从具身观察源中抽取出的一条原始状态声明。

    注意：StateObservation 是证据，不是最终状态。

    EviStateDB reference baseline engine 会把具有相同 state_key 的多条 observation 聚合起来，
    维护成 TemporalStateView。TemporalStateView 才会包含 valid-time interval、
    transaction-time repair、融合后的 confidence、support evidence、
    contradict evidence 和 revision history。

    Example:
        StateObservation(
            obs_id="obs_001",
            episode_id="ep_clean_001",
            task_id="cleaning_garden_tools",
            event_time=12.4,
            arrival_time=15.9,
            source="simulator_state",
            observation_kind="predicate_state",
            predicate_name="covered",
            arguments=("shovel_1", "dirt_1"),
            observed_value=False,
            confidence=0.98,
            evidence_ref="sim_state_t12.4",
            metadata={"predicate_category": "material/particle state"},
        )
    """

    # 这条证据的唯一 id。WHY_STATE 返回证据时，需要能指回这条 observation。
    obs_id: str

    # observation 所属的 episode，可以理解成一次轨迹、一次仿真 rollout、
    # 或一段真实视频。评估和 ground truth 通常都是 episode-scoped。
    episode_id: str

    # observation 所属的任务，比如 BEHAVIOR/BDDL task: "cleaning_garden_tools"。
    task_id: str

    # event_time 表示这条状态证据对应的真实发生时间/观察时间。
    # 后续做 valid-time reasoning 时用的是这个时间。
    event_time: float

    # arrival_time 表示系统收到这条 observation 的时间。
    # detector / VLM / action log 可能延迟输出，所以 arrival_time 可以晚于 event_time。
    # 不同 observation 也可能乱序到达，这是 EviStateBench 要评测的核心情况之一。
    arrival_time: float

    # source 表示 observation 的来源，例如：
    # simulator_state, rgb_detector, depth_relation_model, vlm_caption,
    # object_tracker, action_log, human_annotation, robot_state。
    source: str

    # 这条 observation 声明的是哪个 predicate。
    # 不再使用 subject/object/location，是因为 v0 需要同时支持：
    #   open(cabinet)                 unary
    #   inside(cup, cabinet)          binary
    #   covered(table, dust)          material relation
    #   temperature(food) = 80.0      future numeric extension
    predicate_name: str

    # predicate 的有序参数。例如：
    #   ("cabinet_1",) for open(cabinet_1)
    #   ("cup_1", "cabinet_1") for inside(cup_1, cabinet_1)
    arguments: tuple[str, ...]

    # 观察到的 predicate value。v0 主要是 bool。
    # 但这里保留 numeric/categorical/list/dict，是为了后续扩展：
    #   temperature(object)
    #   pose(object)
    #   distance(object_a, object_b)
    observed_value: ObservedValue

    # observation 级别的置信度，范围是 [0, 1]。
    # 它只是这条证据自身的强度，不是多条证据融合后的最终状态置信度。
    confidence: float

    # observation_kind 区分“任务谓词状态”和“原始测量证据”。
    # 例如：
    #   predicate_state + inside(cup, cabinet)=True
    #   object_pose + object_pose(cup)={pos, ori}
    #   numeric_state + temperature(food)=80.0
    # 这样 predicate_name 仍然保留统一 state_key 语义，但不会把 pose
    # 误认为 BDDL boolean predicate。
    observation_kind: ObservationKind = "predicate_state"

    # 指向原始证据的位置。WHY_STATE 最终应该返回这些 evidence_ref。
    # 例如 frame id、trajectory step、simulator state id、detector output id、
    # action log id、annotation id 等。
    evidence_ref: str | None = None

    # polarity 是 generator 或维护引擎用的辅助语义。
    # v0 里大多数 observation 都是 support，表示支持 observed_value 这条声明。
    # contradict / correction 主要用于构造冲突证据和 late repair workload。
    # 注意：表达一个状态为假，不一定要用 contradict；observed_value=False 就可以表达。
    polarity: ObservationPolarity = "support"

    # 扩展字段。不要过早把所有东西都顶层化。
    # BDDL category、object synsets、room/scope、注入的 noise type、
    # detector score、action name、frame range 等，都可以先放在 metadata 里。
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """只做字段级别校验，不做任何状态维护。"""
        if not self.obs_id:
            raise ValueError("obs_id must be non-empty")
        if not self.episode_id:
            raise ValueError("episode_id must be non-empty")
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.source:
            raise ValueError("source must be non-empty")
        if not self.observation_kind:
            raise ValueError("observation_kind must be non-empty")
        if not self.predicate_name:
            raise ValueError("predicate_name must be non-empty")

        # JSON/YAML 读出来的 arguments 可能是 list。
        # 这里统一转成 tuple，让 state_key 稳定，也更适合做 dict key。
        object.__setattr__(self, "arguments", tuple(self.arguments))
        if not self.arguments:
            raise ValueError("arguments must contain at least one argument")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if not is_json_value(self.observed_value):
            raise ValueError("observed_value must be JSON-compatible")
        if not is_json_value(self.metadata):
            raise ValueError("metadata must be JSON-compatible")

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        """返回这条 observation 指向的状态实例。

        例如所有 inside(cup_1, cabinet_1) 的 observation 都会有相同的 state_key。
        EviStateDB 维护引擎会把这些 observation 作为同一个 TemporalStateView 的候选证据。
        """
        return (self.predicate_name, self.arguments)

    @property
    def predicate_category(self) -> str:
        """返回这个 predicate 在 v0 taxonomy 里的类别。"""
        return PREDICATE_CATEGORY_V0.get(self.predicate_name, "unknown")

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，方便写 JSON/CSV/report。"""
        data = asdict(self)
        data["arguments"] = list(self.arguments)
        data["predicate_category"] = self.predicate_category
        return data
