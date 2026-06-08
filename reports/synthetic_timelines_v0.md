# Synthetic Ground-Truth Timelines v0

本报告由 `tools/build_synthetic_timelines.py` 生成。

它对应最小验证计划的第 2 步：

```text
基于 init / goal predicate instances 构造 synthetic ground-truth timeline
```

这里生成的是隐藏真值时间线，不是 observation stream，不是被测系统输入，也不是 EviStateDB 的预测结果。后续会从它生成 clean observations、扰动 observations、queries 和 ground-truth answers。

## 配置

| item | value |
| --- | --- |
| input predicate instances | `/root/autodl-tmp/EviStateBench/data/task_predicate_instances_v0.jsonl` |
| output timeline events | `/root/autodl-tmp/EviStateBench/data/synthetic_ground_truth_timelines_v0.jsonl` |
| goal start time | 10 |
| goal step | 5 |
| invalidation gap | 0.1 |

## 总览

| item | count |
| --- | ---: |
| episodes | 602 |
| episodes with at least one goal predicate | 597 |
| timeline events | 5835 |
| deduplicated init assertions | 4273 |
| deduplicated goal predicates | 1581 |
| goal transitions written | 1319 |
| goals already satisfied at init | 262 |
| exclusive placement invalidations | 243 |
| duplicate predicate instances skipped | 6 |
| episodes whose final state satisfies all extracted goals | 602 |
| goal-bearing episodes whose final state satisfies all extracted goals | 597 |
| events containing symbolic goal variables | 494 |
| symbolic goal variable argument occurrences | 605 |

## Event Types

| item | count |
| --- | ---: |
| `init_assert` | 4273 |
| `goal_transition` | 1319 |
| `exclusive_relation_invalidation` | 243 |

## Task Families

| item | count |
| --- | ---: |
| `cleaning / washing` | 321 |
| `storage / organization / packing` | 129 |
| `cooking / food preparation` | 110 |
| `liquid / material transfer` | 27 |
| `assembly / setup` | 15 |

## Event Predicates

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

## Sample Events

| time | event_type | task | predicate | value | arguments |
| ---: | --- | --- | --- | --- | --- |
| 0 | `init_assert` | `adding_chemicals_to_hot_tub` | `filled` | True | `chlorine__bottle.n.01_1`, `chlorine.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_hot_tub` | `filled` | True | `hot_tub.n.02_1`, `water.n.06_1` |
| 0 | `init_assert` | `adding_chemicals_to_hot_tub` | `ontop` | True | `chlorine__bottle.n.01_1`, `floor.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_hot_tub` | `ontop` | True | `hot_tub.n.02_1`, `floor.n.01_1` |
| 10 | `goal_transition` | `adding_chemicals_to_hot_tub` | `contains` | True | `hot_tub.n.02_1`, `chlorine.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_lawn` | `filled` | True | `herbicide__bottle.n.01_1`, `herbicide.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_lawn` | `ontop` | True | `fertilizer__atomizer.n.01_1`, `floor.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_lawn` | `ontop` | True | `herbicide__bottle.n.01_1`, `floor.n.01_1` |
| 10 | `goal_transition` | `adding_chemicals_to_lawn` | `covered` | True | `lawn.n.01_1`, `fertilizer.n.01_1` |
| 15 | `goal_transition` | `adding_chemicals_to_lawn` | `covered` | True | `lawn.n.01_1`, `herbicide.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_pool` | `filled` | True | `disinfectant__bottle.n.01_1`, `disinfectant.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_pool` | `filled` | True | `pool.n.01_1`, `water.n.06_1` |
| 0 | `init_assert` | `adding_chemicals_to_pool` | `filled` | True | `sodium_carbonate__jar.n.01_1`, `sodium_carbonate.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_pool` | `ontop` | True | `disinfectant__bottle.n.01_1`, `floor.n.01_1` |
| 0 | `init_assert` | `adding_chemicals_to_pool` | `ontop` | True | `sodium_carbonate__jar.n.01_1`, `floor.n.01_1` |
| 10 | `goal_transition` | `adding_chemicals_to_pool` | `contains` | True | `pool.n.01_1`, `disinfectant.n.01_1` |

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
