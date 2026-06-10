# EviStateBench / EviStateDB Final Frozen IDEA

> 论文形态：ICDE EAB  
> 论文主角：EviStateBench  
> Reference baseline engine：EviStateDB  
> 核心问题：Temporal Task-State View Maintenance over Embodied Observation Streams  
> 当前状态：理想版问题中心定稿。后续只补实验设计、实验数字、引用、图表和消融，不写当前工程状态。

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

**EviStateDB is the reference baseline engine for this benchmark, not the oracle.**

**Ground-truth answers are generated from simulator truth and task specifications.**

中文固定表述：

```text
EviStateBench 是一个面向数据管理的 benchmark，用来评测系统如何从带噪声、延迟、乱序、缺失和冲突的具身观察流中，维护可审计的时态任务状态视图。

EviStateDB 是该 benchmark 的 reference baseline engine，不是 oracle。

标准答案由 simulator truth 和 task specification 生成，不由 EviStateDB 生成。
```

---

## 3. Final Positioning

本项目固定定位为：

```text
temporal task-state view maintenance benchmark + reference baseline engine
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
3. 如何回答以 CHECK_STATE / AS_OF_STATE / STATE_DIFF / CHECK_GOAL 为核心的 query workloads，
   并在 supplemental workloads 中支持 WHY / PRECONDITION / UNCERTAIN / FAILURE analysis，
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
We introduce a benchmark and a reference baseline engine for temporal task-state view maintenance over embodied observation streams. The benchmark oracle generates ground-truth answers from simulator truth and task specifications, not from EviStateDB.
```

---

## 5. Data Model

本节区分两类对象：

```text
Public benchmark artifacts:
  StateObservation streams
  query sets
  ground-truth answers
  predicted QueryAnswers

Reference / conceptual internal artifacts:
  TemporalStateView
  GoalView / PreconditionView / StateDiffView / FailureView / UncertainStateView
```

EviStateBench 对外评测的是系统输出的 predicted QueryAnswers，不要求任意被测系统暴露 TemporalStateView。

### 5.1 StateObservation

Observation 是原始证据，不是最终状态。

```text
StateObservation(
  obs_id,
  episode_id,
  event_time,
  arrival_time,
  source,
  observation_kind,
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
observation_kind: predicate_state / object_pose / object_velocity / joint_state / numeric_state 等
predicate_name: open, inside, ontop, grasped, temperature 等
arguments: predicate 的对象参数
observed_value: true / false / categorical / numeric / JSON-like measurement
confidence: observation-level confidence
polarity: support / contradict / correction
evidence_ref: frame id / trajectory id / annotation id / detector output id
metadata: optional diagnostic information
```

---

### 5.2 TemporalStateView

TemporalStateView 是从 Observation Log 维护出来的物化时态状态视图。

注意：TemporalStateView 不是 EviStateBench 的 public output schema。它用于：

```text
1. 描述 benchmark 想评测的逻辑语义；
2. 作为 EviStateDB reference baseline engine 的内部维护结构；
3. 帮助 oracle / evaluator 定义 valid-time、transaction-time、evidence 和 revision 语义。
```

其他 baseline 或被测系统可以使用 retrieval、log scan、SQL、neural memory、rules 或任何内部表示。它们只需要对外输出统一格式的 predicted QueryAnswers。

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

Task views 在 EviStateDB 内部可以从 TemporalStateView 派生；在 benchmark 层面，它们对应的是 query workload 和 answer schema，而不是要求所有系统暴露这些 view。

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

注意：

```text
ground-truth answers 由 simulator truth、BDDL/task specification 和 perturbation log 生成。
EviStateDB 不负责生成标准答案；EviStateDB 只是一个会被 evaluator 打分的 reference baseline engine。
```

主数据源选择理由：

```text
1. BEHAVIOR / BDDL 有 initial conditions 和 goal conditions；
2. OmniGibson 有丰富 object states；
3. simulator 可以给出 ground-truth state timeline；
4. 可以系统性注入 noise、delay、out-of-order、missing、conflict；
5. 能覆盖多种 predicate 类型和任务视图查询。
```

理想版本中，generator 应尽量覆盖三类 action / observation source：

```text
main controlled simulator-grounded source
  semantic primitive / policy / replay action source
  simulator truth timeline
  clean structured StateObservation
  perturbed public observation streams

supplemental low-level rollout source
  starter / policy rollout
  lower-level execution traces
  用于分析 action gap

supplemental perception-derived source
  RGB / depth / detector / VLM-derived observations
  用于分析 observation gap
```

论文理想表述应是：

```text
主 benchmark 隔离 low-level control 和 perception，集中评测 temporal task-state view maintenance；
补充 subset 用于分析 simulator-derived structured observations 与真实感知 / 真实执行之间的 gap。
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

主论文 correctness claim 使用 core query workloads：

```text
W1 CHECK_STATE
W2 AS_OF_STATE
W3 STATE_DIFF
W5 CHECK_GOAL
```

supplemental / artifact-release workloads：

```text
W4 WHY_STATE
W6 CHECK_PRECONDITION
W7 FIND_UNCERTAIN_STATES
W8 FAILURE_LOCALIZATION
```

完整接口仍保留八类 query，方便后续扩展 provenance、precondition、uncertainty 和 failure analysis。

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

论文主实验不追求穷尽所有可定义指标，而是围绕 benchmark 的核心 claim 报告少量高区分度指标。

主论文指标分成四组：

```text
artifact characterization
correctness under temporal task-state queries
robustness under representative observation perturbations
system cost of maintaining temporal state views
```

### Main correctness metrics

```text
state truth accuracy
state diff precision / recall
goal satisfaction accuracy
AS_OF_STATE correctness
unknown / uncertain calibration
```

### Main robustness metrics

```text
clean-to-mixed degradation
missing robustness
temporal disorder robustness
conflict robustness
late-arrival repair accuracy
```

### Main system metrics

```text
p50 query latency
p95 query latency
update throughput
memory footprint
```

### Supplemental metrics

```text
state interval F1
support evidence precision / recall
contradict evidence precision / recall
why-query correctness
precondition checking accuracy
failure state localization accuracy
numeric state error
index size
out-of-order repair cost
view maintenance overhead
```

---

## 12. Baselines

主论文不需要把所有可想到的方法都放进主表。主表保留能支撑核心 claim 的代表性 baseline；
其余方法不作为投稿正文主表 baseline，可放 artifact release / technical report，或作为 ablation 变体。

### B1 Latest Observation / Arrival-latest, diagnostic only

每个 predicate instance 直接采用最新 observation。

该方法只作为内部 sanity lower bound：用于检查 delay / out-of-order /
conflict 扰动是否真的破坏 naive 状态维护。它不进入投稿正文主表，
也不作为 benchmark 贡献的主要证据。

### B2 Temporal Log + Voting

保存所有 observations，查询时按时间窗口过滤并投票。

主论文主表中，Temporal Log + Voting 和 SQL / DuckDB Scan 可以合并为一个
`Temporal Log / SQL Scan` 代表 baseline；具体实现可以采用 DuckDB / SQLite。

### B3 Static Symbolic State

只维护当前 symbolic state，不维护 history、valid-time interval、transaction-time repair 和 provenance。

该 baseline 不进入投稿正文主表；它的失败模式和 Latest Observation 部分重叠，可放 artifact release / technical report。

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

该 baseline 可以作为 EviStateDB ablation，或放 artifact release / technical report。

### B7 EviStateDB

reference baseline engine，维护：

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

## 13. EviStateDB Reference Baseline Engine

EviStateDB 只作为 reference baseline engine，不主张最强系统，也不是 benchmark oracle。

标准答案由 simulator truth 和 task specification 生成；EviStateDB 输出 predicted answers，并和其他 baseline 一样被 evaluator 打分。

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
12. core CHECK / AS_OF / DIFF / GOAL queries, plus supplemental WHY / PRECONDITION / UNCERTAIN / FAILURE queries
```

---

## 14. Experiments

本节采用 ICDE / VLDB benchmark paper 风格：先报告 artifact profile，再用少量主实验回答核心 claim。
不把每个 query type、每类扰动、每个状态族和每个系统模块都展开成独立大实验。

核心实验原则：

```text
1. artifact characterization 证明 benchmark 的覆盖、规模和可复现性；
2. main comparison 证明 benchmark 能区分状态维护方法和 retrieval / log baselines；
3. query breakdown 证明问题不是普通 retrieval 或 latest-state lookup；
4. robustness 证明扰动 observation stream 会暴露 temporal state maintenance 的必要性；
5. efficiency + ablation 证明 EviStateDB 的系统代价和关键组件贡献。
```

正式论文主实验只保留四个：

```text
E1 Main benchmark results
E2 Query semantics breakdown
E3 Robustness under representative perturbations
E4 Efficiency and ablation
```

WHY_STATE、PRECONDITION_CHECK、UNCERTAIN_STATE、FAILURE_LOCALIZATION、perception-derived streams
和 low-level rollout subsets 作为 supplemental analysis，而不是主 correctness claim。

### Artifact Characterization

问题：

```text
EviStateBench 是否提供了可复现、有覆盖、有区分度的 temporal task-state benchmark artifact？
```

报告：

```text
tasks
episodes
predicate families
objects
hidden timeline events
clean observations
public observation streams
queries by workload
perturbation regimes
splits
artifact size
generation / validation protocol
```

说明：

```text
这部分是 benchmark characterization，不作为方法性能实验。
它对应 benchmark paper 中的 dataset / workload / pipeline profile。
```

---

### E1 Main Benchmark Results

问题：

```text
在统一 public observation streams 和 query workloads 下，显式 temporal task-state view maintenance
是否优于 log scan 和 recall memory 类方法？
```

主表 baseline：

```text
Temporal Log / SQL Scan
Recall Memory
EviStateDB
```

主表 regime：

```text
clean
missing
temporal disorder
conflict
mixed
```

主指标：

```text
overall exact accuracy
state truth accuracy
AS_OF_STATE correctness
STATE_DIFF F1
CHECK_GOAL accuracy
```

预期 takeaway：

```text
retrieval memory can recall relevant evidence but does not maintain bitemporal task-state views;
EviStateDB improves correctness especially under temporal disorder, conflict, and mixed streams.
```

---

### E2 Query Semantics Breakdown

问题：

```text
哪些 query semantics 最能暴露 retrieval / latest-state baseline 的失败？
```

主论文 query types：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL
```

报告：

```text
query type × baseline accuracy
query type × regime degradation
representative failure examples
```

不进入投稿正文主表的 query types：

```text
WHY_STATE
PRECONDITION_CHECK
UNCERTAIN_STATE
FAILURE_LOCALIZATION
```

预期 takeaway：

```text
CHECK_STATE may be partially solved by local evidence;
AS_OF_STATE and STATE_DIFF require valid-time / transaction-time semantics;
CHECK_GOAL requires task-derived views rather than isolated predicate lookup.
```

---

### E3 Robustness Under Representative Perturbations

问题：

```text
代表性 observation stream 扰动如何影响不同 baseline？
```

主论文 perturbation regimes：

```text
clean
missing
temporal disorder = delay + out_of_order
conflict
mixed
```

不做主实验的内容：

```text
all pairwise perturbation combinations
full perturbation strength sweep
every predicate family × every perturbation
```

这些可以放 artifact release / technical report。

指标：

```text
clean-to-perturbed degradation
late-arrival repair accuracy
unknown / uncertain calibration
conflict robustness
```

预期 takeaway：

```text
single perturbations diagnose failure modes;
mixed streams act as the realistic proxy;
temporal state views are most useful when observations are delayed, conflicting, missing, or mixed.
```

---

### E4 Efficiency And Ablation

问题：

```text
EviStateDB 维护 temporal task-state views 的系统代价是多少？哪些组件真正贡献性能和正确性？
```

效率指标：

```text
p50 / p95 query latency
update throughput
memory footprint
scale with #observations / #episodes
```

主论文 ablation：

```text
without transaction-time repair
without support / contradict provenance
without task-derived views
without confidence / unknown handling
```

不进入投稿正文主表的 ablation：

```text
without indexes
without revision history
without recall fallback
different stream compression / storage choices
```

预期 takeaway：

```text
materialized temporal state views trade update and memory overhead for lower query latency and better temporal correctness;
transaction-time repair and task-derived views are essential for AS_OF_STATE, STATE_DIFF, and CHECK_GOAL.
```

---

### Supplemental External Validation

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

该部分可以作为正文 discussion 中的 supplemental analysis；若篇幅不足，放 artifact release / technical report：

```text
perception-derived observation subset
low-level rollout / policy subset
schema portability check
qualitative gap analysis
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
5. EviStateDB Reference Baseline Engine
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
public query / answer schema
predicate schema
episode state timeline extraction
noise/delay/out-of-order/conflict/missing injection
query generator
ground-truth answer generator from simulator truth and task specifications
```

### Phase 1b: Real simulator-grounded generator

```text
live OmniGibson recorder
explicit action-source replay / policy rollout / demo replay support
simulator truth snapshots
hidden state timeline extraction
clean StateObservation extraction
public artifact builder
public artifact validator
profile / quality / baseline sanity reports
supplemental perception-derived subset
```

### Phase 2: Baselines

主论文最低完成：

```text
Temporal Log / SQL Scan
Recall Memory Baseline
EviStateDB reference baseline engine
```

补充 / artifact release：

```text
Latest Observation / Arrival-latest sanity lower bound
Static Symbolic State
Generic IVM baseline
additional neural / LLM memory variants
```

### Phase 3: Query workloads

主论文最低完成：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL
```

补充 / artifact release：

```text
WHY_STATE
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
EviStateDB 是 reference baseline engine，不是 oracle；
标准答案由 simulator truth 和 task specification 生成；
核心问题是 temporal task-state view maintenance；
主实验来自 BEHAVIOR / OmniGibson-derived benchmark；
benchmark generator 必须能支持 noisy / delayed / out-of-order / missing / conflicting perturbations；
主论文报告 clean / missing / temporal disorder / conflict / mixed；其他单类扰动和 severity sweep 放 artifact release / technical report；
WHY_STATE / provenance / support-contradict evidence 作为 supplemental / artifact-release workload；
必须加入小规模 external data validation；
论文形态固定为 ICDE EAB；
不再使用 embodied memory database 或 lifelong memory system 作为主定位。
```

一句话执行口径：

```text
Do not build another embodied memory system. Build a benchmark that exposes why maintaining auditable temporal task-state views from imperfect embodied observation streams is a distinct data-management workload.
```
