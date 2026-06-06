from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Observation:
    """外部感知系统输入的一条原始观察。

    Observation 通常来自检测器、机器人、仿真器或 VLM，表示某个时间点看到的
    一个场景断言，例如“cup_1 in table_1”。它是写入数据库前的证据，
    后续会被 SceneUpdater 融合成一个或多个 Fact。
    """

    # 观察唯一 ID。
    obs_id: str
    # 观察对应的真实场景时间：这件事在场景中被看见/发生的时间。
    # 例如机器人 8.05 看到 cup_1 在 table_1，则 event_time=8.05。
    event_time: float
    # 系统收到这条观察的时间；可能晚于 event_time，用于模拟感知/网络/处理延迟。
    # 例如 8.05 发生的观察到 8.20 才进入数据库，则 arrival_time=8.20。
    arrival_time: float
    # 产生该观察的机器人、agent 或传感器 ID。
    agent_id: str
    # 观察发生的房间或区域。
    room: str
    # 被观察的实体，例如 cup_1。
    subject: str
    # 关系谓词，例如 in。
    predicate: str
    # 关系对象，例如 table_1 或 sink_1。
    object: str
    # 定位查询使用的位置字段，通常与 object 相同。
    location: str
    # 该观察自身的置信度，范围通常为 0 到 1。
    confidence: float
    # 对应的图像帧、视频帧或感知记录 ID，用于证据溯源。
    frame_id: str
    # 观察来源，例如 detector、vlm 或 simulator。
    source: str = "detector"
    # 是否为合成数据中标记的噪声观察。
    is_noisy: bool = False
    # 额外元数据，保留给实验或真实感知系统扩展。
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Fact:
    """数据库中维护的一条场景事实。

    Fact 由 Observation 融合得到，表示系统当前或历史上相信过的一个断言，
    例如“cup_1 in sink_1”。它同时记录 valid time 和 transaction time：
    valid_* 表示事实在真实场景时间中何时成立，tx_* 表示系统何时接收并写入该事实。
    """

    fact_id: str
    # 被描述的实体，例如 cup_1。
    subject: str
    # 关系谓词，例如 in。
    predicate: str
    # 关系对象，例如 table_1 或 sink_1。
    object: str
    # 查询定位时使用的位置字段，通常与 object 相同。
    location: str
    # valid time 起点：该事实在场景时间中从何时开始成立。
    valid_start: float
    # valid time 终点：None 表示尚未被后续事实终止。
    valid_end: float | None
    # transaction time 起点：系统在何时接收到证据并写入该事实。
    tx_start: float
    # transaction time 终点：系统在何时将该事实关闭或标记为被反驳。
    tx_end: float | None
    # 当前融合后的事实置信度。
    confidence: float
    # 事实状态，例如 active 或 contradicted。
    status: str
    # 所属房间或区域，用于区域过滤和变化检测。
    room: str = ""
    # 支持该事实的观察 ID 列表。
    supporting_obs_ids: list[str] = field(default_factory=list)
    # 与该事实冲突的观察 ID 列表。
    contradicting_obs_ids: list[str] = field(default_factory=list)
    # 最近一次被支持或冲突观察更新的 arrival_time。
    last_updated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryResult:
    object_id: str
    location: str
    confidence: float
    time: float | None
    evidence: list[str]
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
