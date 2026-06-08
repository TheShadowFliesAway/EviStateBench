# BDDL Task Audit Report

本报告由 `tools/audit_bddl_tasks.py` 生成，用于 EviStateBench Phase 1：从 BEHAVIOR/BDDL 任务定义反推 task-state space。

## 数据来源

```text
BDDL root: /root/autodl-tmp/BEHAVIOR-1K/bddl3/bddl/activity_definitions
domain file: /root/autodl-tmp/BEHAVIOR-1K/bddl3/bddl/activity_definitions/domain_omnigibson.bddl
```

## 总览

| item | value |
| --- | ---: |
| task files | 1016 |
| domain predicates | 26 |
| predicates observed in init/goal | 25 |
| predicates observed only in init | 3 |
| predicates observed only in goal | 6 |
| domain predicates not observed in init/goal | 1 |
| init predicate occurrences | 12584 |
| goal predicate occurrences | 3317 |

Domain predicates not observed in init/goal:

```text
grasped
```

## 高频 Predicate

### 全部 init + goal

| item | count |
| --- | ---: |
| `ontop` | 5333 |
| `inroom` | 3207 |
| `inside` | 2670 |
| `covered` | 1490 |
| `filled` | 693 |
| `insource` | 442 |
| `cooked` | 431 |
| `real` | 363 |
| `future` | 339 |
| `contains` | 248 |
| `nextto` | 166 |
| `attached` | 109 |
| `frozen` | 77 |
| `folded` | 60 |
| `open` | 54 |
| `toggled_on` | 41 |
| `draped` | 38 |
| `hot` | 36 |
| `overlaid` | 26 |
| `saturated` | 23 |
| `touching` | 22 |
| `unfolded` | 16 |
| `under` | 9 |
| `broken` | 6 |
| `on_fire` | 2 |

### Initial Conditions

| item | count |
| --- | ---: |
| `ontop` | 4776 |
| `inroom` | 3207 |
| `inside` | 1889 |
| `covered` | 777 |
| `filled` | 638 |
| `insource` | 442 |
| `future` | 339 |
| `cooked` | 315 |
| `frozen` | 58 |
| `attached` | 42 |
| `toggled_on` | 29 |
| `hot` | 19 |
| `open` | 18 |
| `unfolded` | 13 |
| `saturated` | 9 |
| `draped` | 8 |
| `broken` | 3 |
| `under` | 1 |
| `overlaid` | 1 |

### Goal Conditions

| item | count |
| --- | ---: |
| `inside` | 781 |
| `covered` | 713 |
| `ontop` | 557 |
| `real` | 363 |
| `contains` | 248 |
| `nextto` | 166 |
| `cooked` | 116 |
| `attached` | 67 |
| `folded` | 60 |
| `filled` | 55 |
| `open` | 36 |
| `draped` | 30 |
| `overlaid` | 25 |
| `touching` | 22 |
| `frozen` | 19 |
| `hot` | 17 |
| `saturated` | 14 |
| `toggled_on` | 12 |
| `under` | 8 |
| `broken` | 3 |
| `unfolded` | 3 |
| `on_fire` | 2 |

### 按任务计数的 Goal Predicate

这里统计的是“有多少个 task 的 goal 里出现过该 predicate”，不是 occurrence 总数。

| item | count |
| --- | ---: |
| `covered` | 426 |
| `inside` | 310 |
| `ontop` | 235 |
| `real` | 152 |
| `contains` | 119 |
| `cooked` | 93 |
| `nextto` | 76 |
| `filled` | 51 |
| `attached` | 50 |
| `folded` | 35 |
| `open` | 31 |
| `overlaid` | 24 |
| `draped` | 19 |
| `hot` | 14 |
| `frozen` | 13 |
| `toggled_on` | 12 |
| `saturated` | 11 |
| `touching` | 11 |
| `under` | 8 |
| `broken` | 3 |
| `unfolded` | 2 |
| `on_fire` | 1 |

## Arity / Polarity / Taxonomy

### Predicate Arity Distribution

| item | count |
| --- | ---: |
| `2` | 14476 |
| `1` | 1425 |

### Predicate Polarity Distribution

| item | count |
| --- | ---: |
| `init/positive` | 12228 |
| `goal/positive` | 2632 |
| `goal/negative` | 685 |
| `init/negative` | 356 |

### Predicate Taxonomy 初版

| item | count |
| --- | ---: |
| `binary spatial / containment relation` | 11433 |
| `material / particle state` | 2454 |
| `BDDL bookkeeping / source marker` | 1144 |
| `object unary state` | 723 |
| `binary relation` | 147 |

### 高频 Predicate 分类表

| predicate | domain arity | observed category | total occurrences | goal occurrences |
| --- | ---: | --- | ---: | ---: |
| `ontop` | 2 | binary spatial / containment relation | 5333 | 557 |
| `inroom` | 2 | binary spatial / containment relation | 3207 | 0 |
| `inside` | 2 | binary spatial / containment relation | 2670 | 781 |
| `covered` | 2 | material / particle state | 1490 | 713 |
| `filled` | 2 | material / particle state | 693 | 55 |
| `insource` | 2 | BDDL bookkeeping / source marker | 442 | 0 |
| `cooked` | 1 | object unary state | 431 | 116 |
| `real` | 1 | BDDL bookkeeping / source marker | 363 | 363 |
| `future` | 1 | BDDL bookkeeping / source marker | 339 | 0 |
| `contains` | 2 | material / particle state | 248 | 248 |
| `nextto` | 2 | binary spatial / containment relation | 166 | 166 |
| `attached` | 2 | binary relation | 109 | 67 |
| `frozen` | 1 | object unary state | 77 | 19 |
| `folded` | 1 | object unary state | 60 | 60 |
| `open` | 1 | object unary state | 54 | 36 |
| `toggled_on` | 1 | object unary state | 41 | 12 |
| `draped` | 2 | binary relation | 38 | 30 |
| `hot` | 1 | object unary state | 36 | 17 |
| `overlaid` | 2 | binary spatial / containment relation | 26 | 25 |
| `saturated` | 2 | material / particle state | 23 | 14 |
| `touching` | 2 | binary spatial / containment relation | 22 | 22 |
| `unfolded` | 1 | object unary state | 16 | 3 |
| `under` | 2 | binary spatial / containment relation | 9 | 8 |
| `broken` | 1 | object unary state | 6 | 3 |
| `on_fire` | 1 | object unary state | 2 | 2 |

## Object Type 分布

| item | count |
| --- | ---: |
| `floor.n.01` | 1066 |
| `agent.n.01` | 1016 |
| `countertop.n.01` | 364 |
| `water.n.06` | 299 |
| `sink.n.01` | 283 |
| `cabinet.n.01` | 245 |
| `electric_refrigerator.n.01` | 224 |
| `rag.n.01` | 158 |
| `bowl.n.01` | 156 |
| `stain.n.01` | 133 |
| `plate.n.04` | 117 |
| `dust.n.01` | 112 |
| `liquid_soap.n.01` | 94 |
| `tupperware.n.01` | 93 |
| `liquid_soap__bottle.n.01` | 91 |
| `stove.n.01` | 81 |
| `money.n.01` | 77 |
| `table.n.02` | 74 |
| `chopping_board.n.01` | 70 |
| `sack.n.01` | 69 |
| `clove.n.03` | 68 |
| `oven.n.01` | 66 |
| `salt__shaker.n.01` | 66 |
| `salt.n.02` | 65 |
| `bucket.n.01` | 63 |
| `grocery_shelf.n.01` | 62 |
| `carving_knife.n.01` | 57 |
| `detergent.n.02` | 57 |
| `detergent__bottle.n.01` | 56 |
| `carton.n.02` | 54 |

## Task Family 初筛

| family | task count | top predicates |
| --- | ---: | --- |
| other / mixed | 372 | `ontop`(2135), `inside`(1234), `inroom`(1220), `filled`(321), `real`(243), `covered`(239) |
| cleaning / washing | 321 | `ontop`(1483), `covered`(1145), `inroom`(901), `inside`(328), `filled`(225), `insource`(194) |
| storage / organization / packing | 129 | `ontop`(739), `inside`(421), `inroom`(369), `attached`(33), `nextto`(26), `covered`(24) |
| cooking / food preparation | 110 | `ontop`(503), `inside`(467), `inroom`(421), `cooked`(256), `real`(109), `future`(101) |
| shopping / acquisition | 42 | `ontop`(298), `inroom`(186), `inside`(154), `nextto`(21), `attached`(3), `covered`(1) |
| liquid / material transfer | 27 | `ontop`(103), `inroom`(77), `inside`(62), `filled`(43), `insource`(14), `covered`(13) |
| assembly / setup | 15 | `ontop`(72), `inroom`(33), `toggled_on`(13), `attached`(12), `inside`(4), `covered`(2) |

## 建议优先选择的 3-5 类任务族

1. cleaning / washing: 高频、任务数量大，适合覆盖 object unary state 与 material / particle state。
2. cooking / food preparation: 适合覆盖 temperature-like、cooked/sliced/frozen 等对象状态，后续可结合 simulator object states 扩展。
3. storage / organization / packing: 适合覆盖 `inside`、`ontop`、`open`、`inroom` 等空间和容器状态。
4. liquid / material transfer: 适合覆盖 `filled`、`covered`、`saturated`、`contains` 等物质状态。
5. assembly / setup: 适合检查接触、空间关系和目标条件组合。

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
