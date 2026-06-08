# Task Predicate Instances v0

本报告由 `tools/extract_task_predicate_instances.py` 生成。

它对应最小验证计划的第 1 步：

```text
从 BDDL init / goal 抽 predicate instances
```

这里抽出来的不是 observation，也不是 EviStateDB 的内部 view。它们是从任务规格中显式出现的状态实例，用于后续构造 synthetic ground-truth timeline、clean observations、query set 和 ground-truth answers。

## 配置

| item | value |
| --- | --- |
| BDDL root | `/root/autodl-tmp/BEHAVIOR-1K/bddl3/bddl/activity_definitions` |
| domain file | `/root/autodl-tmp/BEHAVIOR-1K/bddl3/bddl/activity_definitions/domain_omnigibson.bddl` |
| scanned task files | 1016 |
| selected task files | 602 |
| include all families | False |
| predicate scope | `core` |
| include agent states | False |
| JSONL output | `/root/autodl-tmp/EviStateBench/data/task_predicate_instances_v0.jsonl` |

默认只保留 v0 representative task families：

```text
assembly / setup
cleaning / washing
cooking / food preparation
liquid / material transfer
storage / organization / packing
```

## 总览

| item | count |
| --- | ---: |
| extracted predicate occurrences before predicate-scope filter | 8802 |
| after predicate-scope filter | 6462 |
| excluded by agent-state filter | 602 |
| written predicate instances | 5860 |

## Included Task Families

| item | count |
| --- | ---: |
| `cleaning / washing` | 2943 |
| `cooking / food preparation` | 1407 |
| `storage / organization / packing` | 1215 |
| `liquid / material transfer` | 204 |
| `assembly / setup` | 91 |

## Included Sections

| item | count |
| --- | ---: |
| `init` | 4278 |
| `goal` | 1582 |

## Included Predicates

| item | count |
| --- | ---: |
| `ontop` | 2298 |
| `inside` | 1282 |
| `covered` | 1250 |
| `filled` | 372 |
| `cooked` | 266 |
| `contains` | 81 |
| `attached` | 60 |
| `nextto` | 54 |
| `frozen` | 34 |
| `open` | 33 |
| `folded` | 29 |
| `toggled_on` | 20 |
| `saturated` | 18 |
| `hot` | 15 |
| `draped` | 14 |
| `touching` | 14 |
| `overlaid` | 10 |
| `under` | 7 |
| `unfolded` | 3 |

## Predicate Roles Before Filter

| item | count |
| --- | ---: |
| `core_state` | 6462 |
| `context` | 2340 |

## Excluded By Predicate Scope

| item | count |
| --- | ---: |
| `context` | 2340 |

## Agent-State Filter

默认不写入 `agent.*` 参数相关的 predicate instance。原因是 BDDL init 中几乎每个 task 都有 `ontop(agent, floor)`，它是机器人初始位置/context，不是第一版 object task-state workload 的核心对象。

| item | count |
| --- | ---: |
| excluded agent-state instances | 602 |

| item | count |
| --- | ---: |
| `ontop` | 602 |

如需保留这类状态，可运行：

```bash
python tools/extract_task_predicate_instances.py --include-agent-states
```

## Sample Instances

| task | section | predicate | value | arguments | family |
| --- | --- | --- | --- | --- | --- |
| `adding_chemicals_to_hot_tub` | init | `filled` | True | `hot_tub.n.02_1`, `water.n.06_1` | liquid / material transfer |
| `adding_chemicals_to_hot_tub` | init | `filled` | True | `chlorine__bottle.n.01_1`, `chlorine.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_hot_tub` | init | `ontop` | True | `chlorine__bottle.n.01_1`, `floor.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_hot_tub` | init | `ontop` | True | `hot_tub.n.02_1`, `floor.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_hot_tub` | goal | `contains` | True | `?hot_tub.n.02_1`, `?chlorine.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_hot_tub` | goal | `filled` | True | `?hot_tub.n.02_1`, `?water.n.06_1` | liquid / material transfer |
| `adding_chemicals_to_lawn` | init | `ontop` | True | `herbicide__bottle.n.01_1`, `floor.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_lawn` | init | `ontop` | True | `fertilizer__atomizer.n.01_1`, `floor.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_lawn` | init | `filled` | True | `herbicide__bottle.n.01_1`, `herbicide.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_lawn` | goal | `covered` | True | `?lawn.n.01_1`, `?fertilizer.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_lawn` | goal | `covered` | True | `?lawn.n.01_1`, `?herbicide.n.01_1` | liquid / material transfer |
| `adding_chemicals_to_pool` | init | `filled` | True | `sodium_carbonate__jar.n.01_1`, `sodium_carbonate.n.01_1` | liquid / material transfer |

## 后续用途

这些 predicate instances 会进入下一步 generator：

```text
1. :init instance  -> 初始 ground-truth state
2. :goal instance  -> goal query / oracle answer 的目标条件
3. synthetic update -> 构造状态变化 timeline
4. perturbation    -> 生成 delay / missing / conflict observations
```

注意：BDDL goal 只告诉我们目标应该满足什么，不等于真实 episode 中某个时间点已经满足。后续 oracle 需要根据 synthetic timeline 或 simulator truth 来回答 query。
