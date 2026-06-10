#!/usr/bin/env python3
"""Build perturbed StateObservation streams from the clean stream.

This script implements Step 4 of the minimal EviStateBench pipeline:

clean StateObservation stream -> perturbed observation streams

The generated streams are benchmark inputs.  They intentionally contain delay,
out-of-order arrival, missing records, low-confidence evidence, or conflicting
evidence while keeping the hidden ground-truth timeline unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.schema import StateObservation  # noqa: E402


DEFAULT_INPUT_PATH = REPO_ROOT / "data" / "clean_state_observations_v0.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "observation_streams_v0"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "perturbed_observations_v0.md"


@dataclass(frozen=True, slots=True)
class RegimeResult:
    """Summary for one generated perturbation regime."""

    name: str
    path: Path
    observations: list[StateObservation]
    input_count: int
    dropped_count: int = 0
    conflict_added_count: int = 0
    delayed_count: int = 0
    low_confidence_count: int = 0

    @property
    def output_count(self) -> int:
        return len(self.observations)


def observation_from_dict(row: dict[str, Any]) -> StateObservation:
    """Load a StateObservation from a JSON row written by StateObservation.to_dict."""
    row = dict(row)
    row.pop("predicate_category", None)
    return StateObservation(**row)


def load_observations(path: Path) -> list[StateObservation]:
    observations: list[StateObservation] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            observations.append(observation_from_dict(json.loads(line)))
    return observations


def clean_obs_index(obs_id: str) -> str:
    """Return the trailing numeric part from a clean observation id."""
    marker = "__obs_clean_"
    if marker in obs_id:
        return obs_id.split(marker, maxsplit=1)[1]
    return obs_id.rsplit("_", maxsplit=1)[-1]


def make_obs_id(obs: StateObservation, regime: str) -> str:
    """Create a stable perturbed observation id from a clean observation id."""
    if "__obs_clean_" in obs.obs_id:
        return obs.obs_id.replace("__obs_clean_", f"__obs_{regime}_")
    return f"{obs.obs_id}__{regime}"


def make_conflict_obs_id(obs: StateObservation, regime: str, conflict_index: int) -> str:
    """Create a stable id for an injected conflicting observation."""
    base = make_obs_id(obs, regime)
    return f"{base}__conflict_{conflict_index:05d}"


def perturbation_metadata(
    obs: StateObservation,
    *,
    regime: str,
    seed: int,
    operations: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return metadata for one generated observation."""
    metadata = copy.deepcopy(obs.metadata)
    metadata["stream_variant"] = f"{regime}_v0"
    metadata["source_clean_obs_id"] = obs.obs_id
    metadata["perturbation"] = {
        "regime": regime,
        "seed": seed,
        "operations": operations,
    }
    if extra:
        metadata["perturbation"].update(extra)
    return metadata


def clone_observation(
    obs: StateObservation,
    *,
    regime: str,
    seed: int,
    operations: list[str],
    obs_id: str | None = None,
    arrival_time: float | None = None,
    confidence: float | None = None,
    observed_value: bool | int | float | str | None = None,
    source: str | None = None,
    evidence_ref: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> StateObservation:
    """Clone an observation while applying perturbation-specific field changes."""
    return StateObservation(
        obs_id=obs_id or make_obs_id(obs, regime),
        episode_id=obs.episode_id,
        task_id=obs.task_id,
        event_time=obs.event_time,
        arrival_time=obs.arrival_time if arrival_time is None else round(arrival_time, 6),
        source=obs.source if source is None else source,
        predicate_name=obs.predicate_name,
        arguments=obs.arguments,
        observed_value=obs.observed_value
        if observed_value is None
        else observed_value,
        confidence=obs.confidence if confidence is None else round(confidence, 6),
        evidence_ref=obs.evidence_ref if evidence_ref is None else evidence_ref,
        polarity="support",
        metadata=perturbation_metadata(
            obs,
            regime=regime,
            seed=seed,
            operations=operations,
            extra=extra_metadata,
        ),
    )


def with_stream_order(
    observations: list[StateObservation],
    *,
    regime: str,
    seed: int,
) -> list[StateObservation]:
    """Sort by arrival order and write stream_order into metadata."""
    sorted_observations = sorted(
        observations,
        key=lambda obs: (
            obs.episode_id,
            obs.arrival_time,
            obs.event_time,
            obs.obs_id,
        ),
    )
    ordered: list[StateObservation] = []
    for stream_order, obs in enumerate(sorted_observations, start=1):
        metadata = copy.deepcopy(obs.metadata)
        metadata["stream_order"] = stream_order
        metadata["stream_sort_key"] = "episode_id, arrival_time, event_time, obs_id"
        ordered.append(
            StateObservation(
                obs_id=obs.obs_id,
                episode_id=obs.episode_id,
                task_id=obs.task_id,
                event_time=obs.event_time,
                arrival_time=obs.arrival_time,
                source=obs.source,
                predicate_name=obs.predicate_name,
                arguments=obs.arguments,
                observed_value=obs.observed_value,
                confidence=obs.confidence,
                evidence_ref=obs.evidence_ref,
                polarity=obs.polarity,
                metadata=metadata,
            )
        )
    return ordered


def write_observations(path: Path, observations: list[StateObservation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obs in observations:
            f.write(json.dumps(obs.to_dict(), ensure_ascii=False, sort_keys=True))
            f.write("\n")


def count_out_of_order(observations: list[StateObservation]) -> int:
    """Count observations whose event_time goes backward within an episode stream."""
    last_event_time_by_episode: dict[str, float] = {}
    out_of_order = 0
    for obs in observations:
        last_time = last_event_time_by_episode.get(obs.episode_id)
        if last_time is not None and obs.event_time < last_time:
            out_of_order += 1
        last_event_time_by_episode[obs.episode_id] = obs.event_time
    return out_of_order


def delay_stats(observations: list[StateObservation]) -> tuple[float, float]:
    delays = [obs.arrival_time - obs.event_time for obs in observations]
    if not delays:
        return 0.0, 0.0
    return sum(delays) / len(delays), max(delays)


def count_delayed(observations: list[StateObservation]) -> int:
    """Count observations whose arrival_time is later than event_time."""
    return sum(obs.arrival_time > obs.event_time for obs in observations)


def build_delay_stream(
    clean: list[StateObservation],
    *,
    seed: int,
    delay_seconds: float,
) -> RegimeResult:
    regime = "delay"
    observations = [
        clone_observation(
            obs,
            regime=regime,
            seed=seed,
            operations=["constant_delay"],
            arrival_time=obs.event_time + delay_seconds,
            extra_metadata={"delay_seconds": delay_seconds},
        )
        for obs in clean
    ]
    observations = with_stream_order(observations, regime=regime, seed=seed)
    return RegimeResult(
        name=regime,
        path=Path(f"{regime}.jsonl"),
        observations=observations,
        input_count=len(clean),
        delayed_count=len(observations),
    )


def build_out_of_order_stream(
    clean: list[StateObservation],
    *,
    seed: int,
    max_delay_seconds: float,
) -> RegimeResult:
    regime = "out_of_order"
    rng = random.Random(seed)
    observations: list[StateObservation] = []
    for obs in clean:
        delay = rng.uniform(0.0, max_delay_seconds)
        observations.append(
            clone_observation(
                obs,
                regime=regime,
                seed=seed,
                operations=["random_delay"],
                arrival_time=obs.event_time + delay,
                extra_metadata={"delay_seconds": round(delay, 6)},
            )
        )
    observations = with_stream_order(observations, regime=regime, seed=seed)
    return RegimeResult(
        name=regime,
        path=Path(f"{regime}.jsonl"),
        observations=observations,
        input_count=len(clean),
        delayed_count=len(observations),
    )


def build_missing_stream(
    clean: list[StateObservation],
    *,
    seed: int,
    missing_rate: float,
) -> RegimeResult:
    regime = "missing"
    rng = random.Random(seed)
    observations: list[StateObservation] = []
    dropped = 0
    for obs in clean:
        if rng.random() < missing_rate:
            dropped += 1
            continue
        observations.append(
            clone_observation(
                obs,
                regime=regime,
                seed=seed,
                operations=["kept_after_missing_sampling"],
                extra_metadata={"missing_rate": missing_rate},
            )
        )
    observations = with_stream_order(observations, regime=regime, seed=seed)
    return RegimeResult(
        name=regime,
        path=Path(f"{regime}.jsonl"),
        observations=observations,
        input_count=len(clean),
        dropped_count=dropped,
    )


def build_low_confidence_stream(
    clean: list[StateObservation],
    *,
    seed: int,
    low_confidence_rate: float,
    low_confidence_min: float,
    low_confidence_max: float,
) -> RegimeResult:
    regime = "low_confidence"
    rng = random.Random(seed)
    observations: list[StateObservation] = []
    lowered = 0
    for obs in clean:
        if rng.random() < low_confidence_rate:
            confidence = rng.uniform(low_confidence_min, low_confidence_max)
            lowered += 1
            observations.append(
                clone_observation(
                    obs,
                    regime=regime,
                    seed=seed,
                    operations=["confidence_degraded"],
                    confidence=confidence,
                    extra_metadata={
                        "low_confidence_rate": low_confidence_rate,
                        "original_confidence": obs.confidence,
                    },
                )
            )
        else:
            observations.append(
                clone_observation(
                    obs,
                    regime=regime,
                    seed=seed,
                    operations=["confidence_unchanged"],
                    extra_metadata={"low_confidence_rate": low_confidence_rate},
                )
            )
    observations = with_stream_order(observations, regime=regime, seed=seed)
    return RegimeResult(
        name=regime,
        path=Path(f"{regime}.jsonl"),
        observations=observations,
        input_count=len(clean),
        low_confidence_count=lowered,
    )


def maybe_flip_value(value: bool | int | float | str) -> bool | int | float | str | None:
    """Return a contradictory value when v0 knows how to flip it."""
    if isinstance(value, bool):
        return not value
    return None


def build_conflict_stream(
    clean: list[StateObservation],
    *,
    seed: int,
    conflict_rate: float,
    conflict_confidence: float,
    conflict_max_delay_seconds: float,
    regime: str = "conflict",
) -> RegimeResult:
    rng = random.Random(seed)
    observations: list[StateObservation] = []
    conflict_added = 0
    for obs in clean:
        observations.append(
            clone_observation(
                obs,
                regime=regime,
                seed=seed,
                operations=["kept_original"],
                extra_metadata={"conflict_rate": conflict_rate},
            )
        )
        flipped_value = maybe_flip_value(obs.observed_value)
        if flipped_value is None or rng.random() >= conflict_rate:
            continue

        conflict_added += 1
        conflict_delay = rng.uniform(0.1, conflict_max_delay_seconds)
        observations.append(
            clone_observation(
                obs,
                regime=regime,
                seed=seed,
                operations=["conflict_flip"],
                obs_id=make_conflict_obs_id(obs, regime, conflict_added),
                arrival_time=obs.arrival_time + conflict_delay,
                confidence=conflict_confidence,
                observed_value=flipped_value,
                source="synthetic_conflict_sensor",
                evidence_ref=f"{obs.evidence_ref}__conflict_{conflict_added:05d}"
                if obs.evidence_ref
                else None,
                extra_metadata={
                    "conflict_rate": conflict_rate,
                    "conflict_delay_seconds": round(conflict_delay, 6),
                    "original_observed_value": obs.observed_value,
                    "flipped_observed_value": flipped_value,
                },
            )
        )
    observations = with_stream_order(observations, regime=regime, seed=seed)
    return RegimeResult(
        name=regime,
        path=Path(f"{regime}.jsonl"),
        observations=observations,
        input_count=len(clean),
        conflict_added_count=conflict_added,
    )


def build_mixed_stream(
    clean: list[StateObservation],
    *,
    seed: int,
    missing_rate: float,
    low_confidence_rate: float,
    low_confidence_min: float,
    low_confidence_max: float,
    conflict_rate: float,
    conflict_confidence: float,
    max_delay_seconds: float,
) -> RegimeResult:
    regime = "mixed"
    rng = random.Random(seed)
    observations: list[StateObservation] = []
    dropped = 0
    lowered = 0
    conflict_added = 0
    delayed = 0

    for obs in clean:
        if rng.random() < missing_rate:
            dropped += 1
            continue

        operations = ["kept_after_missing_sampling", "random_delay"]
        delay = rng.uniform(0.0, max_delay_seconds)
        delayed += 1
        confidence = obs.confidence
        if rng.random() < low_confidence_rate:
            confidence = rng.uniform(low_confidence_min, low_confidence_max)
            operations.append("confidence_degraded")
            lowered += 1
        else:
            operations.append("confidence_unchanged")

        base_obs = clone_observation(
            obs,
            regime=regime,
            seed=seed,
            operations=operations,
            arrival_time=obs.event_time + delay,
            confidence=confidence,
            extra_metadata={
                "missing_rate": missing_rate,
                "low_confidence_rate": low_confidence_rate,
                "delay_seconds": round(delay, 6),
            },
        )
        observations.append(base_obs)

        flipped_value = maybe_flip_value(obs.observed_value)
        if flipped_value is None or rng.random() >= conflict_rate:
            continue

        conflict_added += 1
        conflict_delay = rng.uniform(0.1, max_delay_seconds)
        observations.append(
            clone_observation(
                obs,
                regime=regime,
                seed=seed,
                operations=["conflict_flip", "random_delay"],
                obs_id=make_conflict_obs_id(obs, regime, conflict_added),
                arrival_time=obs.event_time + delay + conflict_delay,
                confidence=conflict_confidence,
                observed_value=flipped_value,
                source="synthetic_conflict_sensor",
                evidence_ref=f"{obs.evidence_ref}__mixed_conflict_{conflict_added:05d}"
                if obs.evidence_ref
                else None,
                extra_metadata={
                    "conflict_rate": conflict_rate,
                    "delay_seconds": round(delay + conflict_delay, 6),
                    "original_observed_value": obs.observed_value,
                    "flipped_observed_value": flipped_value,
                },
            )
        )

    observations = with_stream_order(observations, regime=regime, seed=seed)
    return RegimeResult(
        name=regime,
        path=Path(f"{regime}.jsonl"),
        observations=observations,
        input_count=len(clean),
        dropped_count=dropped,
        conflict_added_count=conflict_added,
        delayed_count=delayed,
        low_confidence_count=lowered,
    )


def write_manifest(
    path: Path,
    *,
    input_path: Path,
    seed: int,
    results: list[RegimeResult],
    params: dict[str, Any],
) -> None:
    manifest = {
        "input": str(input_path),
        "seed": seed,
        "params": params,
        "streams": {
            result.name: {
                "path": str(path.parent / result.path),
                "observations": result.output_count,
                "dropped": result.dropped_count,
                "conflict_added": result.conflict_added_count,
                "delayed": count_delayed(result.observations),
                "low_confidence": result.low_confidence_count,
            }
            for result in results
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def table_from_results(results: list[RegimeResult], output_dir: Path) -> str:
    lines = [
        "| regime | output | observations | dropped | conflict added | delayed | low confidence | out-of-order rows | avg delay | max delay |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        avg_delay, max_delay = delay_stats(result.observations)
        lines.append(
            f"| `{result.name}` | `{output_dir / result.path}` | "
            f"{result.output_count} | {result.dropped_count} | "
            f"{result.conflict_added_count} | {count_delayed(result.observations)} | "
            f"{result.low_confidence_count} | "
            f"{count_out_of_order(result.observations)} | "
            f"{avg_delay:.3f} | {max_delay:.3f} |"
        )
    return "\n".join(lines)


def table_from_counter(counter: Counter[str], limit: int) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common(limit):
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def sample_table(result: RegimeResult, limit: int) -> str:
    lines = [
        "| arrival_time | event_time | source | predicate | value | confidence | operations | obs_id |",
        "| ---: | ---: | --- | --- | --- | ---: | --- | --- |",
    ]
    for obs in result.observations[:limit]:
        operations = ",".join(obs.metadata.get("perturbation", {}).get("operations", []))
        lines.append(
            f"| {obs.arrival_time:g} | {obs.event_time:g} | `{obs.source}` | "
            f"`{obs.predicate_name}` | {obs.observed_value} | {obs.confidence:g} | "
            f"`{operations}` | `{obs.obs_id}` |"
        )
    if len(lines) == 2:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(
    *,
    input_path: Path,
    output_dir: Path,
    manifest_path: Path,
    clean_count: int,
    seed: int,
    results: list[RegimeResult],
    params: dict[str, Any],
    top_n: int,
) -> str:
    source_counter = Counter()
    operation_counter = Counter()
    for result in results:
        for obs in result.observations:
            source_counter[obs.source] += 1
            operation_counter.update(
                obs.metadata.get("perturbation", {}).get("operations", [])
            )

    return f"""# Perturbed StateObservation Streams v0

本报告由 `tools/build_perturbed_observations.py` 生成。

它对应最小验证计划的第 4 步：

```text
从 clean StateObservation stream 注入 delay / missing / conflict / out-of-order / low-confidence
```

这些 stream 是 benchmark 输入变体，不是 hidden truth，也不是标准答案。标准答案仍应由 hidden timeline / oracle generator 产生。

## 配置

| item | value |
| --- | --- |
| input clean observations | `{input_path}` |
| clean observation count | {clean_count} |
| output directory | `{output_dir}` |
| manifest | `{manifest_path}` |
| seed | {seed} |

## 参数

```json
{json.dumps(params, ensure_ascii=False, indent=2)}
```

## Streams

{table_from_results(results, output_dir)}

## Operation Counts

{table_from_counter(operation_counter, top_n)}

## Source Counts

{table_from_counter(source_counter, top_n)}

## Mixed Stream Sample

{sample_table(next(result for result in results if result.name == "mixed"), 16)}

## 生成规则

1. `delay`: 所有 observation 使用固定延迟，`arrival_time = event_time + constant_delay`。
2. `out_of_order`: 每条 observation 使用随机延迟，并按 `arrival_time` 排序，因此同一个 episode 内可能出现旧事件晚到。
3. `missing`: 按固定概率丢弃 observation。
4. `low_confidence`: 按固定概率降低 observation confidence。
5. `conflict`: 保留原始 observation，同时为一部分 boolean observation 注入相反 observed_value 的冲突 observation。
6. `mixed`: 同时组合 missing、random delay、low-confidence 和 conflict。

## 边界

Conflict observation 的 `observed_value` 会翻转，但 `polarity` 仍保持 `support`。这表示另一个传感器也在支持自己的状态声明，系统需要通过同一 state_key 上的证据不一致来识别冲突，而不是直接读取一个“这是冲突”的标签。

当前 metadata 中保留了 perturbation 调试信息，方便开发和检查。后续如果要作为正式公开 benchmark 输入，可以选择隐藏或裁剪这部分 metadata，避免被测系统利用生成标签作弊。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build perturbed StateObservation streams from the clean stream."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--constant-delay-seconds", type=float, default=5.0)
    parser.add_argument("--max-random-delay-seconds", type=float, default=12.0)
    parser.add_argument("--missing-rate", type=float, default=0.2)
    parser.add_argument("--low-confidence-rate", type=float, default=0.35)
    parser.add_argument("--low-confidence-min", type=float, default=0.35)
    parser.add_argument("--low-confidence-max", type=float, default=0.75)
    parser.add_argument("--conflict-rate", type=float, default=0.1)
    parser.add_argument("--conflict-confidence", type=float, default=0.65)
    parser.add_argument("--conflict-max-delay-seconds", type=float, default=6.0)
    parser.add_argument("--top-n", type=int, default=25)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.input.exists():
        raise FileNotFoundError(
            f"Clean observation file not found: {args.input}. "
            "Run tools/build_clean_observations.py first."
        )
    for name in ("missing_rate", "low_confidence_rate", "conflict_rate"):
        value = getattr(args, name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name.replace('_', '-')} must be within [0, 1]")
    for name in ("low_confidence_min", "low_confidence_max", "conflict_confidence"):
        value = getattr(args, name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name.replace('_', '-')} must be within [0, 1]")
    if args.low_confidence_max < args.low_confidence_min:
        raise ValueError("low-confidence-max must be >= low-confidence-min")
    if args.constant_delay_seconds < 0:
        raise ValueError("constant-delay-seconds must be non-negative")
    if args.max_random_delay_seconds < 0:
        raise ValueError("max-random-delay-seconds must be non-negative")
    if args.conflict_max_delay_seconds <= 0:
        raise ValueError("conflict-max-delay-seconds must be positive")


def main() -> None:
    args = parse_args()
    validate_args(args)

    clean = load_observations(args.input)
    params = {
        "constant_delay_seconds": args.constant_delay_seconds,
        "max_random_delay_seconds": args.max_random_delay_seconds,
        "missing_rate": args.missing_rate,
        "low_confidence_rate": args.low_confidence_rate,
        "low_confidence_min": args.low_confidence_min,
        "low_confidence_max": args.low_confidence_max,
        "conflict_rate": args.conflict_rate,
        "conflict_confidence": args.conflict_confidence,
        "conflict_max_delay_seconds": args.conflict_max_delay_seconds,
    }

    results = [
        build_delay_stream(
            clean,
            seed=args.seed + 1,
            delay_seconds=args.constant_delay_seconds,
        ),
        build_out_of_order_stream(
            clean,
            seed=args.seed + 2,
            max_delay_seconds=args.max_random_delay_seconds,
        ),
        build_missing_stream(
            clean,
            seed=args.seed + 3,
            missing_rate=args.missing_rate,
        ),
        build_low_confidence_stream(
            clean,
            seed=args.seed + 4,
            low_confidence_rate=args.low_confidence_rate,
            low_confidence_min=args.low_confidence_min,
            low_confidence_max=args.low_confidence_max,
        ),
        build_conflict_stream(
            clean,
            seed=args.seed + 5,
            conflict_rate=args.conflict_rate,
            conflict_confidence=args.conflict_confidence,
            conflict_max_delay_seconds=args.conflict_max_delay_seconds,
        ),
        build_mixed_stream(
            clean,
            seed=args.seed + 6,
            missing_rate=args.missing_rate,
            low_confidence_rate=args.low_confidence_rate,
            low_confidence_min=args.low_confidence_min,
            low_confidence_max=args.low_confidence_max,
            conflict_rate=args.conflict_rate,
            conflict_confidence=args.conflict_confidence,
            max_delay_seconds=args.max_random_delay_seconds,
        ),
    ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        full_path = args.output_dir / result.path
        write_observations(full_path, result.observations)

    manifest_path = args.output_dir / "manifest.json"
    write_manifest(
        manifest_path,
        input_path=args.input,
        seed=args.seed,
        results=results,
        params=params,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            input_path=args.input,
            output_dir=args.output_dir,
            manifest_path=manifest_path,
            clean_count=len(clean),
            seed=args.seed,
            results=results,
            params=params,
            top_n=args.top_n,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "input": str(args.input),
                "output_dir": str(args.output_dir),
                "report": str(args.report),
                "manifest": str(manifest_path),
                "streams": {
                    result.name: {
                        "observations": result.output_count,
                        "dropped": result.dropped_count,
                        "conflict_added": result.conflict_added_count,
                        "delayed": count_delayed(result.observations),
                        "low_confidence": result.low_confidence_count,
                        "out_of_order_rows": count_out_of_order(result.observations),
                    }
                    for result in results
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
