#!/usr/bin/env python3
"""Build synthetic ground-truth state timelines from BDDL predicate instances.

This script implements Step 2 of the minimal EviStateBench pipeline:

task predicate instances -> synthetic ground-truth timeline

The output is not an observation stream and is not a baseline prediction.  It is
hidden oracle material used by later steps to generate clean observations,
perturbed observations, queries, and ground-truth answers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_INSTANCE_PATH = REPO_ROOT / "data" / "task_predicate_instances_v0.jsonl"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "synthetic_ground_truth_timelines_v0.jsonl"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "synthetic_timelines_v0.md"

# v0 only models a tiny amount of physics.  These relations usually encode one
# primary placement for the first argument, so setting a new one invalidates the
# old one in the synthetic timeline.
EXCLUSIVE_PLACEMENT_PREDICATES = frozenset({"inside", "ontop", "under", "overlaid"})


@dataclass(frozen=True, slots=True)
class PredicateInstance:
    """A normalized task predicate instance loaded from Step 1 JSONL."""

    instance_id: str
    task_id: str
    task_file_id: str
    task_family: str
    section: str
    predicate_name: str
    arguments: tuple[str, ...]
    original_arguments: tuple[str, ...]
    truth_value: bool
    source_file: str
    predicate_category: str

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        return (self.predicate_name, self.arguments)


@dataclass(frozen=True, slots=True)
class GroundTruthStateEvent:
    """One event in a synthetic ground-truth state timeline.

    An event says that a state instance takes a truth value at event_time.
    Later events with the same state_key overwrite earlier truth values.
    """

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
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        return (self.predicate_name, self.arguments)

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["arguments"] = list(self.arguments)
        record["state_key"] = [self.predicate_name, list(self.arguments)]
        return record


@dataclass(slots=True)
class EpisodeBuildResult:
    """Synthetic timeline events and build statistics for one task episode."""

    episode_id: str
    task_id: str
    task_file_id: str
    task_family: str
    events: list[GroundTruthStateEvent]
    init_instance_count: int
    goal_instance_count: int
    duplicate_instance_count: int
    goal_already_satisfied_count: int
    goal_transition_count: int
    invalidation_count: int
    final_time: float
    final_goal_satisfied: bool


def has_instance_suffix(argument: str) -> bool:
    """Return whether an argument looks like a concrete object instance."""
    return bool(re.search(r"_\d+$", argument))


def normalize_argument(argument: str, instance_id: str, argument_index: int) -> str:
    """Normalize BDDL arguments for a flat synthetic timeline.

    BDDL goal variables have two common forms:

    - ?hot_tub.n.02_1: this points to a concrete object id and can be mapped to
      hot_tub.n.02_1.
    - ?comic_book.n.01: this is a typed quantified variable.  The Step 1 flat
      extractor does not preserve quantifier structure, so mapping every
      ?comic_book.n.01 to the same key would create false contradictions.  We
      keep it as a stable symbolic placeholder scoped to the occurrence.
    """
    if not argument.startswith("?"):
        return argument

    stripped = argument[1:]
    if has_instance_suffix(stripped):
        return stripped

    occurrence_suffix = instance_id.split("__", maxsplit=2)[-1].replace("__", "_")
    return f"{stripped}__goalvar_{occurrence_suffix}_arg{argument_index}"


def load_instances(path: Path) -> list[PredicateInstance]:
    instances: list[PredicateInstance] = []
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            original_arguments = tuple(row["arguments"])
            normalized_arguments = tuple(
                normalize_argument(argument, row["instance_id"], argument_index)
                for argument_index, argument in enumerate(original_arguments)
            )
            instances.append(
                PredicateInstance(
                    instance_id=row["instance_id"],
                    task_id=row["task_id"],
                    task_file_id=row["task_file_id"],
                    task_family=row["task_family"],
                    section=row["section"],
                    predicate_name=row["predicate_name"],
                    arguments=normalized_arguments,
                    original_arguments=original_arguments,
                    truth_value=bool(row["truth_value"]),
                    source_file=row["source_file"],
                    predicate_category=row["predicate_category"],
                )
            )
    return instances


def safe_episode_id(task_file_id: str) -> str:
    return "syn_v0__" + task_file_id.replace("/", "__")


def sort_key(instance: PredicateInstance) -> tuple[str, str, tuple[str, ...], str]:
    section_order = "0" if instance.section == "init" else "1"
    return (
        section_order,
        instance.predicate_name,
        instance.arguments,
        instance.instance_id,
    )


def deduplicate_instances(
    instances: list[PredicateInstance],
) -> tuple[list[PredicateInstance], int]:
    """Remove exact duplicate state assertions inside one task file."""
    seen: set[tuple[str, str, tuple[str, ...], bool]] = set()
    deduped: list[PredicateInstance] = []
    duplicate_count = 0
    for instance in sorted(instances, key=sort_key):
        key = (
            instance.section,
            instance.predicate_name,
            instance.arguments,
            instance.truth_value,
        )
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        deduped.append(instance)
    return deduped, duplicate_count


def is_exclusive_conflict(
    target_key: tuple[str, tuple[str, ...]],
    existing_key: tuple[str, tuple[str, ...]],
) -> bool:
    """Return whether an existing placement relation conflicts with a target."""
    target_predicate, target_arguments = target_key
    existing_predicate, existing_arguments = existing_key
    if target_predicate not in EXCLUSIVE_PLACEMENT_PREDICATES:
        return False
    if existing_predicate not in EXCLUSIVE_PLACEMENT_PREDICATES:
        return False
    if not target_arguments or not existing_arguments:
        return False
    return target_arguments[0] == existing_arguments[0] and target_key != existing_key


def build_episode_timeline(
    task_file_id: str,
    instances: list[PredicateInstance],
    goal_start_time: float,
    goal_step: float,
    invalidation_gap: float,
) -> EpisodeBuildResult:
    """Build one synthetic ground-truth timeline from init and goal instances."""
    instances, duplicate_count = deduplicate_instances(instances)
    task_id = instances[0].task_id
    task_family = instances[0].task_family
    episode_id = safe_episode_id(task_file_id)

    init_instances = [instance for instance in instances if instance.section == "init"]
    goal_instances = [instance for instance in instances if instance.section == "goal"]
    positive_goal_keys = {
        instance.state_key for instance in goal_instances if instance.truth_value
    }

    events: list[GroundTruthStateEvent] = []
    current_state: dict[tuple[str, tuple[str, ...]], bool] = {}
    event_index = 0

    def append_event(
        *,
        event_time: float,
        event_type: str,
        predicate_name: str,
        arguments: tuple[str, ...],
        truth_value: bool,
        previous_truth_value: bool | None,
        source_instance_id: str,
        source_section: str,
        synthetic_reason: str,
        metadata: dict[str, Any],
    ) -> None:
        nonlocal event_index
        event_index += 1
        rounded_time = round(event_time, 6)
        event = GroundTruthStateEvent(
            event_id=f"{episode_id}__ev{event_index:05d}",
            episode_id=episode_id,
            task_id=task_id,
            task_file_id=task_file_id,
            task_family=task_family,
            event_time=rounded_time,
            event_index=event_index,
            event_type=event_type,
            predicate_name=predicate_name,
            arguments=arguments,
            truth_value=truth_value,
            previous_truth_value=previous_truth_value,
            source_instance_id=source_instance_id,
            source_section=source_section,
            synthetic_reason=synthetic_reason,
            metadata=metadata,
        )
        events.append(event)
        current_state[event.state_key] = truth_value

    for instance in init_instances:
        previous_value = current_state.get(instance.state_key)
        append_event(
            event_time=0.0,
            event_type="init_assert",
            predicate_name=instance.predicate_name,
            arguments=instance.arguments,
            truth_value=instance.truth_value,
            previous_truth_value=previous_value,
            source_instance_id=instance.instance_id,
            source_section="init",
            synthetic_reason="copied_from_bddl_init",
            metadata={
                "original_arguments": list(instance.original_arguments),
                "predicate_category": instance.predicate_category,
                "source_file": instance.source_file,
                "previous_value_source": "none"
                if previous_value is None
                else "explicit_timeline",
            },
        )

    next_goal_time = goal_start_time
    goal_already_satisfied_count = 0
    goal_transition_count = 0
    invalidation_count = 0

    for instance in goal_instances:
        target_key = instance.state_key
        current_value = current_state.get(target_key, False)
        previous_value_source = (
            "explicit_timeline" if target_key in current_state else "closed_world_default"
        )
        if current_value == instance.truth_value:
            goal_already_satisfied_count += 1
            continue

        if instance.truth_value:
            conflicting_keys = [
                key
                for key, value in current_state.items()
                if value
                and key not in positive_goal_keys
                and is_exclusive_conflict(target_key, key)
            ]
            for conflict_key in sorted(conflicting_keys):
                conflict_predicate, conflict_arguments = conflict_key
                invalidation_time = max(0.0, next_goal_time - invalidation_gap)
                append_event(
                    event_time=invalidation_time,
                    event_type="exclusive_relation_invalidation",
                    predicate_name=conflict_predicate,
                    arguments=conflict_arguments,
                    truth_value=False,
                    previous_truth_value=True,
                    source_instance_id=instance.instance_id,
                    source_section="goal",
                    synthetic_reason=(
                        "new_goal_placement_invalidates_existing_placement"
                    ),
                    metadata={
                        "target_predicate_name": instance.predicate_name,
                        "target_arguments": list(instance.arguments),
                        "original_goal_arguments": list(instance.original_arguments),
                        "predicate_category": instance.predicate_category,
                    },
                )
                invalidation_count += 1

        append_event(
            event_time=next_goal_time,
            event_type="goal_transition",
            predicate_name=instance.predicate_name,
            arguments=instance.arguments,
            truth_value=instance.truth_value,
            previous_truth_value=current_value,
            source_instance_id=instance.instance_id,
            source_section="goal",
            synthetic_reason="scheduled_to_satisfy_bddl_goal",
            metadata={
                "original_arguments": list(instance.original_arguments),
                "predicate_category": instance.predicate_category,
                "source_file": instance.source_file,
                "previous_value_source": previous_value_source,
            },
        )
        goal_transition_count += 1
        next_goal_time += goal_step

    final_time = max((event.event_time for event in events), default=0.0)
    final_goal_satisfied = all(
        current_state.get(instance.state_key, False) == instance.truth_value
        for instance in goal_instances
    )

    return EpisodeBuildResult(
        episode_id=episode_id,
        task_id=task_id,
        task_file_id=task_file_id,
        task_family=task_family,
        events=sorted(events, key=lambda event: (event.event_time, event.event_index)),
        init_instance_count=len(init_instances),
        goal_instance_count=len(goal_instances),
        duplicate_instance_count=duplicate_count,
        goal_already_satisfied_count=goal_already_satisfied_count,
        goal_transition_count=goal_transition_count,
        invalidation_count=invalidation_count,
        final_time=final_time,
        final_goal_satisfied=final_goal_satisfied,
    )


def group_by_task_file(
    instances: list[PredicateInstance],
) -> dict[str, list[PredicateInstance]]:
    groups: dict[str, list[PredicateInstance]] = defaultdict(list)
    for instance in instances:
        groups[instance.task_file_id].append(instance)
    return dict(groups)


def write_events_jsonl(path: Path, episodes: list[EpisodeBuildResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for episode in episodes:
            for event in episode.events:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
                f.write("\n")


def table_from_counter(counter: Counter[str], limit: int) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common(limit):
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def sample_event_table(events: list[GroundTruthStateEvent], limit: int) -> str:
    lines = [
        "| time | event_type | task | predicate | value | arguments |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for event in events[:limit]:
        args = ", ".join(f"`{arg}`" for arg in event.arguments)
        lines.append(
            f"| {event.event_time:g} | `{event.event_type}` | `{event.task_id}` | "
            f"`{event.predicate_name}` | {event.truth_value} | {args} |"
        )
    if len(lines) == 2:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(
    *,
    input_path: Path,
    output_path: Path,
    episodes: list[EpisodeBuildResult],
    goal_start_time: float,
    goal_step: float,
    invalidation_gap: float,
    top_n: int,
) -> str:
    all_events = [event for episode in episodes for event in episode.events]
    event_type_counter = Counter(event.event_type for event in all_events)
    predicate_counter = Counter(event.predicate_name for event in all_events)
    family_counter = Counter(episode.task_family for episode in episodes)
    unsatisfied_episodes = [
        episode for episode in episodes if not episode.final_goal_satisfied
    ]
    episodes_with_goal = [episode for episode in episodes if episode.goal_instance_count]
    satisfied_goal_episodes = [
        episode for episode in episodes_with_goal if episode.final_goal_satisfied
    ]
    symbolic_events = [
        event
        for event in all_events
        if any("__goalvar_" in argument for argument in event.arguments)
    ]
    symbolic_argument_occurrences = sum(
        1
        for event in all_events
        for argument in event.arguments
        if "__goalvar_" in argument
    )

    return f"""# Synthetic Ground-Truth Timelines v0

本报告由 `tools/build_synthetic_timelines.py` 生成。

它对应最小验证计划的第 2 步：

```text
基于 init / goal predicate instances 构造 synthetic ground-truth timeline
```

这里生成的是隐藏真值时间线，不是 observation stream，不是被测系统输入，也不是 EviStateDB 的预测结果。后续会从它生成 clean observations、扰动 observations、queries 和 ground-truth answers。

## 配置

| item | value |
| --- | --- |
| input predicate instances | `{input_path}` |
| output timeline events | `{output_path}` |
| goal start time | {goal_start_time:g} |
| goal step | {goal_step:g} |
| invalidation gap | {invalidation_gap:g} |

## 总览

| item | count |
| --- | ---: |
| episodes | {len(episodes)} |
| episodes with at least one goal predicate | {len(episodes_with_goal)} |
| timeline events | {len(all_events)} |
| deduplicated init assertions | {sum(episode.init_instance_count for episode in episodes)} |
| deduplicated goal predicates | {sum(episode.goal_instance_count for episode in episodes)} |
| goal transitions written | {sum(episode.goal_transition_count for episode in episodes)} |
| goals already satisfied at init | {sum(episode.goal_already_satisfied_count for episode in episodes)} |
| exclusive placement invalidations | {sum(episode.invalidation_count for episode in episodes)} |
| duplicate predicate instances skipped | {sum(episode.duplicate_instance_count for episode in episodes)} |
| episodes whose final state satisfies all extracted goals | {len(episodes) - len(unsatisfied_episodes)} |
| goal-bearing episodes whose final state satisfies all extracted goals | {len(satisfied_goal_episodes)} |
| events containing symbolic goal variables | {len(symbolic_events)} |
| symbolic goal variable argument occurrences | {symbolic_argument_occurrences} |

## Event Types

{table_from_counter(event_type_counter, top_n)}

## Task Families

{table_from_counter(family_counter, top_n)}

## Event Predicates

{table_from_counter(predicate_counter, top_n)}

## Sample Events

{sample_event_table(all_events, 16)}

## 生成规则

1. `section=init` 的 predicate instance 被写成 `t=0` 的 `init_assert`。
2. `section=goal` 的 predicate instance 如果在当前状态下已经满足，则不写 no-op event，只计入 `goals already satisfied at init`。
3. 如果 goal 尚未满足，则从 `goal start time` 开始按固定步长写入 `goal_transition`。
4. 对 `inside / ontop / under / overlaid` 这类 placement relation，如果同一物体已有互斥位置关系为 True，会先写一条 `exclusive_relation_invalidation`，把旧关系置为 False。
5. BDDL goal 里的具体编号变量会规范化成真实对象，例如 `?hot_tub.n.02_1` 会变成 `hot_tub.n.02_1`。
6. BDDL goal 里的未编号量词变量会规范化成 stable symbolic placeholder，例如 `?comic_book.n.01` 会变成类似 `comic_book.n.01__goalvar_goal_00012_arg0`。原因是当前 Step 1 是扁平 predicate 抽取，没有保留 `forall / exists / forn / or / not` 的逻辑绑定；如果直接把所有 `?comic_book.n.01` 合成同一个 key，会制造假的冲突。
7. 对于 timeline 中没有显式出现过的状态，v0 暂时采用 closed-world default：默认值为 False。

## 边界

这是 synthetic timeline，只用于先跑通 benchmark 管线。它不等于真实机器人执行轨迹，也不等于 OmniGibson simulator truth。

它也不是完整的 BDDL 逻辑求解器。对包含复杂量词和析取条件的 goal，v0 只把扁平 predicate occurrence 转成可控状态事件。后续如果要更忠实地利用 BDDL goal semantics，需要在 Step 1 保留逻辑树，或者直接接入 simulator truth。

后续接入 simulator truth 后，这一步应该替换或扩展为：

```text
OmniGibson simulator states / action traces
  -> extracted ground-truth state timeline
```
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build synthetic ground-truth timelines for EviStateBench v0."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INSTANCE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--goal-start-time", type=float, default=10.0)
    parser.add_argument("--goal-step", type=float, default=5.0)
    parser.add_argument("--invalidation-gap", type=float, default=0.1)
    parser.add_argument("--top-n", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(
            f"Predicate instance file not found: {args.input}. "
            "Run tools/extract_task_predicate_instances.py first."
        )
    if args.goal_start_time < 0:
        raise ValueError("goal-start-time must be non-negative")
    if args.goal_step <= 0:
        raise ValueError("goal-step must be positive")
    if args.invalidation_gap < 0:
        raise ValueError("invalidation-gap must be non-negative")

    instances = load_instances(args.input)
    groups = group_by_task_file(instances)
    episodes = [
        build_episode_timeline(
            task_file_id=task_file_id,
            instances=groups[task_file_id],
            goal_start_time=args.goal_start_time,
            goal_step=args.goal_step,
            invalidation_gap=args.invalidation_gap,
        )
        for task_file_id in sorted(groups)
    ]

    write_events_jsonl(args.output, episodes)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            input_path=args.input,
            output_path=args.output,
            episodes=episodes,
            goal_start_time=args.goal_start_time,
            goal_step=args.goal_step,
            invalidation_gap=args.invalidation_gap,
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
                "episodes": len(episodes),
                "timeline_events": sum(len(episode.events) for episode in episodes),
                "episodes_final_goal_satisfied": sum(
                    episode.final_goal_satisfied for episode in episodes
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
