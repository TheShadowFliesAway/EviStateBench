# Ground-Truth Answer Sets v0

本报告由 `tools/build_ground_truth_answers.py` 生成。

它对应最小验证计划的第 6 步：

```text
用 hidden timeline 和 observation streams 生成 ground-truth answers
```

## 配置

| item | value |
| --- | --- |
| hidden timeline | `/root/autodl-tmp/EviStateBench/data/synthetic_ground_truth_timelines_v0.jsonl` |
| query set | `/root/autodl-tmp/EviStateBench/data/query_sets_v0/queries.jsonl` |
| output directory | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0` |
| manifest | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/manifest.json` |
| uncertain confidence threshold | 0.75 |
| observation streams | 7 |

## Oracle Semantics

```text
CHECK_STATE  -> hidden world truth at valid_time
STATE_DIFF   -> hidden world truth difference between t1 and t2
CHECK_GOAL   -> hidden world truth + goal specs
AS_OF_STATE  -> selected observation stream evidence available by transaction_time
```

`AS_OF_STATE` 是 stream-dependent 的：同一个 query 在 clean / delay / missing / conflict / mixed stream 下可能有不同标准答案，因为 transaction_time 前可见证据不同。

## Streams

| stream | output | answers | known | unknown | uncertain | conflict |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `clean` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/clean.jsonl` | 10618 | 9136 | 951 | 0 | 0 |
| `conflict` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/conflict.jsonl` | 10618 | 8935 | 951 | 0 | 201 |
| `delay` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/delay.jsonl` | 10618 | 9136 | 951 | 0 | 0 |
| `low_confidence` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/low_confidence.jsonl` | 10618 | 8354 | 951 | 782 | 0 |
| `missing` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/missing.jsonl` | 10618 | 8816 | 1271 | 0 | 0 |
| `mixed` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/mixed.jsonl` | 10618 | 8034 | 1319 | 569 | 165 |
| `out_of_order` | `/root/autodl-tmp/EviStateBench/data/answer_sets_v0/out_of_order.jsonl` | 10618 | 9085 | 1002 | 0 | 0 |

## Clean Answer Types

| item | count |
| --- | ---: |
| `STATE_ANSWER` | 8959 |
| `GOAL_ANSWER` | 1128 |
| `STATE_DIFF_ANSWER` | 531 |

## Clean Query Types

| item | count |
| --- | ---: |
| `CHECK_STATE` | 5835 |
| `AS_OF_STATE` | 3124 |
| `CHECK_GOAL` | 1128 |
| `STATE_DIFF` | 531 |

## Clean Sample Answers

| query_type | answer_type | query_id | value/satisfied | confidence | status |
| --- | --- | --- | --- | ---: | --- |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00001` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00002` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00003` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00004` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00005` | True | 1 | `known` |
| `AS_OF_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_asof_before_00005` | None | 0 | `unknown` |
| `AS_OF_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_asof_after_00005` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00006` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00007` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00008` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00009` | True | 1 | `known` |
| `AS_OF_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_before_00009` | None | 0 | `unknown` |
| `AS_OF_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_after_00009` | True | 1 | `known` |
| `CHECK_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00010` | True | 1 | `known` |
| `AS_OF_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_before_00010` | None | 0 | `unknown` |
| `AS_OF_STATE` | `STATE_ANSWER` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_after_00010` | True | 1 | `known` |

## 边界

这一步生成的是 evaluator 使用的标准答案，不是被测系统输入。正式发布 benchmark 时，answer sets 应该只用于本地评测或隐藏评测服务器，不应和 observation streams 一起暴露给被测系统。

当前 `AS_OF_STATE` oracle 是一个轻量 evidence-availability oracle：它只看 `arrival_time <= transaction_time` 且 `event_time <= valid_time` 的 observation，并取最新 event_time 的证据。如果最新证据值冲突，则答案 status 为 `conflict`；如果没有证据，则为 `unknown`；如果证据 confidence 低于阈值，则为 `uncertain`。
