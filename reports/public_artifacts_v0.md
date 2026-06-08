# Public Artifacts v0

本报告由 `tools/7_build_public_artifacts.py` 生成。

它对应 artifact boundary cleanup：

```text
public task specs + public observation streams + public query set
```

## Public Inputs

| artifact | path | count |
| --- | --- | ---: |
| task specs | `data/public_v0/task_specs.jsonl` | 602 |
| queries | `data/public_v0/queries.jsonl` | 10618 |

## Observation Streams

| stream | observations | path |
| --- | ---: | --- |
| `clean` | 5835 | `data/public_v0/observation_streams/clean.jsonl` |
| `conflict` | 6382 | `data/public_v0/observation_streams/conflict.jsonl` |
| `delay` | 5835 | `data/public_v0/observation_streams/delay.jsonl` |
| `low_confidence` | 5835 | `data/public_v0/observation_streams/low_confidence.jsonl` |
| `missing` | 4686 | `data/public_v0/observation_streams/missing.jsonl` |
| `mixed` | 5143 | `data/public_v0/observation_streams/mixed.jsonl` |
| `out_of_order` | 5835 | `data/public_v0/observation_streams/out_of_order.jsonl` |

## Query Types

| item | count |
| --- | ---: |
| `CHECK_STATE` | 5835 |
| `AS_OF_STATE` | 3124 |
| `CHECK_GOAL` | 1128 |
| `STATE_DIFF` | 531 |

## Task Families

| item | count |
| --- | ---: |
| `cleaning / washing` | 321 |
| `storage / organization / packing` | 129 |
| `cooking / food preparation` | 110 |
| `liquid / material transfer` | 27 |
| `assembly / setup` | 15 |

## Boundary

这些文件可以提供给被测系统：

```text
data/public_v0/task_specs.jsonl
data/public_v0/queries.jsonl
data/public_v0/observation_streams/*.jsonl
```

这些文件是 hidden / oracle / evaluation-only，不应提供给被测系统：

```text
data/synthetic_ground_truth_timelines_v0.jsonl
data/task_predicate_instances_v0.jsonl
data/answer_sets_v0/*.jsonl
data/evaluation_v0/*
```

清理规则：

1. `CHECK_GOAL` query 不再内嵌 `goal_states`，只通过 `task_spec_id` 引用任务规格。
2. public observation 不包含 `truth_value`、`source_section`、`source_event_type`、`synthetic_reason` 等 generator/oracle 字段。
3. public manifest 使用相对路径，避免把本机路径暴露给 benchmark 使用者。
