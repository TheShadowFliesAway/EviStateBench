# Perturbed StateObservation Streams v0

本报告由 `tools/build_perturbed_observations.py` 生成。

它对应最小验证计划的第 4 步：

```text
从 clean StateObservation stream 注入 delay / missing / conflict / out-of-order / low-confidence
```

这些 stream 是 benchmark 输入变体，不是 hidden truth，也不是标准答案。标准答案仍应由 hidden timeline / oracle generator 产生。

## 配置

| item | value |
| --- | --- |
| input clean observations | `/root/autodl-tmp/EviStateBench/data/clean_state_observations_v0.jsonl` |
| clean observation count | 5835 |
| output directory | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0` |
| manifest | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/manifest.json` |
| seed | 2026 |

## 参数

```json
{
  "constant_delay_seconds": 5.0,
  "max_random_delay_seconds": 12.0,
  "missing_rate": 0.2,
  "low_confidence_rate": 0.35,
  "low_confidence_min": 0.35,
  "low_confidence_max": 0.75,
  "conflict_rate": 0.1,
  "conflict_confidence": 0.65,
  "conflict_max_delay_seconds": 6.0
}
```

## Streams

| regime | output | observations | dropped | conflict added | delayed | low confidence | out-of-order rows | avg delay | max delay |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `delay` | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/delay.jsonl` | 5835 | 0 | 0 | 5835 | 0 | 0 | 5.000 | 5.000 |
| `out_of_order` | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/out_of_order.jsonl` | 5835 | 0 | 0 | 5835 | 0 | 297 | 6.007 | 11.999 |
| `missing` | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/missing.jsonl` | 4686 | 1149 | 0 | 0 | 0 | 0 | 0.000 | 0.000 |
| `low_confidence` | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/low_confidence.jsonl` | 5835 | 0 | 0 | 0 | 2116 | 0 | 0.000 | 0.000 |
| `conflict` | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/conflict.jsonl` | 6382 | 0 | 547 | 547 | 0 | 32 | 0.253 | 5.978 |
| `mixed` | `/root/autodl-tmp/EviStateBench/data/observation_streams_v0/mixed.jsonl` | 5143 | 1171 | 479 | 5143 | 1680 | 278 | 6.609 | 23.123 |

## Operation Counts

| item | count |
| --- | ---: |
| `random_delay` | 10978 |
| `kept_after_missing_sampling` | 9350 |
| `confidence_unchanged` | 6703 |
| `constant_delay` | 5835 |
| `kept_original` | 5835 |
| `confidence_degraded` | 3796 |
| `conflict_flip` | 1026 |

## Source Counts

| item | count |
| --- | ---: |
| `synthetic_truth_sensor` | 32690 |
| `synthetic_conflict_sensor` | 1026 |

## Mixed Stream Sample

| arrival_time | event_time | source | predicate | value | confidence | operations | obs_id |
| ---: | ---: | --- | --- | --- | ---: | --- | --- |
| 2.12891 | 0 | `synthetic_truth_sensor` | `ontop` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_hot_tub__problem0__obs_mixed_00004` |
| 6.98098 | 0 | `synthetic_truth_sensor` | `filled` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_hot_tub__problem0__obs_mixed_00001` |
| 7.84335 | 0 | `synthetic_truth_sensor` | `ontop` | True | 0.644394 | `kept_after_missing_sampling,random_delay,confidence_degraded` | `syn_v0__adding_chemicals_to_hot_tub__problem0__obs_mixed_00003` |
| 9.46031 | 0 | `synthetic_truth_sensor` | `filled` | True | 0.74669 | `kept_after_missing_sampling,random_delay,confidence_degraded` | `syn_v0__adding_chemicals_to_hot_tub__problem0__obs_mixed_00002` |
| 18.9119 | 10 | `synthetic_truth_sensor` | `contains` | True | 0.620246 | `kept_after_missing_sampling,random_delay,confidence_degraded` | `syn_v0__adding_chemicals_to_hot_tub__problem0__obs_mixed_00005` |
| 1.02769 | 0 | `synthetic_truth_sensor` | `filled` | True | 0.462211 | `kept_after_missing_sampling,random_delay,confidence_degraded` | `syn_v0__adding_chemicals_to_lawn__problem0__obs_mixed_00001` |
| 4.25177 | 0 | `synthetic_truth_sensor` | `ontop` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_lawn__problem0__obs_mixed_00002` |
| 10.3768 | 10 | `synthetic_truth_sensor` | `covered` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_lawn__problem0__obs_mixed_00004` |
| 11.7088 | 0 | `synthetic_truth_sensor` | `ontop` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_lawn__problem0__obs_mixed_00003` |
| 15.0274 | 15 | `synthetic_truth_sensor` | `covered` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_lawn__problem0__obs_mixed_00005` |
| 1.81968 | 0 | `synthetic_truth_sensor` | `ontop` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_pool__problem0__obs_mixed_00004` |
| 2.52148 | 0 | `synthetic_truth_sensor` | `filled` | True | 0.358784 | `kept_after_missing_sampling,random_delay,confidence_degraded` | `syn_v0__adding_chemicals_to_pool__problem0__obs_mixed_00003` |
| 5.46289 | 0 | `synthetic_truth_sensor` | `ontop` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_pool__problem0__obs_mixed_00005` |
| 7.02428 | 0 | `synthetic_truth_sensor` | `filled` | True | 0.359037 | `kept_after_missing_sampling,random_delay,confidence_degraded` | `syn_v0__adding_chemicals_to_pool__problem0__obs_mixed_00001` |
| 20.6552 | 10 | `synthetic_truth_sensor` | `contains` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__adding_chemicals_to_pool__problem0__obs_mixed_00006` |
| 4.10268 | 0 | `synthetic_truth_sensor` | `ontop` | True | 1 | `kept_after_missing_sampling,random_delay,confidence_unchanged` | `syn_v0__assembling_furniture__problem0__obs_mixed_00006` |

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
