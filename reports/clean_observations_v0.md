# Clean StateObservation Stream v0

本报告由 `tools/build_clean_observations.py` 生成。

它对应最小验证计划的第 3 步：

```text
从 hidden ground-truth timeline 生成 clean StateObservation stream
```

这里生成的是被测系统可以接收的干净观察流。它不是 hidden truth 本身，也不是 EviStateDB 的输出。它是后续 noisy / delayed / missing / conflicting observation streams 的基准版本。

## 配置

| item | value |
| --- | --- |
| input timeline events | `/root/autodl-tmp/EviStateBench/data/synthetic_ground_truth_timelines_v0.jsonl` |
| output observations | `/root/autodl-tmp/EviStateBench/data/clean_state_observations_v0.jsonl` |
| source | `synthetic_truth_sensor` |
| confidence | 1 |

## 总览

| item | count |
| --- | ---: |
| input timeline events | 5835 |
| output observations | 5835 |
| episodes | 602 |
| observations with arrival_time == event_time | 5835 |
| observations with observed_value=False | 791 |

## Source Event Types

| item | count |
| --- | ---: |
| `init_assert` | 4273 |
| `goal_transition` | 1319 |
| `exclusive_relation_invalidation` | 243 |

## Task Families

| item | count |
| --- | ---: |
| `cleaning / washing` | 2809 |
| `cooking / food preparation` | 1421 |
| `storage / organization / packing` | 1304 |
| `liquid / material transfer` | 204 |
| `assembly / setup` | 97 |

## Predicates

| item | count |
| --- | ---: |
| `ontop` | 2438 |
| `inside` | 1304 |
| `covered` | 1109 |
| `filled` | 370 |
| `cooked` | 263 |
| `contains` | 76 |
| `attached` | 55 |
| `nextto` | 54 |
| `frozen` | 34 |
| `folded` | 29 |
| `toggled_on` | 19 |
| `open` | 15 |
| `hot` | 15 |
| `draped` | 14 |
| `touching` | 12 |
| `overlaid` | 10 |
| `saturated` | 9 |
| `under` | 6 |
| `unfolded` | 3 |

## Confidence Values

| item | count |
| --- | ---: |
| `1.0` | 5835 |

## Sample Observations

| event_time | arrival_time | source | task | predicate | value | arguments |
| ---: | ---: | --- | --- | --- | --- | --- |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_hot_tub` | `filled` | True | `chlorine__bottle.n.01_1`, `chlorine.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_hot_tub` | `filled` | True | `hot_tub.n.02_1`, `water.n.06_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_hot_tub` | `ontop` | True | `chlorine__bottle.n.01_1`, `floor.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_hot_tub` | `ontop` | True | `hot_tub.n.02_1`, `floor.n.01_1` |
| 10 | 10 | `synthetic_truth_sensor` | `adding_chemicals_to_hot_tub` | `contains` | True | `hot_tub.n.02_1`, `chlorine.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_lawn` | `filled` | True | `herbicide__bottle.n.01_1`, `herbicide.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_lawn` | `ontop` | True | `fertilizer__atomizer.n.01_1`, `floor.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_lawn` | `ontop` | True | `herbicide__bottle.n.01_1`, `floor.n.01_1` |
| 10 | 10 | `synthetic_truth_sensor` | `adding_chemicals_to_lawn` | `covered` | True | `lawn.n.01_1`, `fertilizer.n.01_1` |
| 15 | 15 | `synthetic_truth_sensor` | `adding_chemicals_to_lawn` | `covered` | True | `lawn.n.01_1`, `herbicide.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_pool` | `filled` | True | `disinfectant__bottle.n.01_1`, `disinfectant.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_pool` | `filled` | True | `pool.n.01_1`, `water.n.06_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_pool` | `filled` | True | `sodium_carbonate__jar.n.01_1`, `sodium_carbonate.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_pool` | `ontop` | True | `disinfectant__bottle.n.01_1`, `floor.n.01_1` |
| 0 | 0 | `synthetic_truth_sensor` | `adding_chemicals_to_pool` | `ontop` | True | `sodium_carbonate__jar.n.01_1`, `floor.n.01_1` |
| 10 | 10 | `synthetic_truth_sensor` | `adding_chemicals_to_pool` | `contains` | True | `pool.n.01_1`, `disinfectant.n.01_1` |

## 生成规则

1. 一条 timeline event 生成一条 `StateObservation`。
2. `event_time` 保持不变。
3. `arrival_time = event_time`，所以 clean stream 没有延迟和乱序。
4. `observed_value = truth_value`。
5. `confidence = 1`。
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
