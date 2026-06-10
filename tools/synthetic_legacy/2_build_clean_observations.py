#!/usr/bin/env python3
"""Build clean StateObservation streams from synthetic ground-truth timelines.

This script implements Step 3 of the minimal EviStateBench pipeline:

hidden ground-truth timeline -> clean StateObservation stream

The clean stream is a public benchmark input candidate.  It has no delay,
missing observations, injected conflicts, or confidence degradation.  Perturbed
streams should be produced by later scripts from this clean stream.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.schema import StateObservation  # noqa: E402


DEFAULT_TIMELINE_PATH = (
    REPO_ROOT / "data" / "synthetic_ground_truth_timelines_v0.jsonl"
)
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "clean_state_observations_v0.jsonl"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "clean_observations_v0.md"
DEFAULT_SOURCE = "synthetic_truth_sensor"


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """A timeline event loaded from Step 2 JSONL."""

    event_id: str
    episode_id: str
    task_id: str
    task_file_id: str
    task_family: str
    event_time: float
    event_index: int
    event_type: str
    predicate_name: str
    arguments: tuple[str, ...]
    truth_value: bool
    previous_truth_value: bool | None
    source_instance_id: str
    source_section: str
    synthetic_reason: str
    metadata: dict[str, Any]


def load_timeline_events(path: Path) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            events.append(
                TimelineEvent(
                    event_id=row["event_id"],
                    episode_id=row["episode_id"],
                    task_id=row["task_id"],
                    task_file_id=row["task_file_id"],
                    task_family=row["task_family"],
                    event_time=float(row["event_time"]),
                    event_index=int(row["event_index"]),
                    event_type=row["event_type"],
                    predicate_name=row["predicate_name"],
                    arguments=tuple(row["arguments"]),
                    truth_value=bool(row["truth_value"]),
                    previous_truth_value=row["previous_truth_value"],
                    source_instance_id=row["source_instance_id"],
                    source_section=row["source_section"],
                    synthetic_reason=row["synthetic_reason"],
                    metadata=dict(row.get("metadata", {})),
                )
            )
    return sorted(events, key=lambda event: (event.episode_id, event.event_time, event.event_index))


def make_obs_id(event: TimelineEvent) -> str:
    """Create a stable clean observation id from the source timeline event."""
    return event.event_id.replace("__ev", "__obs_clean_")


def event_to_clean_observation(
    event: TimelineEvent,
    source: str,
    confidence: float,
) -> StateObservation:
    """Convert one hidden timeline event into one clean StateObservation."""
    metadata = {
        "stream_variant": "clean_v0",
        "source_event_id": event.event_id,
        "source_event_type": event.event_type,
        "source_event_index": event.event_index,
        "source_instance_id": event.source_instance_id,
        "source_section": event.source_section,
        "task_file_id": event.task_file_id,
        "task_family": event.task_family,
        "synthetic_reason": event.synthetic_reason,
        "previous_truth_value": event.previous_truth_value,
        "clean_generation": {
            "arrival_time_policy": "arrival_time_equals_event_time",
            "confidence_policy": "constant_confidence",
            "missing_policy": "none",
            "conflict_policy": "none",
            "delay_policy": "none",
        },
    }
    metadata.update(event.metadata)
    return StateObservation(
        obs_id=make_obs_id(event),
        episode_id=event.episode_id,
        task_id=event.task_id,
        event_time=event.event_time,
        arrival_time=event.event_time,
        source=source,
        predicate_name=event.predicate_name,
        arguments=event.arguments,
        observed_value=event.truth_value,
        confidence=confidence,
        evidence_ref=event.event_id,
        polarity="support",
        metadata=metadata,
    )


def write_observations(path: Path, observations: list[StateObservation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for observation in observations:
            f.write(json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True))
            f.write("\n")


def table_from_counter(counter: Counter[str], limit: int) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common(limit):
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def sample_observation_table(
    observations: list[StateObservation],
    limit: int,
) -> str:
    lines = [
        "| event_time | arrival_time | source | task | predicate | value | arguments |",
        "| ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for observation in observations[:limit]:
        args = ", ".join(f"`{argument}`" for argument in observation.arguments)
        lines.append(
            f"| {observation.event_time:g} | {observation.arrival_time:g} | "
            f"`{observation.source}` | `{observation.task_id}` | "
            f"`{observation.predicate_name}` | {observation.observed_value} | {args} |"
        )
    if len(lines) == 2:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(
    *,
    input_path: Path,
    output_path: Path,
    events: list[TimelineEvent],
    observations: list[StateObservation],
    source: str,
    confidence: float,
    top_n: int,
) -> str:
    predicate_counter = Counter(obs.predicate_name for obs in observations)
    episode_counter = Counter(obs.episode_id for obs in observations)
    event_type_counter = Counter(
        obs.metadata.get("source_event_type", "unknown") for obs in observations
    )
    family_counter = Counter(obs.metadata.get("task_family", "unknown") for obs in observations)
    arrival_equals_event = sum(
        obs.arrival_time == obs.event_time for obs in observations
    )
    confidence_counter = Counter(str(obs.confidence) for obs in observations)
    false_observation_count = sum(obs.observed_value is False for obs in observations)

    return f"""# Clean StateObservation Stream v0

本报告由 `tools/build_clean_observations.py` 生成。

它对应最小验证计划的第 3 步：

```text
从 hidden ground-truth timeline 生成 clean StateObservation stream
```

这里生成的是被测系统可以接收的干净观察流。它不是 hidden truth 本身，也不是 EviStateDB 的输出。它是后续 noisy / delayed / missing / conflicting observation streams 的基准版本。

## 配置

| item | value |
| --- | --- |
| input timeline events | `{input_path}` |
| output observations | `{output_path}` |
| source | `{source}` |
| confidence | {confidence:g} |

## 总览

| item | count |
| --- | ---: |
| input timeline events | {len(events)} |
| output observations | {len(observations)} |
| episodes | {len(episode_counter)} |
| observations with arrival_time == event_time | {arrival_equals_event} |
| observations with observed_value=False | {false_observation_count} |

## Source Event Types

{table_from_counter(event_type_counter, top_n)}

## Task Families

{table_from_counter(family_counter, top_n)}

## Predicates

{table_from_counter(predicate_counter, top_n)}

## Confidence Values

{table_from_counter(confidence_counter, top_n)}

## Sample Observations

{sample_observation_table(observations, 16)}

## 生成规则

1. 一条 timeline event 生成一条 `StateObservation`。
2. `event_time` 保持不变。
3. `arrival_time = event_time`，所以 clean stream 没有延迟和乱序。
4. `observed_value = truth_value`。
5. `confidence = {confidence:g}`。
6. `polarity = support`。即使 `observed_value=False`，它也是支持“该状态为 False”的证据，不是 contradict。
7. `evidence_ref` 指回 source timeline event id，方便后续 WHY / provenance 评测。

## 边界

这份 clean stream 是 benchmark 输入，不是标准答案。标准答案仍然应由 hidden timeline / oracle generator 产生。

后续 Step 4 会从这份 clean stream 派生：

```text
delayed observations
out-of-order observations
missing observations
conflicting observations
low-confidence observations
mixed-regime observations
```
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build clean StateObservation stream from synthetic timelines."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_TIMELINE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--confidence", type=float, default=1.0)
    parser.add_argument("--top-n", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(
            f"Timeline file not found: {args.input}. "
            "Run tools/build_synthetic_timelines.py first."
        )
    if not 0.0 <= args.confidence <= 1.0:
        raise ValueError("confidence must be within [0, 1]")

    events = load_timeline_events(args.input)
    observations = [
        event_to_clean_observation(
            event=event,
            source=args.source,
            confidence=args.confidence,
        )
        for event in events
    ]

    write_observations(args.output, observations)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            input_path=args.input,
            output_path=args.output,
            events=events,
            observations=observations,
            source=args.source,
            confidence=args.confidence,
            top_n=args.top_n,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "report": str(args.report),
                "timeline_events": len(events),
                "observations": len(observations),
                "episodes": len({obs.episode_id for obs in observations}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
