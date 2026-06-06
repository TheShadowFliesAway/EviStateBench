# EviStateBench / EviStateDB Final Frozen IDEA

> 论文形态：ICDE EAB  
> 论文主角：EviStateBench  
> Reference engine：EviStateDB  
> 核心问题：Temporal Task-State View Maintenance over Embodied Observation Streams  
> 当前状态：定稿。后续只补实现细节、实验数字、引用、图表和消融，不再改问题中心。

---

## 1. Final Title

```text
[Experiment, Analysis, and Benchmark] EviStateBench:
Evaluating Temporal Task-State View Maintenance over Embodied Observation Streams
```

参考系统名：

```text
EviStateDB
```

---

## 2. One-sentence Summary

**EviStateBench is a data-management benchmark for evaluating how systems maintain auditable temporal task-state views from noisy, delayed, out-of-order, missing, and conflicting embodied observation streams.**

**EviStateDB is the reference materialized-view engine for this benchmark.**

中文固定表述：

```text
EviStateBench 是一个面向数据管理的 benchmark，用来评测系统如何从带噪声、延迟、乱序、缺失和冲突的具身观察流中，维护可审计的时态任务状态视图。

EviStateDB 是该 benchmark 的 reference materialized-view engine。
```

---

## 3. Final Positioning

本项目固定定位为：

```text
temporal task-state view maintenance benchmark + reference engine
```

禁止作为主定位的说法：

```text
embodied memory database
long-term robot memory system
task-conditioned retrieval system
symbolic state estimation system
robot planning system
VLM / perception system
general embodied database
```

论文要表达的是：

```text
已有 embodied memory、embodied QA、state estimation、goal reasoning、retrieval 和 general view-maintenance 方法很多，
但缺少一个面向数据系统社区的 benchmark，系统性评测：

1. 在 noisy / delayed / out-of-order / missing / conflicting embodied observation streams 上，
2. 如何维护 temporal task-state views，
3. 如何回答 CHECK / AS_OF / DIFF / WHY / GOAL / PRECONDITION / UNCERTAIN / FAILURE queries，
4. 以及不同 baseline 在这个 workload 下各自失败在哪里。
```

---

## 4. Core Claim

最终主 claim：

```text
Embodied observation streams combine perceptual uncertainty, event-time/arrival-time mismatch, contradictory evidence, task-derived views, and provenance queries. EviStateBench brings these challenges together as a data-management benchmark for temporal task-state view maintenance.
```

中文：

```text
具身观察流同时具有感知不确定性、事件时间与到达时间错位、证据冲突、任务派生视图和证据溯源查询等特点。EviStateBench 将这些挑战统一成一个面向数据管理的 temporal task-state view maintenance benchmark。
例如，在一个“将杯子放入柜子并关闭柜门”的具身任务中，系统需要维护 inside(cup, cabinet)、open(cabinet)、grasped(robot, cup) 等任务状态。由于杯子可能被柜门遮挡，视觉检测器可能漏检 cup，深度关系估计器却可能判断 cup 已经位于 cabinet 内部，从而产生带置信度的感知不确定观测。与此同时，VLM 或关系检测模块的推理结果可能在事件发生数秒后才写入系统，使 observation 的 event_time 与 arrival_time 不一致。不同来源还可能给出相互冲突的判断：动作日志声称 place 动作成功，深度关系支持 inside(cup, cabinet)=true，而 RGB detector 由于遮挡给出 inside(cup, cabinet)=false。任务执行系统关心的也不仅是单条 observation，而是由这些状态派生出的 GoalView、PreconditionView 和 StateDiffView，例如当前目标是否满足、下一步 close(cabinet) 的前提是否成立，以及任务失败时哪个状态发生偏差。进一步地，当系统回答 WHY_STATE(inside(cup, cabinet), t) 时，还需要返回支持该状态的 observation、反驳该状态的 observation、置信度变化和历史修正记录。因此，具身观察流需要被维护为可查询、可修正、可追溯的时态任务状态视图。
```

不要写：

```text
We solve embodied memory.
We build the first embodied database.
We outperform embodied memory systems.
We solve robot symbolic state estimation.
We solve real-world robot state tracking.
```

固定写法：

```text
We introduce a benchmark and reference engine for temporal task-state view maintenance over embodied observation streams.
```

---

## 5. Data Model

### 5.1 StateObservation

Observation 是原始证据，不是最终状态。

```text
StateObservation(
  obs_id,
  episode_id,
  event_time,
  arrival_time,
  source,
  predicate_name,
  arguments,
  observed_value,
  confidence,
  polarity,
  evidence_ref,
  metadata
)
```

含义：

```text
某个来源在某个事件时间，以某个置信度声称某个任务状态成立、不成立，或对已有状态形成修正。
```

字段解释：

```text
event_time: 证据对应的真实发生时间
arrival_time: 系统收到证据的时间
source: detector / VLM / tracker / action log / simulator sensor / annotation
predicate_name: open, inside, ontop, grasped, temperature 等
arguments: predicate 的对象参数
observed_value: true / false / categorical / numeric
confidence: observation-level confidence
polarity: support / contradict / correction
evidence_ref: frame id / trajectory id / annotation id / detector output id
metadata: optional diagnostic information
```

---

### 5.2 TemporalStateView

TemporalStateView 是从 Observation Log 维护出来的物化时态状态视图。

```text
TemporalStateView(
  state_id,
  episode_id,
  predicate_name,
  arguments,
  value,
  valid_start,
  valid_end,
  transaction_start,
  transaction_end,
  confidence,
  support_observations,
  contradict_observations,
  status,
  revision_history
)
```

含义：

```text
系统在某个有效时间区间内，对某个任务状态的当前维护判断。
```

例子：

```text
inside(cup_1, cabinet_1) = true
valid_time = [08:20, now)
transaction_time = [08:23, now)
confidence = 0.86
support = [obs_17, obs_18]
contradict = [obs_21]
status = active
```

---

### 5.3 Task-derived Views

Task views 从 TemporalStateView 派生：

```text
GoalView(task_id, time)
PreconditionView(action_id, time)
StateDiffView(scope, t1, t2)
FailureView(episode_id)
UncertainStateView(task_id)
```

GoalView 示例：

```text
GoalView(task_7, now):
  satisfied = false
  satisfied_predicates = [inside(cup_1, cabinet_1)]
  violated_predicates = [open(cabinet_1)]
  uncertain_predicates = [grasped(robot_1, cup_1)]
  evidence = [...]
```

---

## 6. Why This Is a Data-Management Problem

### 6.1 Perception uncertainty

真实 observation 来自 detector、VLM、tracker、动作日志、深度估计、语言解释或仿真传感器，可能出现误检、漏检、关系错判和数值偏差。系统维护的是 uncertain state views，不能直接读取真值。

### 6.2 Event-time / arrival-time mismatch

具身系统里 observation pipeline 异步运行。一个状态证据可能在 08:05 发生，08:30 才进入系统。系统必须区分：

```text
event_time / valid_time
arrival_time / transaction_time
```

这使问题具有 bitemporal semantics。

### 6.3 Contradictory evidence

不同来源可能对同一 predicate instance 给出相反结论。系统必须维护：

```text
support observations
contradict observations
confidence update
revision history
interval close / repair
```

### 6.4 Task-derived views

任务系统关心的不是孤立 observation，而是：

```text
goal 是否满足
precondition 是否满足
状态何时变化
失败可能定位到哪个状态
哪些状态不确定
为什么相信当前判断
```

### 6.5 Provenance queries

WHY_STATE、FAILURE_LOCALIZATION 和 evidence query 是数据管理味道最强的部分。系统需要返回支持证据、反驳证据、修正历史和置信度来源。

---

## 7. EviStateBench Generator

主实验使用：

```text
BEHAVIOR / OmniGibson-derived benchmark
```

生成内容：

```text
ground-truth state timelines
clean observations
noisy observations
delayed observations
out-of-order observations
missing observations
conflicting observations
query sets
ground-truth answers
```

主数据源选择理由：

```text
1. BEHAVIOR / BDDL 有 initial conditions 和 goal conditions；
2. OmniGibson 有丰富 object states；
3. simulator 可以给出 ground-truth state timeline；
4. 可以系统性注入 noise、delay、out-of-order、missing、conflict；
5. 能覆盖多种 predicate 类型和任务视图查询。
```

---

## 8. Predicate Scope

### Unary boolean predicates

```text
open(drawer)
cooked(food)
frozen(food)
folded(cloth)
burnt(food)
sliced(food)
```

### Binary / spatial relation predicates

```text
inside(object, container)
ontop(object, surface)
nextto(object, object)
under(object, object)
touching(object, object)
```

### Material / particle state predicates

```text
filled(container, substance)
covered(object, substance)
saturated(object, substance)
contains(container, substance)
```

### Robot-specific predicates

```text
grasped(robot, object)
objects_in_fov(robot)
reachable(robot, object)
holding(robot, object)
```

### Numeric predicates

```text
temperature(object)
pose(object)
max_temperature(object)
distance(object, object)
```

---

## 9. Perturbation Regimes

必须做成主实验变量：

```text
R0 clean
R1 noisy
R2 delayed
R3 out-of-order
R4 conflicting
R5 missing
R6 mixed
```

每个 regime 至少控制这些参数：

```text
noise_rate
delay_rate
out_of_order_rate
conflict_rate
missing_rate
confidence_noise
```

mixed regime 是主压力测试：

```text
mixed = noisy + delayed + out-of-order + missing + conflicting
```

---

## 10. Query Workloads

```text
W1 CHECK_STATE
W2 AS_OF_STATE
W3 STATE_DIFF
W4 WHY_STATE
W5 CHECK_GOAL
W6 CHECK_PRECONDITION
W7 FIND_UNCERTAIN_STATES
W8 FAILURE_LOCALIZATION
```

### W1 CHECK_STATE

```text
CHECK_STATE(predicate, arguments, time)
```

回答某个状态在某个时间是否成立。

### W2 AS_OF_STATE

```text
AS_OF_STATE(predicate, arguments, valid_time, transaction_time)
```

回答在某个系统知识版本下，某个有效时间的状态判断。

### W3 STATE_DIFF

```text
STATE_DIFF(scope, t1, t2)
```

回答两个时间点之间发生了哪些状态变化。

### W4 WHY_STATE

```text
WHY_STATE(predicate, arguments, time)
```

返回当前状态判断的 support evidence、contradict evidence、confidence 和 revision history。

### W5 CHECK_GOAL

```text
CHECK_GOAL(task_id, time)
```

回答任务目标是否满足，并列出 satisfied / violated / uncertain predicates。

### W6 CHECK_PRECONDITION

```text
CHECK_PRECONDITION(action_id, time)
```

回答下一步动作前提是否满足。

### W7 FIND_UNCERTAIN_STATES

```text
FIND_UNCERTAIN_STATES(task_id, time, threshold)
```

返回低置信度、高冲突或证据不足的状态。

### W8 FAILURE_LOCALIZATION

```text
FAILURE_LOCALIZATION(episode_id)
```

定位失败可能对应的状态变化、前提违背或目标未满足原因。

---

## 11. Metrics

### Correctness metrics

```text
state truth accuracy
state interval F1
state diff precision / recall
goal satisfaction accuracy
precondition checking accuracy
failure state localization accuracy
numeric state error
```

### Evidence metrics

```text
support evidence precision / recall
contradict evidence precision / recall
why-query correctness
revision correctness
```

### Robustness metrics

```text
accuracy vs noise rate
accuracy vs delay rate
accuracy vs out-of-order rate
accuracy vs conflict rate
accuracy vs missing rate
late-arrival repair accuracy
uncertain-state calibration
```

### System metrics

```text
update throughput
p50 query latency
p95 query latency
memory footprint
index size
out-of-order repair cost
view maintenance overhead
```

---

## 12. Baselines

### B1 Latest Observation

每个 predicate instance 直接采用最新 observation。

### B2 Temporal Log + Voting

保存所有 observations，查询时按时间窗口过滤并投票。

### B3 Static Symbolic State

只维护当前 symbolic state，不维护 history、valid-time interval、transaction-time repair 和 provenance。

### B4 SQL / DuckDB Scan

用 DuckDB / SQLite 存 observation log，每次查询 scan + group-by + heuristic。

### B5 Recall Memory Baseline

模拟 eMEM / STaR 类型系统：

```text
store observations
retrieve top-k by semantic/time/spatial similarity
aggregate retrieved observations with heuristic
answer state query
```

### B6 Generic IVM Baseline

使用通用 incremental view maintenance / materialized view 思路，只维护 query result，不专门处理 support/contradict evidence、late repair 和 task-derived views。

### B7 EviStateDB

参考引擎，维护：

```text
materialized temporal state views
valid-time intervals
transaction-time repair
support / contradict evidence
confidence update
revision history
goal / precondition derived views
predicate-time-evidence-task indexes
```

---

## 13. EviStateDB Reference Engine

EviStateDB 只作为 reference engine，不主张最强系统。

职责：

```text
1. StateObservation ingestion
2. predicate schema validation
3. confidence update
4. support / contradict provenance tracking
5. valid-time interval maintenance
6. transaction-time versioning
7. delayed / out-of-order repair
8. derived goal / precondition views
9. state diff maintenance
10. uncertainty tracking
11. indexes for predicate-args, time, evidence, confidence, task
12. CHECK / AS_OF / DIFF / WHY / GOAL / PRECONDITION / UNCERTAIN / FAILURE queries
```

---

## 14. Experiments

### Experiment 1: State Tracking

问题：

```text
不同方法维护基础状态视图的准确性如何？
```

指标：

```text
state truth accuracy
state interval F1
numeric state error
```

---

### Experiment 2: Robustness under Perturbations

问题：

```text
noise、delay、out-of-order、conflict、missingness 如何影响不同方法？
```

指标：

```text
accuracy vs noise_rate
accuracy vs delay_rate
accuracy vs conflict_rate
late-arrival repair accuracy
uncertain-state calibration
```

---

### Experiment 3: Goal Satisfaction Monitoring

问题：

```text
不同方法能否正确判断任务目标是否满足？
```

指标：

```text
goal satisfaction accuracy
violated predicate recall
uncertain predicate recall
```

---

### Experiment 4: Precondition Checking

问题：

```text
不同方法能否正确判断下一步动作前提？
```

指标：

```text
precondition checking accuracy
false positive rate
false negative rate
```

---

### Experiment 5: State Diff / Restoration

问题：

```text
不同方法能否正确找出两个时间点之间的状态差异？
```

指标：

```text
state diff precision
state diff recall
state interval boundary error
```

---

### Experiment 6: WHY_STATE / Evidence Query

问题：

```text
不同方法能否返回正确支持证据和反驳证据？
```

指标：

```text
support evidence precision / recall
contradict evidence precision / recall
why-query correctness
revision correctness
```

---

### Experiment 7: Query Processing and Scalability

问题：

```text
materialized temporal state views 相比 log scan 的 latency / update trade-off 如何？
```

指标：

```text
update throughput
p50 / p95 query latency
memory footprint
index size
repair cost
```

---

### Experiment 8: Ablation

问题：

```text
valid time、arrival time、confidence、contradict provenance、index、late repair 各自是否必要？
```

消融项：

```text
without valid-time intervals
without transaction-time repair
without confidence
without contradict evidence
without revision history
without indexes
without task-derived views
```

---

### Experiment 9: External Data Validation

必须加，但不承担主 correctness claim。

候选数据：

```text
DROID small sample
EPIC-KITCHENS annotations
OpenEQA episode histories
```

目标：

```text
1. schema can ingest real embodied observations;
2. evidence_ref can point to real frames / annotations;
3. query interface can run on real data;
4. provenance and uncertainty fields are meaningful outside simulation.
```

---

## 15. Expected Lessons Learned

论文最终至少要产出这些分析结论：

```text
L1. Recall-memory methods can retrieve evidence, but do not reliably maintain goal/precondition state views.
L2. Latest-observation methods are fast but fragile under noisy and conflicting evidence.
L3. Temporal-log methods can recover history but pay high query cost and handle late repair poorly.
L4. Bitemporal semantics matter most under delayed and out-of-order observations.
L5. Support/contradict provenance is necessary for WHY_STATE and failure localization.
L6. Materialized temporal state views trade update overhead for lower query latency and better goal/precondition correctness.
L7. Task-derived views expose errors that are hidden by predicate-level accuracy alone.
L8. External real-data validation shows schema portability, while simulator-derived data remains necessary for controlled correctness evaluation.
```

---

## 16. Related Work Boundaries

### Embodied memory / embodied QA

包括：

```text
eMEM
STaR
STARBench
OpenEQA
```

区分：

```text
这些工作主要评测 recall、retrieval、object search 或 embodied question answering。
EviStateBench 评测 temporal task-state view maintenance、late repair、goal/precondition checking 和 WHY evidence queries。
```

### BEHAVIOR / OmniGibson

区分：

```text
BEHAVIOR / OmniGibson 是 task predicates、object states 和 simulator truth 的来源。
EviStateBench 评测从扰动 observation streams 到 temporal state views 的维护和查询。
```

### Symbolic state estimation

区分：

```text
Symbolic state estimation 关注如何从 observations 估计 symbolic state。
EviStateBench 关注数据系统如何维护状态视图、修正历史、追踪证据和回答任务级查询。
```

### IVM / temporal DB / stream processing

区分：

```text
这些工作提供 view maintenance、event-time processing、bitemporal modeling 的基础。
EviStateBench 提供具身任务状态场景下的 workload、data model、query templates、perturbation generator 和 baseline analysis。
```

### Provenance / uncertain data

区分：

```text
这些工作研究 query explanation、uncertain facts 和 result provenance。
EviStateBench 将 support / contradict evidence、confidence 和 revision history 放入 embodied task-state view maintenance workload。
```

---

## 17. Paper Structure

```text
1. Introduction
2. Background and Motivation
3. Problem Definition
4. EviStateBench Benchmark
5. EviStateDB Reference Engine
6. Experimental Setup
7. Evaluation and Analysis
8. External Data Validation
9. Lessons Learned
10. Related Work
11. Conclusion
```

---

## 18. Minimum Viable Implementation Plan

### Phase 1: Data schema and synthetic generator

完成：

```text
StateObservation schema
TemporalStateView schema
predicate schema
episode state timeline extraction
noise/delay/out-of-order/conflict/missing injection
query generator
ground-truth answer generator
```

### Phase 2: Baselines

完成：

```text
Latest Observation
Temporal Log + Voting
Static Symbolic State
SQL / DuckDB Scan
Recall Memory Baseline
EviStateDB reference engine
```

Generic IVM baseline 可作为加强项。

### Phase 3: Query workloads

完成：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
WHY_STATE
CHECK_GOAL
CHECK_PRECONDITION
FIND_UNCERTAIN_STATES
FAILURE_LOCALIZATION
```

### Phase 4: Main experiments

完成：

```text
state tracking
robustness
goal satisfaction
precondition checking
state diff
WHY_STATE
scalability
ablation
```

### Phase 5: External validation

完成：

```text
small real-data ingestion
evidence_ref to frames / annotations
query examples
qualitative examples
```

---

## 19. Final Decision

```text
能投 ICDE。
有改动。
改动已经完成。
```

最终定稿：

```text
EviStateBench 是论文主角；
EviStateDB 是 reference engine；
核心问题是 temporal task-state view maintenance；
主实验来自 BEHAVIOR / OmniGibson-derived benchmark；
必须包含 noisy / delayed / out-of-order / missing / conflicting perturbations；
必须包含 WHY_STATE / provenance / support-contradict evidence；
必须加入小规模 external data validation；
论文形态固定为 ICDE EAB；
不再使用 embodied memory database 或 lifelong memory system 作为主定位。
```

一句话执行口径：

```text
Do not build another embodied memory system. Build a benchmark that exposes why maintaining auditable temporal task-state views from imperfect embodied observation streams is a distinct data-management workload.
```
