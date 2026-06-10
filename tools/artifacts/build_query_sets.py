#!/usr/bin/env python3
"""Build EviStateBench v0 query sets from hidden timelines and task specs.

This script implements Step 5 of the minimal pipeline:

hidden ground-truth timeline + extracted goal specs -> public query set

It does not generate answers.  Ground-truth answers are generated in Step 6 by
an oracle from the hidden timeline and, for bitemporal queries, from the chosen
observation stream.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.queries import (  # noqa: E402
    AsOfStateQuery,
    GoalQuery,
    StateDiffQuery,
    StateInstance,
    StateQuery,
)


DEFAULT_TIMELINE_PATH = (
    REPO_ROOT / "data" / "synthetic_ground_truth_timelines_v0.jsonl"
)
DEFAULT_GOAL_INSTANCE_PATH = (
    REPO_ROOT / "data" / "task_predicate_instances_v0.jsonl"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "query_sets_v0"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "query_sets_v0.md"


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One hidden timeline event used only for selecting query targets."""

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

    @property
    def state(self) -> StateInstance:
        return StateInstance(
            predicate_name=self.predicate_name,
            arguments=self.arguments,
        )


@dataclass(frozen=True, slots=True)
class GoalStateSpec:
    """One normalized goal predicate from the task specification."""

    predicate_name: str
    arguments: tuple[str, ...]
    desired_value: bool
    source_instance_id: str
    predicate_category: str

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        return (self.predicate_name, self.arguments)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "predicate_name": self.predicate_name,
            "arguments": list(self.arguments),
            "desired_value": self.desired_value,
            "predicate_category": self.predicate_category,
        }


def has_instance_suffix(argument: str) -> bool:
    """Return whether an argument looks like a concrete object instance."""
    return bool(re.search(r"_\d+$", argument))


def normalize_argument(argument: str, instance_id: str, argument_index: int) -> str:
    """Use the same flat goal-variable normalization as Step 2."""
    if not argument.startswith("?"):
        return argument

    stripped = argument[1:]
    if has_instance_suffix(stripped):
        return stripped

    occurrence_suffix = instance_id.split("__", maxsplit=2)[-1].replace("__", "_")
    return f"{stripped}__goalvar_{occurrence_suffix}_arg{argument_index}"


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
                )
            )
    return sorted(events, key=lambda event: (event.episode_id, event.event_time, event.event_index))


def load_goal_specs(path: Path) -> dict[str, list[GoalStateSpec]]:
    """Load and normalize BDDL goal predicate instances from Step 1."""
    goals_by_task_file: dict[str, list[GoalStateSpec]] = defaultdict(list)
    seen_by_task_file: dict[str, set[tuple[str, tuple[str, ...], bool]]] = defaultdict(set)
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["section"] != "goal":
                continue
            arguments = tuple(
                normalize_argument(argument, row["instance_id"], argument_index)
                for argument_index, argument in enumerate(row["arguments"])
            )
            key = (row["predicate_name"], arguments, bool(row["truth_value"]))
            task_file_id = row["task_file_id"]
            if key in seen_by_task_file[task_file_id]:
                continue
            seen_by_task_file[task_file_id].add(key)
            goals_by_task_file[task_file_id].append(
                GoalStateSpec(
                    predicate_name=row["predicate_name"],
                    arguments=arguments,
                    desired_value=bool(row["truth_value"]),
                    source_instance_id=row["instance_id"],
                    predicate_category=row["predicate_category"],
                )
            )
    return dict(goals_by_task_file)


def group_events_by_episode(
    events: list[TimelineEvent],
) -> dict[str, list[TimelineEvent]]:
    grouped: dict[str, list[TimelineEvent]] = defaultdict(list)
    for event in events:
        grouped[event.episode_id].append(event)
    return dict(grouped)


def query_dict(query: StateQuery | AsOfStateQuery | StateDiffQuery | GoalQuery) -> dict[str, Any]:
    return query.to_dict()


def safe_time_label(value: float) -> str:
    label = f"{value:.6f}".rstrip("0").rstrip(".")
    label = label or "0"
    return re.sub(r"[^0-9a-zA-Z]+", "_", label)


def make_check_query(event: TimelineEvent, index: int) -> StateQuery:
    return StateQuery(
        query_id=f"{event.episode_id}__q_check_state_{index:05d}",
        episode_id=event.episode_id,
        task_id=event.task_id,
        state=event.state,
        valid_time=event.event_time,
        metadata={
            "query_family": "event_state_probe",
            "task_file_id": event.task_file_id,
            "task_family": event.task_family,
            "target_event_time": event.event_time,
        },
    )


def make_asof_queries(
    event: TimelineEvent,
    index: int,
    before_gap: float,
    after_gap: float,
) -> list[AsOfStateQuery]:
    if event.event_time <= 0.0:
        return []
    before_transaction_time = max(0.0, event.event_time - before_gap)
    after_transaction_time = event.event_time + after_gap
    return [
        AsOfStateQuery(
            query_id=f"{event.episode_id}__q_asof_before_{index:05d}",
            episode_id=event.episode_id,
            task_id=event.task_id,
            state=event.state,
            valid_time=event.event_time,
            transaction_time=round(before_transaction_time, 6),
            metadata={
                "query_family": "asof_before_observation_window",
                "task_file_id": event.task_file_id,
                "task_family": event.task_family,
                "time_probe": "before",
            },
        ),
        AsOfStateQuery(
            query_id=f"{event.episode_id}__q_asof_after_{index:05d}",
            episode_id=event.episode_id,
            task_id=event.task_id,
            state=event.state,
            valid_time=event.event_time,
            transaction_time=round(after_transaction_time, 6),
            metadata={
                "query_family": "asof_after_observation_window",
                "task_file_id": event.task_file_id,
                "task_family": event.task_family,
                "time_probe": "after",
            },
        ),
    ]


def make_diff_query(episode_events: list[TimelineEvent], index: int) -> StateDiffQuery | None:
    first = episode_events[0]
    final_time = max(event.event_time for event in episode_events)
    if final_time <= 0.0:
        return None
    return StateDiffQuery(
        query_id=f"{first.episode_id}__q_state_diff_{index:05d}",
        episode_id=first.episode_id,
        task_id=first.task_id,
        scope="task",
        t1=0.0,
        t2=final_time,
        predicate_filter=(),
        metadata={
            "query_family": "full_episode_diff",
            "task_file_id": first.task_file_id,
            "task_family": first.task_family,
            "window": "t0_to_final_time",
        },
    )


def make_goal_queries(
    episode_events: list[TimelineEvent],
    goal_specs: list[GoalStateSpec],
    index: int,
) -> list[GoalQuery]:
    if not goal_specs:
        return []
    first = episode_events[0]
    final_time = max(event.event_time for event in episode_events)
    goal_metadata = {
        "query_family": "task_goal_view",
        "task_file_id": first.task_file_id,
        "task_family": first.task_family,
        "goal_state_count": len(goal_specs),
        "goal_states": [goal.to_public_dict() for goal in goal_specs],
    }
    queries = [
        GoalQuery(
            query_id=f"{first.episode_id}__q_check_goal_t0_{index:05d}",
            episode_id=first.episode_id,
            task_id=first.task_id,
            valid_time=0.0,
            transaction_time=None,
            metadata={**goal_metadata, "time_probe": "initial"},
        )
    ]
    if final_time > 0.0:
        queries.append(
            GoalQuery(
                query_id=f"{first.episode_id}__q_check_goal_final_{index:05d}",
                episode_id=first.episode_id,
                task_id=first.task_id,
                valid_time=final_time,
                transaction_time=None,
                metadata={**goal_metadata, "time_probe": "final"},
            )
        )
    return queries


def build_queries(
    events: list[TimelineEvent],
    goals_by_task_file: dict[str, list[GoalStateSpec]],
    *,
    asof_before_gap: float,
    asof_after_gap: float,
) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, event in enumerate(events, start=1):
        queries.append(query_dict(make_check_query(event, index)))
        if event.event_type != "init_assert":
            for asof_query in make_asof_queries(
                event,
                index,
                before_gap=asof_before_gap,
                after_gap=asof_after_gap,
            ):
                queries.append(query_dict(asof_query))

    events_by_episode = group_events_by_episode(events)
    for index, episode_id in enumerate(sorted(events_by_episode), start=1):
        episode_events = events_by_episode[episode_id]
        diff_query = make_diff_query(episode_events, index)
        if diff_query is not None:
            queries.append(query_dict(diff_query))

        task_file_id = episode_events[0].task_file_id
        for goal_query in make_goal_queries(
            episode_events,
            goals_by_task_file.get(task_file_id, []),
            index,
        ):
            queries.append(query_dict(goal_query))

    return queries


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def validate_query_row(row: dict[str, Any]) -> None:
    """Validate a serialized query row against the public query schema."""
    query_type = row["query_type"]
    if query_type in {"CHECK_STATE", "AS_OF_STATE"}:
        state = StateInstance(**row["state"])
        payload = dict(row)
        payload["state"] = state
        if query_type == "CHECK_STATE":
            StateQuery(**{k: v for k, v in payload.items() if k != "query_type"})
        else:
            AsOfStateQuery(**{k: v for k, v in payload.items() if k != "query_type"})
    elif query_type == "STATE_DIFF":
        StateDiffQuery(**{k: v for k, v in row.items() if k != "query_type"})
    elif query_type == "CHECK_GOAL":
        GoalQuery(**{k: v for k, v in row.items() if k != "query_type"})
    else:
        raise ValueError(f"Unsupported query_type in v0 generator: {query_type}")


def write_manifest(
    path: Path,
    *,
    timeline_path: Path,
    goal_instance_path: Path,
    output_path: Path,
    queries: list[dict[str, Any]],
    asof_before_gap: float,
    asof_after_gap: float,
) -> None:
    counter = Counter(row["query_type"] for row in queries)
    manifest = {
        "timeline_path": str(timeline_path),
        "goal_instance_path": str(goal_instance_path),
        "query_set_path": str(output_path),
        "query_count": len(queries),
        "query_type_counts": dict(counter),
        "asof_before_gap": asof_before_gap,
        "asof_after_gap": asof_after_gap,
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def table_from_counter(counter: Counter[str], limit: int) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common(limit):
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def sample_table(queries: list[dict[str, Any]], limit: int) -> str:
    lines = [
        "| query_type | query_id | episode | state/scope | time |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in queries[:limit]:
        query_type = row["query_type"]
        if "state" in row:
            state = row["state"]
            args = ", ".join(state["arguments"])
            target = f"{state['predicate_name']}({args})"
        else:
            target = row.get("scope", "goal")
        if query_type == "STATE_DIFF":
            time_text = f"{row['t1']} -> {row['t2']}"
        elif query_type == "AS_OF_STATE":
            time_text = f"valid={row['valid_time']}, tx={row['transaction_time']}"
        else:
            time_text = f"valid={row['valid_time']}"
        lines.append(
            f"| `{query_type}` | `{row['query_id']}` | `{row['episode_id']}` | "
            f"`{target}` | {time_text} |"
        )
    if len(lines) == 2:
        lines.append("| n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(
    *,
    timeline_path: Path,
    goal_instance_path: Path,
    output_path: Path,
    manifest_path: Path,
    events: list[TimelineEvent],
    goals_by_task_file: dict[str, list[GoalStateSpec]],
    queries: list[dict[str, Any]],
    asof_before_gap: float,
    asof_after_gap: float,
    top_n: int,
) -> str:
    query_type_counter = Counter(row["query_type"] for row in queries)
    task_family_counter = Counter(event.task_family for event in events)
    goal_task_count = sum(1 for goals in goals_by_task_file.values() if goals)
    goal_state_count = sum(len(goals) for goals in goals_by_task_file.values())

    return f"""# Query Set v0

本报告由 `tools/artifacts/build_query_sets.py` 生成。

它对应最小验证计划的第 5 步：

```text
生成 CHECK_STATE / AS_OF_STATE / STATE_DIFF / CHECK_GOAL query set
```

这里生成的是 public query set，不包含标准答案。标准答案会在 Step 6 中由 hidden timeline / oracle 生成。

## 配置

| item | value |
| --- | --- |
| input timeline events | `{timeline_path}` |
| input goal predicate instances | `{goal_instance_path}` |
| output query set | `{output_path}` |
| manifest | `{manifest_path}` |
| AS_OF before gap | {asof_before_gap:g} |
| AS_OF after gap | {asof_after_gap:g} |

## 总览

| item | count |
| --- | ---: |
| timeline events | {len(events)} |
| task files with goal specs | {goal_task_count} |
| normalized goal states | {goal_state_count} |
| queries | {len(queries)} |

## Query Types

{table_from_counter(query_type_counter, top_n)}

## Task Families

{table_from_counter(task_family_counter, top_n)}

## Sample Queries

{sample_table(queries, 16)}

## 生成规则

1. 每条 hidden timeline event 生成一个 `CHECK_STATE` query。
2. 每条非 `init_assert` event 生成两个 `AS_OF_STATE` query：一个 transaction_time 在事件前，一个在事件后。
3. 每个 final_time > 0 的 episode 生成一个 `STATE_DIFF(scope=task, t1=0, t2=final_time)` query。
4. 每个有 BDDL goal specs 的 episode 生成 `CHECK_GOAL(t=0)`；如果 final_time > 0，再生成 `CHECK_GOAL(t=final_time)`。
5. `CHECK_GOAL` query 的 metadata 中包含 goal predicate specs。这是任务规格，不是答案；系统需要知道目标条件才能判断任务是否完成。

## 边界

这个 query set 可以和 clean / perturbed observation streams 配套使用。

`AS_OF_STATE` 的标准答案在 Step 6 里要特别小心：如果评测的是 bitemporal information availability，它可能需要按不同 observation stream 的 arrival_time 分别生成；如果评测的是 pure world truth，则只依赖 hidden timeline。第一版 oracle 需要明确采用哪一种语义。

v0 暂时没有生成 `WHY_STATE` query，因为 WHY 的 evidence correctness metric 需要单独定义。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build EviStateBench v0 query set.")
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE_PATH)
    parser.add_argument("--goal-instances", type=Path, default=DEFAULT_GOAL_INSTANCE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--asof-before-gap", type=float, default=0.1)
    parser.add_argument("--asof-after-gap", type=float, default=30.0)
    parser.add_argument("--top-n", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.timeline.exists():
        raise FileNotFoundError(
            f"Timeline file not found: {args.timeline}. "
            "Run tools/build_synthetic_timelines.py first."
        )
    if not args.goal_instances.exists():
        raise FileNotFoundError(
            f"Goal instance file not found: {args.goal_instances}. "
            "Run tools/extract_task_predicate_instances.py first."
        )
    if args.asof_before_gap < 0:
        raise ValueError("asof-before-gap must be non-negative")
    if args.asof_after_gap <= 0:
        raise ValueError("asof-after-gap must be positive")

    events = load_timeline_events(args.timeline)
    goals_by_task_file = load_goal_specs(args.goal_instances)
    queries = build_queries(
        events,
        goals_by_task_file,
        asof_before_gap=args.asof_before_gap,
        asof_after_gap=args.asof_after_gap,
    )
    for row in queries:
        validate_query_row(row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "queries.jsonl"
    manifest_path = args.output_dir / "manifest.json"
    write_jsonl(output_path, queries)
    write_manifest(
        manifest_path,
        timeline_path=args.timeline,
        goal_instance_path=args.goal_instances,
        output_path=output_path,
        queries=queries,
        asof_before_gap=args.asof_before_gap,
        asof_after_gap=args.asof_after_gap,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            timeline_path=args.timeline,
            goal_instance_path=args.goal_instances,
            output_path=output_path,
            manifest_path=manifest_path,
            events=events,
            goals_by_task_file=goals_by_task_file,
            queries=queries,
            asof_before_gap=args.asof_before_gap,
            asof_after_gap=args.asof_after_gap,
            top_n=args.top_n,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "timeline": str(args.timeline),
                "goal_instances": str(args.goal_instances),
                "output": str(output_path),
                "manifest": str(manifest_path),
                "report": str(args.report),
                "queries": len(queries),
                "query_type_counts": dict(Counter(row["query_type"] for row in queries)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
