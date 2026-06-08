# EviStateBench Idea 与实验思路简述

## 1. 这个 idea 想解决什么

EviStateBench 的核心问题是：机器人或具身智能系统看到的不是干净、同步、完整的世界状态，而是一串带噪声、延迟、乱序、缺失和互相冲突的 observation。真正有价值的问题不是“存不存这些 observation”，而是系统能不能把这些 observation 维护成可查询、可修正、可追溯的 **temporal task-state views**。

换句话说，EviStateBench 评测的是：

```text
observation stream + query set -> system under test -> predicted QueryAnswers -> evaluator
```

系统内部可以维护 temporal task-state views，也可以使用 retrieval、log scan、SQL、规则或神经方法。benchmark 不强制内部表示，只评测最终查询答案。

例如一个任务要求“把杯子放进柜子并关上柜门”。系统需要维护的不只是某一帧里看没看到杯子，而是：

```text
inside(cup, cabinet)
open(cabinet)
grasped(robot, cup)
goal_satisfied(task)
```

并且要知道这些状态在什么世界时间成立、系统在什么接收时间知道它、哪些证据支持它、哪些证据反驳它、后来迟到的证据是否改写了历史判断。

## 2. 最关键的因素

这个 idea 最关键的因素有五个。

第一，**event time 和 arrival time 必须分开**。具身 observation 可能晚到、乱序到达，系统不能只维护一个“当前状态”，而要支持 valid-time 和 transaction-time 的双时间语义。

第二，**observation 是证据，不是最终状态**。来自 simulator、detector、VLM、tracker、action log 的输出都只是带置信度的声明，系统要把多条证据融合成状态视图。

第三，**冲突证据必须被保留**。如果动作日志说 cup 已经放进柜子，但视觉检测器因为遮挡说没看到 cup，benchmark 应该检查系统是否能保留 support / contradict evidence，而不是简单覆盖旧值。

第四，**查询必须是任务驱动的**。机器人关心的是状态是否成立、目标是否满足、动作前提是否满足、失败前后哪些状态变了、为什么系统相信某个状态，而不是泛泛地检索历史片段。

第五，**标准答案不能由 EviStateDB 自己产生**。EviStateDB 只是 reference baseline engine；ground truth 应该来自 simulator truth 和 task specification。

## 3. 一句话定位

```text
EviStateBench 是一个面向数据管理的 benchmark，用来评测系统如何从不可靠的具身 observation stream 中维护可审计的时态任务状态视图。
```

它不是：

```text
embodied memory system
robot planning system
VLM / perception system
symbolic state estimator
```

它更准确的定位是：

```text
temporal task-state view maintenance benchmark + reference baseline engine
```

## 4. 实验的总体思路

实验应该围绕一条主线展开：

```text
任务定义 -> 真值状态时间线 -> 扰动 observation stream -> 查询集 -> 系统回答 -> 和标准答案评测
```

具体可以分成六步。

## 5. Step 1: 从 BEHAVIOR/BDDL 反推任务状态空间

先审计 BEHAVIOR/BDDL 中的任务定义，统计 init / goal 里的 predicate、object type、predicate arity 和 task family。

这一部分回答：

```text
benchmark 应该维护哪些 task-state？
哪些 predicate 高频出现？
哪些 predicate 是核心状态？
哪些只是 context 或 bookkeeping？
哪些任务族最适合作为第一版实验？
```

当前已有数据已经支持这一步。已有结论是 v0 应重点覆盖：

```text
inside, contains
ontop, nextto, under, overlaid
covered, filled, saturated
cooked, frozen, open, folded, toggled_on, hot
attached, draped, touching
```

代表任务族可以选：

```text
cleaning / washing
cooking / food preparation
storage / organization / packing
liquid / material transfer
assembly / setup
```

## 6. Step 2: 生成 ground-truth state timelines

对每个 episode，需要从 simulator truth 和 task specification 生成标准状态时间线。

也就是明确：

```text
在每个 valid_time，
每个 predicate instance 的真实 value 是什么，
goal predicates 是否满足，
状态变化发生在什么时候。
```

这一层是 oracle，只用于生成标准答案，不等于系统能直接读取的输入。

## 7. Step 3: 从真值生成 observation stream

接下来从 ground-truth timeline 生成系统实际能看到的 `StateObservation`。

每条 observation 至少包含：

```text
event_time
arrival_time
source
predicate_name
arguments
observed_value
confidence
polarity
evidence_ref
```

这里要区分：

```text
simulator truth: 标准答案来源
observation stream: 系统输入
query set: benchmark 考题
predicted QueryAnswer: 系统对外输出
maintained view: 系统内部可能维护的结构，不是 benchmark 强制输出
```

这个区分非常关键，否则 benchmark 会退化成直接读取真值。

## 8. Step 4: 注入扰动，形成不同实验 regime

EviStateBench 的核心挑战来自 observation stream 的不可靠性。因此实验要设置多个 regime：

```text
clean
noisy
delayed
out-of-order
missing
conflicting
mixed
```

每个 regime 评测不同能力：

| regime | 主要考察 |
| --- | --- |
| clean | 基础状态维护是否正确 |
| noisy | 置信度融合和错误观测鲁棒性 |
| delayed | arrival_time 晚于 event_time 时是否能修复历史 |
| out-of-order | 乱序 observation 是否破坏状态视图 |
| missing | 证据缺失时是否能返回 unknown / uncertain |
| conflicting | support / contradict evidence 是否被保留 |
| mixed | 接近真实具身 observation pipeline 的综合压力 |

## 9. Step 5: 让不同方法输出统一 QueryAnswer

每个方法都接收同样的 observation stream 和 query set，输出同样格式的 predicted `QueryAnswer`。

TemporalStateView 只是一种可选的内部维护结构。EviStateDB 会维护 TemporalStateView；其他 baseline 可以完全不维护它，只要能回答 query 即可。

可以比较的 baseline 包括：

```text
Latest Observation
Temporal Log + Voting
Static Symbolic State
SQL / DuckDB Scan
Recall Memory Baseline
Generic IVM Baseline
EviStateDB
```

重点不是证明 EviStateDB 一定最强，而是分析不同方法在这个 workload 下分别失败在哪里。

## 10. Step 6: 用任务查询评测维护结果

核心 query workload 应该包括：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
WHY_STATE
CHECK_GOAL
```

每类查询对应一种任务需要：

| query | 问题 |
| --- | --- |
| CHECK_STATE | 某个状态在某个 valid_time 是否成立 |
| AS_OF_STATE | 系统在某个 transaction_time 当时如何判断历史状态 |
| STATE_DIFF | 两个时间点之间哪些状态变了 |
| WHY_STATE | 系统为什么相信某个状态 |
| CHECK_GOAL | 任务目标是否已经满足 |

评测指标可以从这些查询反推：

```text
state accuracy
state interval accuracy
goal satisfaction accuracy
state diff precision / recall
WHY_STATE evidence precision / recall
late-arrival repair accuracy
uncertainty calibration
query latency
update throughput
memory footprint
```

## 11. 最小可跑实验版本

第一版不需要一上来接完整 OmniGibson runtime。最小可跑版本可以是：

```text
1. 从 BDDL 中抽取 init / goal predicate instances
2. 构造简单 synthetic state timeline
3. 生成 clean observations
4. 注入 delay / missing / conflict
5. 实现 Latest Observation 和 Temporal Log + Voting
6. 跑 CHECK_STATE / AS_OF_STATE / WHY_STATE / CHECK_GOAL
7. 报告不同 regime 下的 accuracy 和 evidence correctness
```

这样就能证明 benchmark 的核心价值：同一个任务状态，在不同 observation 扰动下，不同维护策略会产生不同的内部维护结果、证据解释和最终 QueryAnswer。

## 12. 最核心的实验图

建议论文或汇报中画一张主图：

```text
BEHAVIOR / BDDL task
        |
        v
Ground-truth state timeline
        |
        v
Perturbation injector
  clean / noisy / delayed / missing / conflict
        |
        v
Observation stream
        |
        v
Query set + Baselines / EviStateDB
        |
        v
Predicted QueryAnswers
        |
        v
Evaluator compares with Ground-truth Answers
```

这张图能把整个 idea 讲清楚：EviStateBench 不是做感知，也不是做规划，而是评测系统能否从具身 observation stream 中回答可审计的任务状态查询。

## 13. 一句话总结

EviStateBench 的关键不在于“机器人记住了什么”，而在于“系统如何把不可靠、异步、冲突的具身观察维护成可查询、可修正、可解释的时态任务状态视图”，实验也应该围绕这个维护过程和查询结果来设计。
