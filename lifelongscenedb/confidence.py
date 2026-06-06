from __future__ import annotations


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """把数值限制在 [low, high] 范围内，默认用于保证置信度落在 [0, 1]。"""

    return max(low, min(high, value))


def support_update(p_old: float, c_obs: float) -> float:
    """支持证据融合：新观察支持旧事实时，提高旧事实置信度。"""

    return clamp(1 - (1 - p_old) * (1 - c_obs))


def conflict_decay(p_old: float, c_obs: float, gamma: float = 0.7) -> float:
    """冲突证据衰减：新观察反驳旧事实时，降低旧事实置信度。"""

    return clamp(p_old * (1 - gamma * c_obs))


def time_decay(p: float, delta_t: float, half_life: float = 100.0) -> float:
    """时间衰减：经过 delta_t 时间后，按 half_life 半衰期降低置信度。"""

    if half_life <= 0:
        raise ValueError("half_life must be positive")
    return clamp(p * 0.5 ** (delta_t / half_life))
