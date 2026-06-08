# EviStateBench

EviStateBench 是一个面向数据管理的 benchmark，用来评测系统如何从带噪声、延迟、乱序、缺失和冲突的具身观察流中，维护可审计的时态任务状态视图。

EviStateDB 是该 benchmark 的 reference baseline engine，不是 oracle。标准答案由 simulator truth 和 task specification 生成，不由 EviStateDB 生成。

## 当前定位

论文形态：

```text
ICDE Experiment, Analysis, and Benchmark
```

核心问题：

```text
Temporal Task-State View Maintenance over Embodied Observation Streams
```

固定口径：

```text
EviStateBench evaluates temporal task-state view maintenance.
EviStateDB is a reference baseline engine for this benchmark, not the oracle.
```

这个项目不是要再做一个通用 embodied memory system，也不是把机器人记忆包装成数据库。它关注的是一个更窄、更数据管理的问题：当 observation stream 存在感知不确定性、事件时间和到达时间错位、证据冲突、缺失、乱序和延迟时，系统如何维护可查询、可修正、可追溯的任务状态视图。

## 核心对象

EviStateBench 的 public benchmark artifacts 主要包括：

```text
StateObservation
```

表示原始观察证据。它记录某个来源在某个事件时间，以某个置信度声称某个任务状态成立、不成立，或者对已有状态形成修正。

```text
Query / QueryAnswer
```

表示 benchmark 的考题和被测系统需要输出的统一答案格式。

TemporalStateView 不属于 public benchmark output。它是 EviStateDB reference baseline engine 的内部维护结构，用来实现 valid time、transaction time、confidence、support / contradict evidence 和 revision history。

在此基础上，benchmark 还会评测任务派生视图，例如：

```text
GoalView
PreconditionView
StateDiffView
FailureView
UncertainStateView
```

## 查询负载

EviStateBench 计划覆盖这些 query workloads：

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

这些查询都需要服务机器人任务执行中的具体问题，例如当前目标是否满足、下一步动作前提是否成立、两个时间点之间状态发生了什么变化、系统为什么相信某个状态判断、任务失败可能对应哪个状态偏差。

## 数据来源

主实验计划使用 BEHAVIOR / OmniGibson-derived benchmark。

它负责生成：

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

BEHAVIOR / OmniGibson 的作用是提供任务、predicate、object state 和 simulator truth。EviStateBench 评测的是：系统接收扰动 observation streams 和 query sets 后，输出的 predicted QueryAnswers 是否接近 ground-truth answers。

## Benchmark 边界

当前 v0 把 benchmark artifact 明确分成三层。

给被测系统看的 public input：

```text
data/public_v0/task_specs.jsonl
data/public_v0/observation_streams/*.jsonl
data/public_v0/queries.jsonl
```

被测系统需要输出：

```text
predicted QueryAnswers JSONL
```

只给 oracle / evaluator 使用的 hidden artifacts：

```text
data/synthetic_ground_truth_timelines_v0.jsonl
data/task_predicate_instances_v0.jsonl
data/answer_sets_v0/*.jsonl
data/evaluation_v0/*
```

`data/public_v0/` 是当前真正面向 benchmark 使用者的输入包。它由 `tools/7_build_public_artifacts.py` 从现有中间产物清理生成：`CHECK_GOAL` query 不再内嵌 goal predicates，而是通过 `task_spec_id` 引用 `task_specs.jsonl`；public observation stream 也不再包含 `truth_value`、`source_section`、`source_event_type`、`synthetic_reason` 等 generator/oracle 字段。

## 评测维度

主要评测方向包括：

```text
state tracking correctness
state interval correctness
goal satisfaction accuracy
precondition checking accuracy
state diff precision / recall
WHY_STATE evidence correctness
late-arrival repair accuracy
uncertain-state calibration
query latency
update throughput
memory footprint
view maintenance overhead
```

benchmark 需要特别分析不同方法在 noisy、delayed、out-of-order、missing、conflicting 和 mixed regimes 下的失败模式。

## Baselines

计划对比的方法包括：

```text
Latest Observation
Temporal Log + Voting
Static Symbolic State
SQL / DuckDB Scan
Recall Memory Baseline
Generic IVM Baseline
EviStateDB
```

其中 Recall Memory Baseline 用来模拟 eMEM / STaR 这类基于 retrieval 的 embodied memory 方法；EviStateDB 作为 reference baseline engine，不主张是最强系统，也不生成标准答案，而是作为一个会被 evaluator 打分的官方参考 baseline。

## 当前仓库状态

当前阶段先保留论文主线文档，不保留旧 LifelongSceneDB 原型代码。

```text
EviStateBench_IDEA.md  当前定稿的论文想法和 benchmark 设计主线
README.md             项目入口说明
pyproject.toml        当前 evistatebench Python 包的最小安装配置
evistatebench/        EviStateBench v0 的轻量 Python 数据结构
tools/                面向 benchmark 设计的轻量审计/分析工具
reports/              当前阶段生成的 task-space 审计报告
```

当前已有的 Phase 1 产物：

```text
evistatebench/schema.py          StateObservation schema v0 和 predicate taxonomy 常量
evistatebench/queries.py         CHECK / AS_OF / DIFF / WHY / GOAL 的 query / answer schema v0
evistatebench/engine/views.py    EviStateDB 内部 TemporalStateView schema v0，不是 public output
evistatebench/evistatebench_idea_experiment_brief.md  实验执行版 IDEA 简述
tools/audit_bddl_tasks.py        解析 BEHAVIOR/BDDL task 并统计 predicate 分布
tools/0_extract_task_predicate_instances.py
                                 从 BDDL init/goal 抽取 predicate instances
tools/1_build_synthetic_timelines.py
                                 基于 predicate instances 构造 synthetic ground-truth timeline
tools/2_build_clean_observations.py
                                 从 hidden timeline 生成 clean StateObservation stream
tools/3_build_perturbed_observations.py
                                 从 clean stream 生成 delay/missing/conflict 等扰动 observation streams
tools/4_build_query_sets.py
                                 基于 hidden timeline 和 goal specs 生成 public query set
tools/5_build_ground_truth_answers.py
                                 基于 hidden timeline / observation streams 生成 ground-truth answer sets
tools/6_evaluate_answers.py      对 predicted answers 和 ground-truth answers 做统一评估
tools/7_build_public_artifacts.py
                                 生成给被测系统使用的 sanitized public artifact package
tools/8_validate_public_artifacts.py
                                 检查 public artifacts 中是否残留 oracle/generator 字段
reports/bddl_task_audit.md       面向复盘的 BDDL task audit 报告
reports/bddl_task_audit.json     后续挑选任务族和 query template 时可复用的结构化统计结果
reports/task_space_v0.md         predicate taxonomy v0 和 representative task families v0
reports/query_templates_v0.md    CHECK / AS_OF / DIFF / WHY / GOAL 查询模板 v0
reports/task_predicate_instances_v0.md
                                 predicate instance 抽取结果的统计报告
reports/synthetic_timelines_v0.md
                                 synthetic ground-truth timeline 生成结果的统计报告
reports/clean_observations_v0.md
                                 clean StateObservation stream 生成结果的统计报告
reports/perturbed_observations_v0.md
                                 扰动 StateObservation streams 生成结果的统计报告
reports/query_sets_v0.md         CHECK_STATE / AS_OF_STATE / STATE_DIFF / CHECK_GOAL query set 报告
reports/ground_truth_answers_v0.md
                                 ground-truth answer sets 生成结果的统计报告
reports/evaluator_self_check_v0.md
                                 evaluator 使用 ground-truth answer 自检生成的评估报告
reports/public_artifacts_v0.md   public artifact package 生成报告
reports/public_artifact_validation_v0.md
                                 public artifact 边界校验报告
```

本地生成的数据分为 public input 和 hidden/evaluation-only 两类。

public input 位于：

```text
data/public_v0/task_specs.jsonl
data/public_v0/queries.jsonl
data/public_v0/observation_streams/
data/public_v0/manifest.json
```

hidden / intermediate / evaluation-only 数据位于：

```text
data/task_predicate_instances_v0.jsonl
data/synthetic_ground_truth_timelines_v0.jsonl
data/clean_state_observations_v0.jsonl
data/observation_streams_v0/
data/query_sets_v0/
data/answer_sets_v0/
data/evaluation_v0/
```

`data/` 默认被 `.gitignore` 忽略，适合放本地生成的 benchmark 数据和中间产物。

后续实现应围绕 `EviStateBench_IDEA.md` 逐步补充：

```text
BEHAVIOR / OmniGibson-derived generator
perturbation injector
query generator
ground-truth answer generator
baselines
EviStateDB reference baseline engine
experiment scripts
```

## 详细想法

完整论文构思见：

```text
EviStateBench_IDEA.md
```
