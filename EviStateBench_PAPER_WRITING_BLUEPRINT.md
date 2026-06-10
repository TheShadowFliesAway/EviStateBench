# EviStateBench Paper Writing Blueprint

本文档用于按理想版本撰写 EviStateBench 论文。它不是当前工程进度记录，
而是从 `EviStateBench_IDEA.md` 出发，把论文贡献、章节、实验、图表和写作约束拆成可执行写作计划。

目标论文形态：

```text
ICDE Experiment, Analysis, and Benchmark
```

ICDE benchmark / experimental study 写作基调：

```text
standardized artifact
unified evaluation pipeline
fair baseline comparison
workload diversity without experimental sprawl
effectiveness + efficiency metrics
clear reproducibility boundary
```

不要把论文写成“我们做了很多功能”。要写成：

```text
previous evaluations are inconsistent or miss this workload;
EviStateBench standardizes the data, workload, perturbations, and evaluation;
representative baselines are evaluated under the same protocol;
results reveal concrete lessons for future systems.
```

论文主角：

```text
EviStateBench
```

reference baseline engine：

```text
EviStateDB
```

一句话主张：

```text
EviStateBench is a data-management benchmark for evaluating temporal task-state
view maintenance over imperfect embodied observation streams.
```

---

## 1. Non-Negotiable Positioning

必须坚持：

```text
EviStateBench 是 benchmark。
EviStateDB 是 reference baseline engine。
oracle 来自 simulator truth + task specification。
EviStateDB 不是 oracle。
被测对象是 temporal task-state view maintenance。
```

不要写成：

```text
embodied memory database
robot memory system
task retrieval benchmark
symbolic state estimation benchmark
VLM perception benchmark
robot control benchmark
complete BEHAVIOR task completion benchmark
```

推荐固定表达：

```text
We introduce EviStateBench, a benchmark for evaluating how systems maintain
auditable temporal task-state views from noisy, delayed, out-of-order, missing,
and conflicting embodied observation streams.
```

```text
EviStateDB is a reference baseline engine evaluated by EviStateBench, not the
source of ground-truth answers.
```

---

## 2. Core Contributions

论文贡献建议写成四点：

```text
C1 Benchmark formulation
  将 embodied observation stream 下的 task-state view maintenance 形式化为
  数据管理 benchmark，而不是 retrieval / memory recall。

C2 Data model and query workloads
  提出 StateObservation、TemporalStateView 语义、bitemporal event/arrival time、
  support / contradict evidence、以及以 CHECK_STATE / AS_OF_STATE / STATE_DIFF /
  CHECK_GOAL 为主的 core query workload。
  WHY_STATE / PRECONDITION / UNCERTAIN / FAILURE queries 作为 supplemental workloads
  展示 provenance、task precondition 和 failure analysis 能力。

C3 Simulator-grounded benchmark generator
  从 BEHAVIOR / OmniGibson task specifications 和 simulator truth 生成 hidden
  state timelines、clean observations、perturbed streams、query sets 和 hidden answers。

C4 Evaluation and analysis
  系统比较 Temporal Log / SQL Scan、Recall Memory 和 EviStateDB
  在代表性 perturbation regimes、core query workloads 和 task-derived views 下的表现。
  Latest Observation / Arrival-latest 只作为 sanity lower bound；
  Static Symbolic State、Generic IVM 和更多 neural / LLM memory variants 不作为投稿正文主表，
  可作为 ablation、artifact release 或 technical report 中的 supplemental baselines。
```

可选第五点：

```text
C5 Gap analysis
  用 low-level rollout subset 和 perception-derived subset 分析 structured
  simulator-derived benchmark 与真实执行 / 真实感知之间的 gap。
```

---

## 2.5 ICDE-Style Reviewer Questions

写作时要主动回答这些问题。

```text
RQ1 Benchmark need
  现有 embodied memory / QA / state estimation / simulator benchmarks 为什么不能评测
  temporal task-state view maintenance？

RQ2 Fairness and reproducibility
  EviStateBench 如何统一 public inputs、query workloads、splits、answer schema、
  evaluator 和 reporting，使不同 systems 可以公平比较？

RQ3 Workload difficulty
  哪些 query semantics 和 perturbation regimes 会暴露 retrieval / latest / log baselines
  的失败？

RQ4 Reference baseline
  EviStateDB 相比 retrieval-style memory 和 log-scan baselines 的收益来自哪些系统机制？
  代价是什么？

RQ5 Scope boundary
  主 benchmark 为什么隔离 low-level control 和 perception？supplemental subsets 如何
  分析 action gap 和 observation gap？
```

推荐把这些 RQ 映射到实验：

```text
RQ1 -> Related benchmark comparison + Artifact Characterization
RQ2 -> Benchmark protocol + validation / leakage checks
RQ3 -> E1 Main Results + E2 Query Breakdown + E3 Robustness
RQ4 -> E4 Efficiency and Ablation
RQ5 -> Supplemental External Validation / Discussion
```

---

## 3. Paper Skeleton

建议章节：

```text
1. Introduction
2. Background and Motivation
3. Problem Definition
4. EviStateBench Benchmark
5. Benchmark Generator
6. EviStateDB Reference Baseline Engine
7. Experimental Setup
8. Evaluation and Analysis
9. External / Supplemental Validation
10. Lessons Learned
11. Related Work
12. Conclusion
```

如果页数紧张，可以合并：

```text
4 + 5: EviStateBench Design
7 + 8: Experiments
9 + 10: Discussion
```

---

## 4. Section-by-Section Writing Plan

### 4.1 Introduction

目标：

```text
把问题从 embodied memory / VLM / robot control 中切出来，落到 data management。
```

必须回答：

```text
1. 为什么 embodied systems 会产生 imperfect observation streams？
2. 为什么任务系统需要 temporal task-state views？
3. 为什么 retrieval / latest observation / static symbolic state 不够？
4. 为什么需要 benchmark，而不仅是一个新系统？
5. EviStateBench 和 EviStateDB 分别是什么？
```

建议结构：

```text
P1 具身系统不断产生 observation streams，但这些 observations noisy、late、missing、conflicting。
P2 任务执行需要维护 task-state views，而不是只检索历史片段。
P3 现有 benchmark 多关注 memory recall、QA、navigation、state estimation，缺少 temporal view maintenance workload。
P4 EviStateBench 的定义和 artifact。
P5 Contributions。
```

不要在 introduction 里过早讲工程细节。

### 4.2 Background And Motivation

用一个贯穿例子：

```text
把杯子放进柜子并关闭柜门
```

展示：

```text
inside(cup, cabinet)
open(cabinet)
grasped(robot, cup)
event_time vs arrival_time
detector / VLM / action log conflict
goal / precondition / why queries
```

这一节的目标是让数据库读者明白：

```text
这是 stream processing + temporal DB + uncertain data + provenance + task semantics 的交叉问题。
```

### 4.3 Problem Definition

定义对象：

```text
Episode
Task specification
StateObservation
Observation stream
TemporalStateView
Query
QueryAnswer
Ground-truth answer
```

定义时间：

```text
event_time / valid_time
arrival_time / transaction_time
```

定义评价任务：

```text
input: public observation stream + task spec + queries
output: predicted QueryAnswers
hidden: simulator truth + answer sets
```

关键澄清：

```text
TemporalStateView 是概念语义和 EviStateDB 内部表示，不是所有系统必须暴露的 public output。
```

### 4.4 EviStateBench Benchmark

写 benchmark 包含什么：

```text
task specs
observation streams
perturbation regimes
query workloads
answer sets
evaluation metrics
splits
```

按 query workloads 展开：

```text
core:
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL

supplemental:
WHY_STATE
CHECK_PRECONDITION
FIND_UNCERTAIN_STATES
FAILURE_LOCALIZATION
```

按 perturbation 展开：

```text
clean
low-confidence / noisy
delayed
out-of-order
conflicting
missing
mixed
```

强调 mixed 是主压力测试，single-factor regimes 用于诊断。主论文实验报告
`clean / missing / temporal disorder / conflict / mixed`；low-confidence、单独 delay、
单独 out-of-order、severity sweep 和所有扰动组合放 artifact release / technical report。

### 4.5 Benchmark Generator

理想 generator pipeline：

```text
BEHAVIOR / OmniGibson task instance
-> action-source rollout / replay
-> simulator truth snapshots
-> hidden state timeline
-> clean StateObservation stream
-> perturbation injection
-> query generation
-> hidden answer generation
-> sanitized public package
```

必须区分三类 source：

```text
main controlled simulator-grounded source
supplemental low-level rollout source
supplemental perception-derived source
```

必须写清两个 gap：

```text
action gap
observation gap
```

但写法要积极：

```text
主 benchmark 有意隔离 perception / low-level control，以便可控评测 state-view maintenance。
supplemental subset 用于分析和量化 gap。
```

### 4.6 EviStateDB Reference Baseline Engine

强调它是 baseline，不是 oracle。

写 EviStateDB 维护：

```text
observation log
TemporalStateView
valid intervals
transaction-time versions
support / contradict evidence
confidence
revision history
task-derived views
indexes
```

可以给出 high-level algorithms：

```text
ingest observation
update state belief
repair valid intervals
record transaction-time revision
answer query from materialized views
```

不要把 EviStateDB 写成唯一贡献。论文主角仍是 EviStateBench。

### 4.7 Experimental Setup

说明：

```text
dataset source
task split
predicate family split
horizon split
perturbation profiles
query workload distribution
baselines
metrics
hardware / runtime
```

必须写清 fair-comparison protocol：

```text
所有 baseline 读取同一个 public artifact；
所有 baseline 使用同一批 queries；
所有 baseline 禁止读取 hidden timeline、answer sets、perturbation labels；
所有 prediction 用同一个 evaluator；
每个运行报告 hardware、software version、runtime setting；
随机 seed、split、perturbation parameters 固定并公开。
```

必须报告 artifact profile：

```text
episodes
tasks
objects
observations
queries
hidden timeline events
public package size
stream sizes
predicate families
```

建议单独放一张 validation summary：

```text
public artifact validation status
leakage check status
query coverage
answer-set coverage
baseline sanity gap between clean and mixed
known limitations
```

### 4.8 Evaluation And Analysis

建议实验组织：

```text
Artifact Characterization
E1 Main benchmark results
E2 Query semantics breakdown
E3 Robustness under representative perturbations
E4 Efficiency and ablation
Supplemental external validation
```

每个实验写法：

```text
question
setup
metric
result
interpretation
takeaway
```

不要只堆表格；每个结果要回答数据管理 insight。

主论文实验要避免把每个 query type、每个扰动类型、每个状态族和每个系统组件都正交展开。
写作时按 claim 组织：

```text
benchmark 有覆盖和可复现性；
benchmark 能区分 retrieval/log/latest baselines 与 temporal state maintenance；
AS_OF_STATE、STATE_DIFF、CHECK_GOAL 暴露普通 memory retrieval 的不足；
代表性扰动会放大 temporal view maintenance 的优势；
EviStateDB 的关键组件带来正确性收益，并有可接受的系统代价。
```

### 4.9 External / Supplemental Validation

目标不是主 correctness claim。

写：

```text
schema portability
evidence_ref to frames / annotations
perception-derived observations
low-level rollout failure examples
gap analysis
```

### 4.10 Lessons Learned

建议 lessons：

```text
L1 Naive latest-observation sanity checks are fragile under conflicts and late arrivals.
L2 Retrieval-style memory can surface evidence but does not maintain task-state views.
L3 Bitemporal semantics matter for delayed and out-of-order observations.
L4 Support / contradict provenance is necessary for WHY and failure queries.
L5 Task-derived views expose errors hidden by predicate-level accuracy.
L6 Materialized temporal state views trade update overhead for lower query latency.
L7 Simulator-grounded structured observations enable controlled correctness evaluation.
L8 Supplemental subsets reveal action and observation gaps.
```

---

## 5. Figure Plan

### Figure 1: Motivation Example

内容：

```text
cup-cabinet task timeline
event_time vs arrival_time
conflicting detector / action log / relation evidence
queries asked over the maintained view
```

目的：

```text
让读者一图看懂为什么这不是 retrieval。
```

### Figure 2: Benchmark Architecture

内容：

```text
BEHAVIOR / OmniGibson
-> simulator truth
-> hidden timeline
-> clean observations
-> perturbation injector
-> public streams + queries
-> systems
-> predicted answers
-> evaluator
```

### Figure 3: Data Model

内容：

```text
StateObservation
TemporalStateView
QueryAnswer
support / contradict evidence
valid time / transaction time
```

### Figure 4: Query Workload Examples

展示 core query 的输入输出：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL
```

WHY_STATE / PRECONDITION / UNCERTAIN / FAILURE 作为 supplemental examples。

### Figure 5: Results Overview

内容：

```text
baseline performance under clean vs mixed
```

建议 Figure 5 不只画 accuracy，还要让读者看到 benchmark 的区分力：

```text
baseline x regime heatmap
query-type breakdown
clean-to-mixed degradation
```

---

## 6. Table Plan

### Table 1: Comparison With Related Benchmarks

列：

```text
Benchmark
Embodied tasks
Temporal state
Bitemporal semantics
Perturbations
Task-derived views
WHY / provenance
Ground-truth oracle
```

### Table 2: Artifact Statistics

列：

```text
split
episodes
tasks
predicate families
observations
queries
hidden events
public size
```

### Table 3: Query Workloads

列：

```text
query type
input
output
evaluated capability
metric
```

### Table 4: Perturbation Regimes

列：

```text
regime
data issue
parameters
system challenge
```

### Table 5: Baselines

列：

```text
baseline
state representation
history support
repair support
provenance support
expected weakness
```

---

## 7. Experiment Matrix

```text
Artifact Characterization
  Purpose: describe the benchmark artifact, not method performance.
  Report: tasks, episodes, predicate families, objects, observations, hidden events,
          queries, perturbation regimes, splits, artifact size, validation protocol.

E1 Main Benchmark Results
  Query: CHECK_STATE, AS_OF_STATE, STATE_DIFF, CHECK_GOAL
  Regimes: clean, missing, temporal disorder, conflict, mixed
  Baselines: Temporal Log / SQL Scan, Recall Memory, EviStateDB
  Metrics: overall exact accuracy, state truth accuracy, AS_OF_STATE correctness,
           STATE_DIFF F1, CHECK_GOAL accuracy
  Claim: EviStateDB-style temporal task-state view maintenance is stronger than
         retrieval/log baselines under the benchmark workload.

E2 Query Semantics Breakdown
  Query: CHECK_STATE, AS_OF_STATE, STATE_DIFF, CHECK_GOAL
  Metrics: query type x baseline accuracy, query type x regime degradation
  Analysis: show representative failures for retrieval memory and latest-state baselines
  Claim: the benchmark is not a plain retrieval or static state lookup benchmark.

E3 Robustness Under Representative Perturbations
  Regimes: clean, missing, temporal disorder = delay + out_of_order, conflict, mixed
  Metrics: clean-to-perturbed degradation, late-arrival repair accuracy,
           unknown / uncertain calibration, conflict robustness
  Claim: mixed and temporal-disorder streams expose the need for bitemporal view maintenance.

E4 Efficiency And Ablation
  Metrics: p50/p95 query latency, update throughput, memory footprint,
           scale with #observations / #episodes
  Main ablations: no transaction-time repair, no support/contradict provenance,
                  no task-derived views, no confidence/unknown handling
  Non-main ablations: no indexes, no revision history, no recall fallback,
                      storage/compression choices, reported in artifact release / technical report if needed
  Claim: materialized temporal state views trade modest update/memory overhead for
         lower query latency and better temporal correctness.

Supplemental External Validation
  Scope: perception-derived observations, low-level rollout subset, schema portability,
         qualitative action/observation gap analysis
  Claim: useful for gap analysis, but not the main correctness claim.
```

实验呈现注意：

```text
主表不要超过 4 个 baseline x 5 个 regimes。
query semantics breakdown 用 heatmap 或 grouped table，不要拆成四个独立实验。
robustness 不穷尽扰动排列组合，主文只保留代表性 regimes。
efficiency 和 ablation 可以合并为一个实验，避免系统贡献压过 benchmark 贡献。
supplemental subsets 明确标注为 gap analysis，不支撑主 correctness claim。
ICDE 无附录设置下，投稿正文不能依赖附录才成立；所有主 claim、
核心表格、主要 limitations 和 fair-comparison protocol 必须在正文内闭合。
```

---

## 8. Related Work Strategy

分组写，不要散：

```text
Embodied memory / embodied QA
  区分点：它们评测 recall / QA；EviStateBench 评测 maintained temporal task-state views。

BEHAVIOR / OmniGibson / embodied simulators
  区分点：它们提供 tasks 和 simulator truth；EviStateBench 提供 data-management workload。

Symbolic state estimation
  区分点：state estimation 关注估计 symbolic state；EviStateBench 关注 temporal view maintenance、
  repair、provenance 和 task-derived queries。

Temporal DB / stream processing / IVM
  区分点：这些是技术基础；EviStateBench 提供 embodied task-state benchmark。

Uncertain data / provenance
  区分点：EviStateBench 把 support / contradict evidence 放入 embodied task maintenance workload。
```

---

## 9. Writing Guardrails

### 9.1 Claims To Avoid

不要写：

```text
We solve embodied memory.
We build the first robot database.
We prove robots can complete BEHAVIOR tasks.
We solve low-level manipulation.
We solve visual perception.
EviStateDB generates ground truth.
```

### 9.2 Claims To Use

推荐写：

```text
EviStateBench evaluates temporal task-state view maintenance.
The oracle is derived from simulator truth and task specifications.
EviStateDB is a reference baseline engine.
The main benchmark isolates perception and control to enable controlled correctness evaluation.
Supplemental subsets analyze action and observation gaps.
```

### 9.3 Tone

写作风格：

```text
具体、克制、数据管理导向。
每个 claim 后面接 artifact / query / metric。
不要把概念讲成大而空的 embodied intelligence。
```

---

## 10. Abstract Draft Skeleton

英文摘要骨架：

```text
Embodied agents increasingly produce streams of observations from perception modules,
action logs, trackers, and task monitors. These streams are noisy, delayed,
out-of-order, missing, and sometimes contradictory, yet downstream task execution
requires auditable temporal views of task states.

We introduce EviStateBench, a data-management benchmark for temporal task-state
view maintenance over embodied observation streams. EviStateBench derives
simulator-grounded task-state timelines from BEHAVIOR / OmniGibson, generates
clean and perturbed StateObservation streams, and evaluates systems with query
workloads centered on state checks, bitemporal as-of queries, state diffs, and
goal monitoring, with supplemental provenance, precondition, uncertainty, and
failure-analysis queries.

We further provide EviStateDB, a reference baseline engine that maintains
bitemporal task-state views with support and contradict evidence. Experiments
compare EviStateDB with latest-observation, temporal-log, SQL-scan, recall-memory,
and supplemental view-maintenance baselines across representative perturbation
regimes and task splits. The results show ...
```

中文摘要骨架：

```text
具身智能系统会持续产生来自感知模块、动作日志、跟踪器和任务监控器的观察流。
这些观察流常常存在噪声、延迟、乱序、缺失和证据冲突，但下游任务执行需要维护
可查询、可修正、可追溯的时态任务状态视图。

本文提出 EviStateBench，一个面向数据管理的 benchmark，用于评测系统如何从具身观察流中
维护 temporal task-state views。EviStateBench 基于 BEHAVIOR / OmniGibson 生成
simulator-grounded hidden timelines、clean StateObservation streams、扰动 public streams、
query workloads 和 hidden ground-truth answers。
```

---

## 11. Drafting Order

推荐实际写作顺序：

```text
1. Problem Definition
2. Benchmark Design
3. Generator Protocol
4. Query Workloads and Metrics
5. Baselines
6. Experiments
7. Introduction
8. Related Work
9. Abstract
10. Conclusion
```

原因：

```text
先写定义和 benchmark，能固定术语；
最后写 introduction，能避免前面 claim 还没定就过度包装。
```

---

## 12. Pre-Submission Checklist

```text
[ ] EviStateBench and EviStateDB are clearly separated.
[ ] Oracle source is simulator truth + task specification, not EviStateDB.
[ ] Public / hidden artifact boundary is explicit.
[ ] Query workloads are defined formally enough to implement.
[ ] Perturbation parameters are reported.
[ ] Baselines only read public input.
[ ] Every result table has an interpretation paragraph.
[ ] Action gap and observation gap are acknowledged.
[ ] Supplemental subsets are not used to overclaim full real-world validity.
[ ] Related work distinctions are benchmark-level, not dismissive.
[ ] Claims are supported by metrics, not just examples.
```
