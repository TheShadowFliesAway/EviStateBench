#!/usr/bin/env python3
"""Audit BEHAVIOR BDDL tasks for EviStateBench task-state design."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_BDDL_ROOT = Path(
    "/root/autodl-tmp/BEHAVIOR-1K/bddl3/bddl/activity_definitions"
)
DEFAULT_DOMAIN = DEFAULT_BDDL_ROOT / "domain_omnigibson.bddl"

LOGICAL_FORMS = {
    "and",
    "or",
    "not",
    "exists",
    "forall",
    "imply",
    "implies",
    "when",
    "forn",
    "forpairs",
    "fornpairs",
    "for-pairs",
    "for-n-pairs",
}

TAXONOMY_HINTS = {
    "BDDL bookkeeping / source marker": {
        "real",
        "future",
        "insource",
    },
    "binary spatial / containment relation": {
        "inside",
        "ontop",
        "under",
        "nextto",
        "touching",
        "overlaid",
        "inroom",
    },
    "material / particle state": {
        "covered",
        "saturated",
        "filled",
        "contains",
    },
    "robot / agent interaction state": {
        "grasped",
        "holding",
        "inhand",
    },
    "object unary state": {
        "open",
        "cooked",
        "frozen",
        "heated",
        "sliced",
        "folded",
        "stained",
        "dusty",
        "burnt",
        "toggled_on",
        "broken",
        "soaked",
    },
}

TASK_FAMILY_RULES = {
    "cleaning / washing": (
        "clean",
        "wash",
        "wipe",
        "rinse",
        "scrub",
        "sanitize",
        "disinfect",
        "sweep",
        "mop",
    ),
    "cooking / food preparation": (
        "cook",
        "bake",
        "boil",
        "chop",
        "slice",
        "brew",
        "toast",
        "prepare",
        "can_",
        "canning",
    ),
    "storage / organization / packing": (
        "put",
        "pack",
        "box",
        "store",
        "organize",
        "sort",
        "arrange",
        "bring",
        "carry",
    ),
    "shopping / acquisition": (
        "buy",
        "buying",
        "shop",
        "gather",
        "collect",
    ),
    "liquid / material transfer": (
        "fill",
        "pour",
        "water",
        "adding_chemicals",
        "chlorinating",
        "bottling",
    ),
    "assembly / setup": (
        "assemble",
        "assembling",
        "attach",
        "install",
        "changing",
    ),
}


@dataclass
class PredicateOccurrence:
    name: str
    args: list[str]
    polarity: str
    section: str


@dataclass
class TaskAudit:
    task_name: str
    path: str
    object_type_count: Counter[str] = field(default_factory=Counter)
    init_occurrences: list[PredicateOccurrence] = field(default_factory=list)
    goal_occurrences: list[PredicateOccurrence] = field(default_factory=list)


def scan_tokens(path: Path) -> list[Any]:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r";.*$", "", raw, flags=re.MULTILINE).lower()
    stack: list[list[Any]] = []
    tokens: list[Any] = []
    for token in re.findall(r"[()]|[^\s()]+", raw):
        if token == "(":
            stack.append(tokens)
            tokens = []
        elif token == ")":
            if not stack:
                raise ValueError(f"Missing open parenthesis in {path}")
            expr = tokens
            tokens = stack.pop()
            tokens.append(expr)
        else:
            tokens.append(token)
    if stack:
        raise ValueError(f"Missing close parenthesis in {path}")
    if len(tokens) != 1:
        raise ValueError(f"Malformed expression in {path}")
    return tokens[0]


def parse_domain_predicates(domain_path: Path) -> dict[str, int]:
    tokens = scan_tokens(domain_path)
    predicates: dict[str, int] = {}
    for group in tokens:
        if isinstance(group, list) and group and group[0] == ":predicates":
            for pred in group[1:]:
                if isinstance(pred, list) and pred:
                    variables = [x for x in pred[1:] if x.startswith("?")]
                    predicates[pred[0]] = len(variables)
    return predicates


def parse_objects(group: list[Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    current_objects: list[str] = []
    i = 1
    while i < len(group):
        item = group[i]
        if item == "-":
            if i + 1 < len(group):
                obj_type = group[i + 1]
                counts[obj_type] += len(current_objects)
                current_objects = []
                i += 2
                continue
        current_objects.append(item)
        i += 1
    if current_objects:
        counts["object"] += len(current_objects)
    return counts


def extract_predicates(
    expr: Any,
    predicate_names: set[str],
    section: str,
    polarity: str = "positive",
) -> list[PredicateOccurrence]:
    occurrences: list[PredicateOccurrence] = []
    if not isinstance(expr, list) or not expr:
        return occurrences

    head = expr[0]
    if head == "not" and len(expr) > 1:
        occurrences.extend(
            extract_predicates(expr[1], predicate_names, section, "negative")
        )
        return occurrences

    if isinstance(head, str) and head in predicate_names:
        args = [str(arg) for arg in expr[1:] if not isinstance(arg, list)]
        occurrences.append(PredicateOccurrence(head, args, polarity, section))
        return occurrences

    if isinstance(head, str) and head in LOGICAL_FORMS:
        for child in expr[1:]:
            occurrences.extend(
                extract_predicates(child, predicate_names, section, polarity)
            )
        return occurrences

    for child in expr:
        occurrences.extend(extract_predicates(child, predicate_names, section, polarity))
    return occurrences


def parse_task(path: Path, predicate_names: set[str]) -> TaskAudit:
    tokens = scan_tokens(path)
    task = TaskAudit(task_name=path.parent.name, path=str(path))
    for group in tokens:
        if not isinstance(group, list) or not group:
            continue
        head = group[0]
        if head == ":objects":
            task.object_type_count = parse_objects(group)
        elif head == ":init":
            for expr in group[1:]:
                task.init_occurrences.extend(
                    extract_predicates(expr, predicate_names, "init")
                )
        elif head == ":goal" and len(group) > 1:
            task.goal_occurrences.extend(
                extract_predicates(group[1], predicate_names, "goal")
            )
    return task


def categorize_predicate(name: str, arity: int | None = None) -> str:
    for category, names in TAXONOMY_HINTS.items():
        if name in names:
            return category
    if arity == 1:
        return "object unary state"
    if arity == 2:
        return "binary relation"
    return "other / needs inspection"


def categorize_task_family(task_name: str) -> str:
    for family, prefixes in TASK_FAMILY_RULES.items():
        if any(task_name.startswith(prefix) or f"_{prefix}" in task_name for prefix in prefixes):
            return family
    return "other / mixed"


def top_table(counter: Counter[str], limit: int) -> str:
    lines = ["| item | count |", "| --- | ---: |"]
    for key, count in counter.most_common(limit):
        lines.append(f"| `{key}` | {count} |")
    return "\n".join(lines)


def build_report(
    bddl_root: Path,
    domain_path: Path,
    domain_predicates: dict[str, int],
    tasks: list[TaskAudit],
    top_n: int,
) -> str:
    init_counter: Counter[str] = Counter()
    goal_counter: Counter[str] = Counter()
    all_counter: Counter[str] = Counter()
    init_task_counter: Counter[str] = Counter()
    goal_task_counter: Counter[str] = Counter()
    arity_counter: Counter[str] = Counter()
    polarity_counter: Counter[str] = Counter()
    object_type_counter: Counter[str] = Counter()
    taxonomy_counter: Counter[str] = Counter()
    family_counter: Counter[str] = Counter()
    family_predicates: dict[str, Counter[str]] = defaultdict(Counter)

    for task in tasks:
        object_type_counter.update(task.object_type_count)
        family = categorize_task_family(task.task_name)
        family_counter[family] += 1

        init_names = {occ.name for occ in task.init_occurrences}
        goal_names = {occ.name for occ in task.goal_occurrences}
        init_task_counter.update(init_names)
        goal_task_counter.update(goal_names)

        for occ in task.init_occurrences:
            init_counter[occ.name] += 1
            all_counter[occ.name] += 1
            arity_counter[str(len(occ.args))] += 1
            polarity_counter[f"init/{occ.polarity}"] += 1
            taxonomy_counter[categorize_predicate(occ.name, len(occ.args))] += 1
            family_predicates[family][occ.name] += 1

        for occ in task.goal_occurrences:
            goal_counter[occ.name] += 1
            all_counter[occ.name] += 1
            arity_counter[str(len(occ.args))] += 1
            polarity_counter[f"goal/{occ.polarity}"] += 1
            taxonomy_counter[categorize_predicate(occ.name, len(occ.args))] += 1
            family_predicates[family][occ.name] += 1

    unique_predicates = set(all_counter)
    goal_only = set(goal_counter) - set(init_counter)
    init_only = set(init_counter) - set(goal_counter)
    domain_not_observed = set(domain_predicates) - unique_predicates

    family_lines = [
        "| family | task count | top predicates |",
        "| --- | ---: | --- |",
    ]
    for family, count in family_counter.most_common():
        top_preds = ", ".join(
            f"`{name}`({pred_count})"
            for name, pred_count in family_predicates[family].most_common(6)
        )
        family_lines.append(f"| {family} | {count} | {top_preds} |")

    taxonomy_lines = [
        "| predicate | domain arity | observed category | total occurrences | goal occurrences |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for name, count in all_counter.most_common(top_n):
        domain_arity = domain_predicates.get(name)
        observed_arity = domain_arity if domain_arity is not None else None
        category = categorize_predicate(name, observed_arity)
        taxonomy_lines.append(
            f"| `{name}` | {domain_arity if domain_arity is not None else 'n/a'} | "
            f"{category} | {count} | {goal_counter[name]} |"
        )

    candidate_family_lines = [
        "1. cleaning / washing: 高频、任务数量大，适合覆盖 object unary state 与 material / particle state。",
        "2. cooking / food preparation: 适合覆盖 temperature-like、cooked/sliced/frozen 等对象状态，后续可结合 simulator object states 扩展。",
        "3. storage / organization / packing: 适合覆盖 `inside`、`ontop`、`open`、`inroom` 等空间和容器状态。",
        "4. liquid / material transfer: 适合覆盖 `filled`、`covered`、`saturated`、`contains` 等物质状态。",
        "5. assembly / setup: 适合检查接触、空间关系和目标条件组合。",
    ]

    report = f"""# BDDL Task Audit Report

本报告由 `tools/synthetic_legacy/audit_bddl_tasks.py` 生成，用于 EviStateBench Phase 1：从 BEHAVIOR/BDDL 任务定义反推 task-state space。

## 数据来源

```text
BDDL root: {bddl_root}
domain file: {domain_path}
```

## 总览

| item | value |
| --- | ---: |
| task files | {len(tasks)} |
| domain predicates | {len(domain_predicates)} |
| predicates observed in init/goal | {len(unique_predicates)} |
| predicates observed only in init | {len(init_only)} |
| predicates observed only in goal | {len(goal_only)} |
| domain predicates not observed in init/goal | {len(domain_not_observed)} |
| init predicate occurrences | {sum(init_counter.values())} |
| goal predicate occurrences | {sum(goal_counter.values())} |

Domain predicates not observed in init/goal:

```text
{", ".join(sorted(domain_not_observed)) if domain_not_observed else "None"}
```

## 高频 Predicate

### 全部 init + goal

{top_table(all_counter, top_n)}

### Initial Conditions

{top_table(init_counter, top_n)}

### Goal Conditions

{top_table(goal_counter, top_n)}

### 按任务计数的 Goal Predicate

这里统计的是“有多少个 task 的 goal 里出现过该 predicate”，不是 occurrence 总数。

{top_table(goal_task_counter, top_n)}

## Arity / Polarity / Taxonomy

### Predicate Arity Distribution

{top_table(arity_counter, top_n)}

### Predicate Polarity Distribution

{top_table(polarity_counter, top_n)}

### Predicate Taxonomy 初版

{top_table(taxonomy_counter, top_n)}

### 高频 Predicate 分类表

{chr(10).join(taxonomy_lines)}

## Object Type 分布

{top_table(object_type_counter, top_n)}

## Task Family 初筛

{chr(10).join(family_lines)}

## 建议优先选择的 3-5 类任务族

{chr(10).join(candidate_family_lines)}

## 对 EviStateBench 的含义

从这次审计可以先得到几个直接结论：

1. BEHAVIOR/BDDL 可以作为 EviStateBench task-state space 的 grounding，但不能定义全部边界。
2. `ontop`、`inside`、`open`、`covered`、`filled`、`contains`、`cooked` 这类空间/容器/对象/物质状态 predicate 是第一批 CHECK / AS_OF / DIFF / WHY / GOAL 查询的自然来源。
3. goal predicate 和 init predicate 的分布不同，因此 benchmark 不能只统计 goal；维护状态视图时必须同时处理初始状态、状态变化和目标条件。
4. `real`、`future`、`insource` 更像 BDDL bookkeeping / source marker，不能直接当成机器人任务状态视图的核心 predicate。
5. `grasped` 在 domain 中存在但没有出现在 init/goal 统计里，说明 robot interaction state 需要从 runtime/action log/simulator sensor 侧补充，不能只依赖 BDDL goal。
6. 高频 predicate 可以先支撑最小 StateObservation schema，但 `object state`、`material/particle state`、`robot interaction state` 和 numeric state 需要继续结合 OmniGibson object states 和真实 observation source 扩展。
7. 第一版 query templates 应该从 task family 反推，而不是从接口名字反推。

## 下一步

1. 人工检查高频 predicate 的 BDDL 语义，确认 taxonomy。
2. 从候选任务族中各选若干 task，形成 EviStateBench v0 的 representative task set。
3. 基于这些 task 设计 StateObservation schema v0。
4. 设计 CHECK / AS_OF / DIFF / WHY / GOAL query templates，并为每个 template 绑定真实 task-state 例子。

## 注意

本报告只统计 BDDL 文件中显式写出的 init / goal predicate。它还没有统计 OmniGibson runtime object states、动作日志、视觉检测器输出或真实视频 annotation。因此这里的统计结果是 schema/query 设计的起点，不是最终边界。
"""
    return report


def build_json_summary(
    bddl_root: Path,
    domain_path: Path,
    domain_predicates: dict[str, int],
    tasks: list[TaskAudit],
) -> dict[str, Any]:
    init_counter: Counter[str] = Counter()
    goal_counter: Counter[str] = Counter()
    object_type_counter: Counter[str] = Counter()
    family_counter: Counter[str] = Counter()
    task_rows: list[dict[str, Any]] = []

    for task in tasks:
        init_counter.update(occ.name for occ in task.init_occurrences)
        goal_counter.update(occ.name for occ in task.goal_occurrences)
        object_type_counter.update(task.object_type_count)
        family = categorize_task_family(task.task_name)
        family_counter[family] += 1
        task_rows.append(
            {
                "task_name": task.task_name,
                "path": task.path,
                "family": family,
                "object_count": sum(task.object_type_count.values()),
                "init_predicates": Counter(occ.name for occ in task.init_occurrences),
                "goal_predicates": Counter(occ.name for occ in task.goal_occurrences),
            }
        )

    return {
        "bddl_root": str(bddl_root),
        "domain_path": str(domain_path),
        "task_count": len(tasks),
        "domain_predicates": domain_predicates,
        "init_predicate_counts": init_counter,
        "goal_predicate_counts": goal_counter,
        "object_type_counts": object_type_counter,
        "task_family_counts": family_counter,
        "tasks": task_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bddl-root", type=Path, default=DEFAULT_BDDL_ROOT)
    parser.add_argument("--domain", type=Path, default=DEFAULT_DOMAIN)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=25)
    args = parser.parse_args()

    if not args.bddl_root.exists():
        raise FileNotFoundError(f"BDDL root not found: {args.bddl_root}")
    if not args.domain.exists():
        raise FileNotFoundError(f"Domain file not found: {args.domain}")

    domain_predicates = parse_domain_predicates(args.domain)
    predicate_names = set(domain_predicates)
    task_files = sorted(args.bddl_root.glob("*/problem*.bddl"))
    tasks = [parse_task(path, predicate_names) for path in task_files]

    report = build_report(
        args.bddl_root,
        args.domain,
        domain_predicates,
        tasks,
        args.top_n,
    )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        summary = build_json_summary(
            args.bddl_root,
            args.domain,
            domain_predicates,
            tasks,
        )
        args.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
