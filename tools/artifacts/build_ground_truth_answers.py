#!/usr/bin/env python3
"""Build ground-truth answers for EviStateBench v0 query sets.

This script implements Step 6 of the minimal pipeline:

hidden timeline + query set + observation streams -> ground-truth answer sets

Semantics:
- CHECK_STATE / STATE_DIFF / CHECK_GOAL are answered from hidden world truth.
- AS_OF_STATE is answered from the selected observation stream using
  transaction-time information availability.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.queries import (  # noqa: E402
    GoalAnswer,
    GoalPredicateResult,
    StateAnswer,
    StateChange,
    StateDiffAnswer,
    StateInstance,
)
from evistatebench.schema import ObservedValue, StateObservation  # noqa: E402


DEFAULT_TIMELINE_PATH = (
    REPO_ROOT / "data" / "synthetic_ground_truth_timelines_v0.jsonl"
)
DEFAULT_QUERY_PATH = REPO_ROOT / "data" / "query_sets_v0" / "queries.jsonl"
DEFAULT_CLEAN_STREAM_PATH = REPO_ROOT / "data" / "clean_state_observations_v0.jsonl"
DEFAULT_STREAM_DIR = REPO_ROOT / "data" / "observation_streams_v0"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "answer_sets_v0"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ground_truth_answers_v0.md"


StateKey = tuple[str, tuple[str, ...]]


def open_text(path: Path, mode: str = "r"):
    if path.name.endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def stream_name_for_path(path: Path) -> str:
    name = path.name
    if name.endswith(".jsonl.gz"):
        return name[: -len(".jsonl.gz")]
    if name.endswith(".jsonl"):
        return name[: -len(".jsonl")]
    return path.stem


def iter_jsonl_paths(directory: Path) -> list[Path]:
    return sorted(
        [*directory.glob("*.jsonl"), *directory.glob("*.jsonl.gz")],
        key=lambda path: (stream_name_for_path(path), path.name),
    )


def stable_value_key(value: Any) -> str:
    """Return a hashable key for JSON-compatible observed values."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One hidden world-truth state event."""

    event_id: str
    episode_id: str
    task_id: str
    task_file_id: str
    event_time: float
    event_index: int
    predicate_name: str
    arguments: tuple[str, ...]
    truth_value: ObservedValue

    @property
    def state_key(self) -> StateKey:
        return (self.predicate_name, self.arguments)


@dataclass(frozen=True, slots=True)
class TruthLookupResult:
    """Value of a state at a valid_time according to hidden world truth."""

    value: ObservedValue
    source_event_id: str | None
    valid_interval: tuple[float, float | None] | None


@dataclass(frozen=True, slots=True)
class AvailableEvidenceResult:
    """Value available to a system at a transaction_time from one stream."""

    value: ObservedValue | None
    confidence: float
    status: str
    support_observation_ids: tuple[str, ...]
    contradict_observation_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    latest_event_time: float | None


def state_from_query(row: dict[str, Any]) -> StateInstance:
    state = row["state"]
    return StateInstance(
        predicate_name=state["predicate_name"],
        arguments=tuple(state["arguments"]),
    )


def state_key_from_state(state: StateInstance) -> StateKey:
    return (state.predicate_name, state.arguments)


def load_timeline(path: Path) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    with open_text(path) as f:
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
                    event_time=float(row["event_time"]),
                    event_index=int(row["event_index"]),
                    predicate_name=row["predicate_name"],
                    arguments=tuple(row["arguments"]),
                    truth_value=row["truth_value"],
                )
            )
    return sorted(events, key=lambda e: (e.episode_id, e.event_time, e.event_index))


def load_queries(path: Path) -> list[dict[str, Any]]:
    with open_text(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_observations(path: Path) -> list[StateObservation]:
    observations: list[StateObservation] = []
    with open_text(path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            row.pop("predicate_category", None)
            observations.append(StateObservation(**row))
    return sorted(
        observations,
        key=lambda obs: (obs.episode_id, obs.arrival_time, obs.event_time, obs.obs_id),
    )


def discover_streams(
    clean_stream_path: Path,
    stream_dir: Path,
) -> dict[str, Path]:
    streams = {"clean": clean_stream_path}
    if stream_dir.exists():
        for path in iter_jsonl_paths(stream_dir):
            stream_name = stream_name_for_path(path)
            if stream_name in streams:
                raise ValueError(
                    f"Duplicate observation stream name {stream_name!r}: "
                    f"{streams[stream_name]} and {path}"
                )
            streams[stream_name] = path
    return streams


class TruthTimeline:
    """Hidden world-truth lookup over timeline events."""

    def __init__(self, events: list[TimelineEvent]) -> None:
        self.events_by_episode_state: dict[str, dict[StateKey, list[TimelineEvent]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        self.state_keys_by_episode: dict[str, set[StateKey]] = defaultdict(set)
        for event in events:
            self.events_by_episode_state[event.episode_id][event.state_key].append(event)
            self.state_keys_by_episode[event.episode_id].add(event.state_key)

        for state_events in self.events_by_episode_state.values():
            for events_for_state in state_events.values():
                events_for_state.sort(key=lambda event: (event.event_time, event.event_index))

    def value_at(
        self,
        episode_id: str,
        state_key: StateKey,
        valid_time: float,
    ) -> TruthLookupResult:
        events = self.events_by_episode_state.get(episode_id, {}).get(state_key, [])
        latest: TimelineEvent | None = None
        next_event: TimelineEvent | None = None
        for event in events:
            if event.event_time <= valid_time:
                latest = event
            elif event.event_time > valid_time:
                next_event = event
                break

        if latest is None:
            # v0 hidden timeline uses closed-world default for unobserved states.
            return TruthLookupResult(value=False, source_event_id=None, valid_interval=None)

        return TruthLookupResult(
            value=latest.truth_value,
            source_event_id=latest.event_id,
            valid_interval=(
                latest.event_time,
                None if next_event is None else next_event.event_time,
            ),
        )

    def state_keys(self, episode_id: str) -> set[StateKey]:
        return set(self.state_keys_by_episode.get(episode_id, set()))


class ObservationAvailability:
    """Transaction-time evidence lookup over one observation stream."""

    def __init__(self, observations: list[StateObservation], uncertain_threshold: float) -> None:
        self.uncertain_threshold = uncertain_threshold
        self.observations_by_episode_state: dict[str, dict[StateKey, list[StateObservation]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        for obs in observations:
            self.observations_by_episode_state[obs.episode_id][obs.state_key].append(obs)

        for state_observations in self.observations_by_episode_state.values():
            for obs_list in state_observations.values():
                obs_list.sort(key=lambda obs: (obs.arrival_time, obs.event_time, obs.obs_id))

    def available_at(
        self,
        episode_id: str,
        state_key: StateKey,
        valid_time: float,
        transaction_time: float,
    ) -> AvailableEvidenceResult:
        candidates = [
            obs
            for obs in self.observations_by_episode_state.get(episode_id, {}).get(state_key, [])
            if obs.event_time <= valid_time and obs.arrival_time <= transaction_time
        ]
        if not candidates:
            return AvailableEvidenceResult(
                value=None,
                confidence=0.0,
                status="unknown",
                support_observation_ids=(),
                contradict_observation_ids=(),
                evidence_refs=(),
                latest_event_time=None,
            )

        latest_event_time = max(obs.event_time for obs in candidates)
        latest = [obs for obs in candidates if obs.event_time == latest_event_time]
        values: dict[str, list[StateObservation]] = defaultdict(list)
        for obs in latest:
            values[stable_value_key(obs.observed_value)].append(obs)

        evidence_refs = tuple(obs.evidence_ref for obs in latest if obs.evidence_ref)
        if len(values) > 1:
            sorted_groups = sorted(
                values.values(),
                key=lambda group: (-len(group), -max(obs.confidence for obs in group)),
            )
            support = tuple(obs.obs_id for obs in sorted_groups[0])
            contradict = tuple(obs.obs_id for group in sorted_groups[1:] for obs in group)
            return AvailableEvidenceResult(
                value=None,
                confidence=max(obs.confidence for obs in latest),
                status="conflict",
                support_observation_ids=support,
                contradict_observation_ids=contradict,
                evidence_refs=evidence_refs,
                latest_event_time=latest_event_time,
            )

        group = next(iter(values.values()))
        value = group[0].observed_value
        confidence = max(obs.confidence for obs in group)
        status = "known" if confidence >= self.uncertain_threshold else "uncertain"
        return AvailableEvidenceResult(
            value=value,
            confidence=confidence,
            status=status,
            support_observation_ids=tuple(obs.obs_id for obs in group),
            contradict_observation_ids=(),
            evidence_refs=evidence_refs,
            latest_event_time=latest_event_time,
        )


def wrap_answer(
    *,
    query_type: str,
    answer_type: str,
    answer: StateAnswer | StateDiffAnswer | GoalAnswer,
) -> dict[str, Any]:
    row = answer.to_dict()
    row["query_type"] = query_type
    row["answer_type"] = answer_type
    return row


def make_state_answer_from_truth(
    query: dict[str, Any],
    timeline: TruthTimeline,
) -> StateAnswer:
    state = state_from_query(query)
    state_key = state_key_from_state(state)
    lookup = timeline.value_at(query["episode_id"], state_key, float(query["valid_time"]))
    return StateAnswer(
        query_id=query["query_id"],
        state=state,
        value=lookup.value,
        confidence=1.0,
        status="known",
        valid_interval=lookup.valid_interval,
        state_id=f"{query['episode_id']}::{state.predicate_name}::{','.join(state.arguments)}",
        metadata={
            "answer_semantics": "hidden_world_truth",
            "source_event_id": lookup.source_event_id,
        },
    )


def make_asof_answer(
    query: dict[str, Any],
    availability: ObservationAvailability,
    stream_name: str,
) -> StateAnswer:
    state = state_from_query(query)
    state_key = state_key_from_state(state)
    result = availability.available_at(
        episode_id=query["episode_id"],
        state_key=state_key,
        valid_time=float(query["valid_time"]),
        transaction_time=float(query["transaction_time"]),
    )
    return StateAnswer(
        query_id=query["query_id"],
        state=state,
        value=result.value,
        confidence=result.confidence,
        status=result.status,  # type: ignore[arg-type]
        transaction_time=float(query["transaction_time"]),
        state_id=f"{query['episode_id']}::{state.predicate_name}::{','.join(state.arguments)}",
        metadata={
            "answer_semantics": "stream_transaction_time_availability",
            "stream_name": stream_name,
            "latest_available_event_time": result.latest_event_time,
            "support_observation_ids": list(result.support_observation_ids),
            "contradict_observation_ids": list(result.contradict_observation_ids),
            "evidence_refs": list(result.evidence_refs),
        },
    )


def make_state_change(
    state_key: StateKey,
    value_at_t1: ObservedValue | None,
    value_at_t2: ObservedValue | None,
) -> StateChange:
    predicate_name, arguments = state_key
    return StateChange(
        state=StateInstance(predicate_name=predicate_name, arguments=arguments),
        value_at_t1=value_at_t1,
        value_at_t2=value_at_t2,
        confidence_at_t1=1.0,
        confidence_at_t2=1.0,
    )


def make_diff_answer(query: dict[str, Any], timeline: TruthTimeline) -> StateDiffAnswer:
    episode_id = query["episode_id"]
    t1 = float(query["t1"])
    t2 = float(query["t2"])
    changed: list[StateChange] = []
    added: list[StateChange] = []
    removed: list[StateChange] = []

    for state_key in sorted(timeline.state_keys(episode_id)):
        v1 = timeline.value_at(episode_id, state_key, t1).value
        v2 = timeline.value_at(episode_id, state_key, t2).value
        if v1 == v2:
            continue
        change = make_state_change(state_key, v1, v2)
        if v1 is False and v2 is True:
            added.append(change)
        elif v1 is True and v2 is False:
            removed.append(change)
        else:
            changed.append(change)

    return StateDiffAnswer(
        query_id=query["query_id"],
        changed_states=tuple(changed),
        added_states=tuple(added),
        removed_states=tuple(removed),
        metadata={
            "answer_semantics": "hidden_world_truth_diff",
            "scope": query["scope"],
            "t1": t1,
            "t2": t2,
        },
    )


def make_goal_answer(query: dict[str, Any], timeline: TruthTimeline) -> GoalAnswer:
    valid_time = float(query["valid_time"])
    goal_specs = query.get("metadata", {}).get("goal_states", [])
    satisfied: list[GoalPredicateResult] = []
    violated: list[GoalPredicateResult] = []

    for spec in goal_specs:
        state = StateInstance(
            predicate_name=spec["predicate_name"],
            arguments=tuple(spec["arguments"]),
        )
        required_value = spec.get("desired_value", True)
        lookup = timeline.value_at(query["episode_id"], state_key_from_state(state), valid_time)
        result = GoalPredicateResult(
            state=state,
            required_value=required_value,
            value=lookup.value,
            confidence=1.0,
            status="known",
            metadata={"source_event_id": lookup.source_event_id},
        )
        if lookup.value == required_value:
            satisfied.append(result)
        else:
            violated.append(result)

    overall = len(violated) == 0
    return GoalAnswer(
        query_id=query["query_id"],
        satisfied=overall,
        confidence=1.0,
        status="known",
        satisfied_predicates=tuple(satisfied),
        violated_predicates=tuple(violated),
        metadata={
            "answer_semantics": "hidden_world_truth_goal",
            "valid_time": valid_time,
            "goal_state_count": len(goal_specs),
        },
    )


def build_answers_for_stream(
    queries: list[dict[str, Any]],
    timeline: TruthTimeline,
    availability: ObservationAvailability,
    stream_name: str,
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for query in queries:
        query_type = query["query_type"]
        if query_type == "CHECK_STATE":
            answers.append(
                wrap_answer(
                    query_type=query_type,
                    answer_type="STATE_ANSWER",
                    answer=make_state_answer_from_truth(query, timeline),
                )
            )
        elif query_type == "AS_OF_STATE":
            answers.append(
                wrap_answer(
                    query_type=query_type,
                    answer_type="STATE_ANSWER",
                    answer=make_asof_answer(query, availability, stream_name),
                )
            )
        elif query_type == "STATE_DIFF":
            answers.append(
                wrap_answer(
                    query_type=query_type,
                    answer_type="STATE_DIFF_ANSWER",
                    answer=make_diff_answer(query, timeline),
                )
            )
        elif query_type == "CHECK_GOAL":
            answers.append(
                wrap_answer(
                    query_type=query_type,
                    answer_type="GOAL_ANSWER",
                    answer=make_goal_answer(query, timeline),
                )
            )
        else:
            raise ValueError(f"Unsupported query_type for v0 oracle: {query_type}")
    return answers


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_text(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def validate_answer_row(row: dict[str, Any]) -> None:
    answer_type = row["answer_type"]
    payload = {k: v for k, v in row.items() if k not in {"answer_type", "query_type"}}

    if answer_type == "STATE_ANSWER":
        payload["state"] = StateInstance(**payload["state"])
        StateAnswer(**payload)
    elif answer_type == "STATE_DIFF_ANSWER":
        for key in ("changed_states", "added_states", "removed_states", "unchanged_but_uncertain_states"):
            payload[key] = tuple(
                StateChange(
                    state=StateInstance(**change["state"]),
                    value_at_t1=change["value_at_t1"],
                    value_at_t2=change["value_at_t2"],
                    confidence_at_t1=change["confidence_at_t1"],
                    confidence_at_t2=change["confidence_at_t2"],
                    support_observation_ids=tuple(change.get("support_observation_ids", ())),
                    contradict_observation_ids=tuple(change.get("contradict_observation_ids", ())),
                )
                for change in payload.get(key, ())
            )
        StateDiffAnswer(**payload)
    elif answer_type == "GOAL_ANSWER":
        for key in ("satisfied_predicates", "violated_predicates", "uncertain_predicates"):
            payload[key] = tuple(
                GoalPredicateResult(
                    state=StateInstance(**result["state"]),
                    required_value=result.get("required_value"),
                    value=result.get("value"),
                    confidence=result["confidence"],
                    status=result["status"],
                    support_observation_ids=tuple(result.get("support_observation_ids", ())),
                    contradict_observation_ids=tuple(result.get("contradict_observation_ids", ())),
                    metadata=result.get("metadata", {}),
                )
                for result in payload.get(key, ())
            )
        GoalAnswer(**payload)
    else:
        raise ValueError(f"Unsupported answer_type: {answer_type}")


def status_counts_by_query_type(answers: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for answer in answers:
        status = answer.get("status")
        if status is not None:
            counts[answer["query_type"]][status] += 1
    return dict(counts)


def write_manifest(
    path: Path,
    *,
    timeline_path: Path,
    query_path: Path,
    stream_paths: dict[str, Path],
    outputs: dict[str, Path],
    answer_counts: dict[str, Counter[str]],
    uncertain_threshold: float,
) -> None:
    manifest = {
        "timeline_path": str(timeline_path),
        "query_path": str(query_path),
        "uncertain_confidence_threshold": uncertain_threshold,
        "streams": {
            name: {
                "observation_stream": str(stream_paths[name]),
                "answer_set": str(outputs[name]),
                "answer_type_counts": dict(answer_counts[name]),
            }
            for name in sorted(outputs)
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def table_from_counter(counter: Counter[str]) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common():
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def stream_table(
    outputs: dict[str, Path],
    answer_rows_by_stream: dict[str, list[dict[str, Any]]],
) -> str:
    lines = [
        "| stream | output | answers | known | unknown | uncertain | conflict |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in sorted(outputs):
        status_counter = Counter(row.get("status", "n/a") for row in answer_rows_by_stream[name])
        lines.append(
            f"| `{name}` | `{outputs[name]}` | {len(answer_rows_by_stream[name])} | "
            f"{status_counter['known']} | {status_counter['unknown']} | "
            f"{status_counter['uncertain']} | {status_counter['conflict']} |"
        )
    return "\n".join(lines)


def sample_table(rows: list[dict[str, Any]], limit: int) -> str:
    lines = [
        "| query_type | answer_type | query_id | value/satisfied | confidence | status |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in rows[:limit]:
        value = row.get("value", row.get("satisfied"))
        lines.append(
            f"| `{row['query_type']}` | `{row['answer_type']}` | `{row['query_id']}` | "
            f"{value} | {row.get('confidence', 0):g} | `{row.get('status', 'n/a')}` |"
        )
    if len(lines) == 2:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(
    *,
    timeline_path: Path,
    query_path: Path,
    output_dir: Path,
    manifest_path: Path,
    stream_paths: dict[str, Path],
    answer_rows_by_stream: dict[str, list[dict[str, Any]]],
    uncertain_threshold: float,
) -> str:
    clean_rows = answer_rows_by_stream.get("clean", [])
    clean_type_counter = Counter(row["answer_type"] for row in clean_rows)
    clean_query_counter = Counter(row["query_type"] for row in clean_rows)

    return f"""# Ground-Truth Answer Sets v0

本报告由 `tools/artifacts/build_ground_truth_answers.py` 生成。

它对应最小验证计划的第 6 步：

```text
用 hidden timeline 和 observation streams 生成 ground-truth answers
```

## 配置

| item | value |
| --- | --- |
| hidden timeline | `{timeline_path}` |
| query set | `{query_path}` |
| output directory | `{output_dir}` |
| manifest | `{manifest_path}` |
| uncertain confidence threshold | {uncertain_threshold:g} |
| observation streams | {len(stream_paths)} |

## Oracle Semantics

```text
CHECK_STATE  -> hidden world truth at valid_time
STATE_DIFF   -> hidden world truth difference between t1 and t2
CHECK_GOAL   -> hidden world truth + goal specs
AS_OF_STATE  -> selected observation stream evidence available by transaction_time
```

`AS_OF_STATE` 是 stream-dependent 的：同一个 query 在 clean / delay / missing / conflict / mixed stream 下可能有不同标准答案，因为 transaction_time 前可见证据不同。

## Streams

{stream_table({name: output_dir / f"{name}.jsonl" for name in answer_rows_by_stream}, answer_rows_by_stream)}

## Clean Answer Types

{table_from_counter(clean_type_counter)}

## Clean Query Types

{table_from_counter(clean_query_counter)}

## Clean Sample Answers

{sample_table(clean_rows, 16)}

## 边界

这一步生成的是 evaluator 使用的标准答案，不是被测系统输入。正式发布 benchmark 时，answer sets 应该只用于本地评测或隐藏评测服务器，不应和 observation streams 一起暴露给被测系统。

当前 `AS_OF_STATE` oracle 是一个轻量 evidence-availability oracle：它只看 `arrival_time <= transaction_time` 且 `event_time <= valid_time` 的 observation，并取最新 event_time 的证据。如果最新证据值冲突，则答案 status 为 `conflict`；如果没有证据，则为 `unknown`；如果证据 confidence 低于阈值，则为 `uncertain`。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build EviStateBench v0 ground-truth answer sets."
    )
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE_PATH)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_PATH)
    parser.add_argument("--clean-stream", type=Path, default=DEFAULT_CLEAN_STREAM_PATH)
    parser.add_argument("--stream-dir", type=Path, default=DEFAULT_STREAM_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--uncertain-confidence-threshold", type=float, default=0.75)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path, label in (
        (args.timeline, "timeline"),
        (args.queries, "query set"),
        (args.clean_stream, "clean stream"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")
    if not 0.0 <= args.uncertain_confidence_threshold <= 1.0:
        raise ValueError("uncertain-confidence-threshold must be within [0, 1]")

    timeline = TruthTimeline(load_timeline(args.timeline))
    queries = load_queries(args.queries)
    stream_paths = discover_streams(args.clean_stream, args.stream_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    answer_rows_by_stream: dict[str, list[dict[str, Any]]] = {}
    outputs: dict[str, Path] = {}
    answer_type_counts: dict[str, Counter[str]] = {}

    for stream_name, stream_path in sorted(stream_paths.items()):
        observations = load_observations(stream_path)
        availability = ObservationAvailability(
            observations,
            uncertain_threshold=args.uncertain_confidence_threshold,
        )
        answers = build_answers_for_stream(
            queries,
            timeline,
            availability,
            stream_name,
        )
        for row in answers:
            validate_answer_row(row)
        output_path = args.output_dir / f"{stream_name}.jsonl"
        write_jsonl(output_path, answers)
        answer_rows_by_stream[stream_name] = answers
        outputs[stream_name] = output_path
        answer_type_counts[stream_name] = Counter(row["answer_type"] for row in answers)

    manifest_path = args.output_dir / "manifest.json"
    write_manifest(
        manifest_path,
        timeline_path=args.timeline,
        query_path=args.queries,
        stream_paths=stream_paths,
        outputs=outputs,
        answer_counts=answer_type_counts,
        uncertain_threshold=args.uncertain_confidence_threshold,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            timeline_path=args.timeline,
            query_path=args.queries,
            output_dir=args.output_dir,
            manifest_path=manifest_path,
            stream_paths=stream_paths,
            answer_rows_by_stream=answer_rows_by_stream,
            uncertain_threshold=args.uncertain_confidence_threshold,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "timeline": str(args.timeline),
                "queries": str(args.queries),
                "output_dir": str(args.output_dir),
                "manifest": str(manifest_path),
                "report": str(args.report),
                "streams": {
                    name: {
                        "answers": len(answer_rows_by_stream[name]),
                        "answer_type_counts": dict(answer_type_counts[name]),
                        "status_counts": dict(
                            Counter(
                                row.get("status", "n/a")
                                for row in answer_rows_by_stream[name]
                            )
                        ),
                    }
                    for name in sorted(answer_rows_by_stream)
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
