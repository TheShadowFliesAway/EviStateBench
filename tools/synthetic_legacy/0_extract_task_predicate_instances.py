#!/usr/bin/env python3
"""Extract BDDL init/goal predicate instances for EviStateBench v0.

This script is the first concrete generator step:

BDDL task specification -> predicate instances -> synthetic timeline generator.

It does not create StateObservation streams yet.  It only extracts the state
instances that BDDL explicitly mentions in :init and :goal sections.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.schema import (  # noqa: E402
    CONTEXT_PREDICATES_V0,
    CORE_STATE_PREDICATES_V0,
    PREDICATE_CATEGORY_V0,
    RUNTIME_EXTENSION_PREDICATES_V0,
)
from tools.audit_bddl_tasks import (  # noqa: E402
    DEFAULT_BDDL_ROOT,
    DEFAULT_DOMAIN,
    PredicateOccurrence,
    categorize_predicate,
    categorize_task_family,
    parse_domain_predicates,
    parse_task,
)


SELECTED_TASK_FAMILIES_V0 = (
    "cleaning / washing",
    "cooking / food preparation",
    "storage / organization / packing",
    "liquid / material transfer",
    "assembly / setup",
)


@dataclass(frozen=True, slots=True)
class TaskPredicateInstance:
    """A predicate instance extracted from a BDDL task file.

    This is not an observation.  It is task-spec truth material:
    - :init instances can seed the initial ground-truth timeline.
    - :goal instances can seed target-state queries and oracle answers.
    """

    instance_id: str
    task_id: str
    task_file_id: str
    task_family: str
    source_file: str
    section: str
    predicate_name: str
    arguments: tuple[str, ...]
    truth_value: bool
    bddl_polarity: str
    predicate_role: str
    predicate_category: str
    synthetic_role: str
    domain_arity: int | None

    @property
    def state_key(self) -> tuple[str, tuple[str, ...]]:
        return (self.predicate_name, self.arguments)

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["arguments"] = list(self.arguments)
        record["state_key"] = [self.predicate_name, list(self.arguments)]
        return record


def predicate_role(name: str) -> str:
    """Map a predicate into the v0 benchmark role used by extraction filters."""
    if name in CORE_STATE_PREDICATES_V0:
        return "core_state"
    if name in CONTEXT_PREDICATES_V0:
        return "context"
    if name in RUNTIME_EXTENSION_PREDICATES_V0:
        return "runtime_extension"
    return "other"


def should_include_role(role: str, predicate_scope: str) -> bool:
    """Return whether a predicate role should be written to the JSONL output."""
    if predicate_scope == "all":
        return True
    if predicate_scope == "core+context":
        return role in {"core_state", "context"}
    return role == "core_state"


def has_agent_argument(instance: TaskPredicateInstance) -> bool:
    """Return whether the instance talks about the embodied agent itself."""
    return any(
        argument.startswith("agent.") or argument.startswith("?agent.")
        for argument in instance.arguments
    )


def make_instance_id(
    task_name: str,
    problem_stem: str,
    section: str,
    occurrence_index: int,
) -> str:
    """Create a stable id that survives re-running the extractor."""
    return f"{task_name}__{problem_stem}__{section}__{occurrence_index:05d}"


def occurrence_to_instance(
    occurrence: PredicateOccurrence,
    occurrence_index: int,
    task_name: str,
    task_path: Path,
    task_family: str,
    domain_predicates: dict[str, int],
) -> TaskPredicateInstance:
    """Convert one parsed BDDL predicate occurrence into the output schema."""
    role = predicate_role(occurrence.name)
    domain_arity = domain_predicates.get(occurrence.name)
    category = PREDICATE_CATEGORY_V0.get(
        occurrence.name,
        categorize_predicate(occurrence.name, domain_arity),
    )
    problem_stem = task_path.stem
    section = occurrence.section
    return TaskPredicateInstance(
        instance_id=make_instance_id(task_name, problem_stem, section, occurrence_index),
        task_id=task_name,
        task_file_id=f"{task_name}/{problem_stem}",
        task_family=task_family,
        source_file=str(task_path),
        section=section,
        predicate_name=occurrence.name,
        arguments=tuple(occurrence.args),
        truth_value=occurrence.polarity == "positive",
        bddl_polarity=occurrence.polarity,
        predicate_role=role,
        predicate_category=category,
        synthetic_role=(
            "initial_truth_seed" if section == "init" else "goal_condition_seed"
        ),
        domain_arity=domain_arity,
    )


def iter_instances(
    bddl_root: Path,
    domain_path: Path,
    selected_families: set[str],
    include_all_families: bool,
) -> tuple[list[TaskPredicateInstance], dict[str, Any]]:
    """Parse BDDL tasks and return all extracted predicate instances.

    Filtering by predicate role happens later so that the report can still
    explain what was excluded.
    """
    domain_predicates = parse_domain_predicates(domain_path)
    predicate_names = set(domain_predicates)
    task_files = sorted(bddl_root.glob("*/problem*.bddl"))

    instances: list[TaskPredicateInstance] = []
    scanned_task_count = 0
    selected_task_count = 0

    for task_path in task_files:
        scanned_task_count += 1
        task_name = task_path.parent.name
        task_family = categorize_task_family(task_name)
        if not include_all_families and task_family not in selected_families:
            continue

        selected_task_count += 1
        task = parse_task(task_path, predicate_names)
        occurrences = [*task.init_occurrences, *task.goal_occurrences]
        for occurrence_index, occurrence in enumerate(occurrences, start=1):
            instances.append(
                occurrence_to_instance(
                    occurrence=occurrence,
                    occurrence_index=occurrence_index,
                    task_name=task.task_name,
                    task_path=task_path,
                    task_family=task_family,
                    domain_predicates=domain_predicates,
                )
            )

    metadata = {
        "bddl_root": str(bddl_root),
        "domain_path": str(domain_path),
        "scanned_task_count": scanned_task_count,
        "selected_task_count": selected_task_count,
        "domain_predicate_count": len(domain_predicates),
        "selected_families": sorted(selected_families),
        "include_all_families": include_all_families,
    }
    return instances, metadata


def table_from_counter(counter: Counter[str], limit: int) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for item, count in counter.most_common(limit):
        lines.append(f"| `{item}` | {count} |")
    if len(lines) == 2:
        lines.append("| n/a | 0 |")
    return "\n".join(lines)


def sample_table(instances: list[TaskPredicateInstance], limit: int) -> str:
    lines = [
        "| task | section | predicate | value | arguments | family |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for instance in instances[:limit]:
        args = ", ".join(f"`{arg}`" for arg in instance.arguments)
        lines.append(
            f"| `{instance.task_id}` | {instance.section} | "
            f"`{instance.predicate_name}` | {instance.truth_value} | "
            f"{args} | {instance.task_family} |"
        )
    if len(lines) == 2:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def build_report(
    *,
    output_path: Path,
    metadata: dict[str, Any],
    all_instances: list[TaskPredicateInstance],
    role_filtered_instances: list[TaskPredicateInstance],
    included_instances: list[TaskPredicateInstance],
    predicate_scope: str,
    include_agent_states: bool,
    top_n: int,
) -> str:
    """Build a human-readable extraction summary."""
    all_role_counter = Counter(instance.predicate_role for instance in all_instances)
    included_family_counter = Counter(
        instance.task_family for instance in included_instances
    )
    included_section_counter = Counter(instance.section for instance in included_instances)
    included_predicate_counter = Counter(
        instance.predicate_name for instance in included_instances
    )
    scope_excluded_role_counter = all_role_counter.copy()
    scope_excluded_role_counter.subtract(
        Counter(instance.predicate_role for instance in role_filtered_instances)
    )
    scope_excluded_role_counter = Counter(
        {
            role: count
            for role, count in scope_excluded_role_counter.items()
            if count > 0
        }
    )
    agent_excluded_instances = [
        instance for instance in role_filtered_instances if has_agent_argument(instance)
    ]
    agent_excluded_predicate_counter = Counter(
        instance.predicate_name for instance in agent_excluded_instances
    )
    agent_excluded_count = len(agent_excluded_instances)

    return f"""# Task Predicate Instances v0

本报告由 `tools/extract_task_predicate_instances.py` 生成。

它对应最小验证计划的第 1 步：

```text
从 BDDL init / goal 抽 predicate instances
```

这里抽出来的不是 observation，也不是 EviStateDB 的内部 view。它们是从任务规格中显式出现的状态实例，用于后续构造 synthetic ground-truth timeline、clean observations、query set 和 ground-truth answers。

## 配置

| item | value |
| --- | --- |
| BDDL root | `{metadata["bddl_root"]}` |
| domain file | `{metadata["domain_path"]}` |
| scanned task files | {metadata["scanned_task_count"]} |
| selected task files | {metadata["selected_task_count"]} |
| include all families | {metadata["include_all_families"]} |
| predicate scope | `{predicate_scope}` |
| include agent states | {include_agent_states} |
| JSONL output | `{output_path}` |

默认只保留 v0 representative task families：

```text
{chr(10).join(metadata["selected_families"])}
```

## 总览

| item | count |
| --- | ---: |
| extracted predicate occurrences before predicate-scope filter | {len(all_instances)} |
| after predicate-scope filter | {len(role_filtered_instances)} |
| excluded by agent-state filter | {agent_excluded_count} |
| written predicate instances | {len(included_instances)} |

## Included Task Families

{table_from_counter(included_family_counter, top_n)}

## Included Sections

{table_from_counter(included_section_counter, top_n)}

## Included Predicates

{table_from_counter(included_predicate_counter, top_n)}

## Predicate Roles Before Filter

{table_from_counter(all_role_counter, top_n)}

## Excluded By Predicate Scope

{table_from_counter(scope_excluded_role_counter, top_n)}

## Agent-State Filter

默认不写入 `agent.*` 参数相关的 predicate instance。原因是 BDDL init 中几乎每个 task 都有 `ontop(agent, floor)`，它是机器人初始位置/context，不是第一版 object task-state workload 的核心对象。

| item | count |
| --- | ---: |
| excluded agent-state instances | {agent_excluded_count} |

{table_from_counter(agent_excluded_predicate_counter, top_n)}

如需保留这类状态，可运行：

```bash
python tools/extract_task_predicate_instances.py --include-agent-states
```

## Sample Instances

{sample_table(included_instances, 12)}

## 后续用途

这些 predicate instances 会进入下一步 generator：

```text
1. :init instance  -> 初始 ground-truth state
2. :goal instance  -> goal query / oracle answer 的目标条件
3. synthetic update -> 构造状态变化 timeline
4. perturbation    -> 生成 delay / missing / conflict observations
```

注意：BDDL goal 只告诉我们目标应该满足什么，不等于真实 episode 中某个时间点已经满足。后续 oracle 需要根据 synthetic timeline 或 simulator truth 来回答 query。
"""


def write_jsonl(path: Path, instances: list[TaskPredicateInstance]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for instance in instances:
            f.write(json.dumps(instance.to_dict(), ensure_ascii=False, sort_keys=True))
            f.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract v0 BDDL predicate instances for EviStateBench."
    )
    parser.add_argument("--bddl-root", type=Path, default=DEFAULT_BDDL_ROOT)
    parser.add_argument("--domain", type=Path, default=DEFAULT_DOMAIN)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "task_predicate_instances_v0.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / "reports" / "task_predicate_instances_v0.md",
    )
    parser.add_argument(
        "--predicate-scope",
        choices=("core", "core+context", "all"),
        default="core",
        help="Which predicate roles to write to JSONL.",
    )
    parser.add_argument(
        "--families",
        nargs="*",
        default=list(SELECTED_TASK_FAMILIES_V0),
        help="Representative task families to include unless --all-families is set.",
    )
    parser.add_argument(
        "--all-families",
        action="store_true",
        help="Include every audited BDDL task family.",
    )
    parser.add_argument(
        "--include-agent-states",
        action="store_true",
        help="Keep predicate instances whose arguments mention agent.*.",
    )
    parser.add_argument("--top-n", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.bddl_root.exists():
        raise FileNotFoundError(f"BDDL root not found: {args.bddl_root}")
    if not args.domain.exists():
        raise FileNotFoundError(f"Domain file not found: {args.domain}")

    selected_families = set(args.families)
    all_instances, metadata = iter_instances(
        bddl_root=args.bddl_root,
        domain_path=args.domain,
        selected_families=selected_families,
        include_all_families=args.all_families,
    )
    role_filtered_instances = [
        instance
        for instance in all_instances
        if should_include_role(instance.predicate_role, args.predicate_scope)
    ]
    included_instances = [
        instance
        for instance in role_filtered_instances
        if args.include_agent_states or not has_agent_argument(instance)
    ]

    write_jsonl(args.output, included_instances)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(
            output_path=args.output,
            metadata=metadata,
            all_instances=all_instances,
            role_filtered_instances=role_filtered_instances,
            included_instances=included_instances,
            predicate_scope=args.predicate_scope,
            include_agent_states=args.include_agent_states,
            top_n=args.top_n,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(args.output),
                "report": str(args.report),
                "scanned_task_count": metadata["scanned_task_count"],
                "selected_task_count": metadata["selected_task_count"],
                "written_instances": len(included_instances),
                "agent_state_instances_excluded": len(role_filtered_instances)
                - len(included_instances),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
