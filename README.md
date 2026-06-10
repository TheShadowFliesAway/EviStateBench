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

表示原始观察证据。它记录某个来源在某个事件时间，以某个置信度声称某个任务状态成立、不成立，或者给出 pose、velocity、temperature 这类测量证据。`observation_kind` 用来区分任务谓词状态和原始测量证据。

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

benchmark artifact 明确分成三层。

给被测系统看的 public input：

```text
public_v0/task_specs.jsonl
public_v0/observation_streams/*.jsonl 或 *.jsonl.gz
public_v0/queries.jsonl
```

被测系统需要输出：

```text
predicted QueryAnswers JSONL
```

只给 oracle / evaluator 使用的 hidden artifacts：

```text
intermediate/*hidden*
answer_sets_v0/*.jsonl
evaluation / baseline sanity reports
```

当前真实 benchmark 的 public package 位于
`real_data_pipeline/artifacts/public_v3_scale48_seed6_main/public_v0/`
和 `real_data_pipeline/artifacts/public_v4_local_seed3_main/public_v0/`。
旧 synthetic v0 的 `data/public_v0/` 可以由 `tools/artifacts/build_public_artifacts.py`
重新生成，但不再作为项目根目录的常驻文件保存。

public observation stream 不应包含 `truth_value`、`source_section`、
`source_event_type`、`synthetic_reason` 等 generator/oracle 字段。

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
Temporal Log + Voting
Static Symbolic State
SQL / DuckDB Scan
Recall Memory Baseline
Generic IVM Baseline
EviStateDB
```

其中 Recall Memory Baseline 用来模拟 eMEM / STaR 这类基于 retrieval 的 embodied memory 方法；EviStateDB 作为 reference baseline engine，不主张是最强系统，也不生成标准答案，而是作为一个会被 evaluator 打分的官方参考 baseline。

`Latest Observation` / `Arrival-latest` 这类方法只保留为内部 sanity lower bound：
它可以用来检查扰动流是否真的制造了 temporal-state maintenance 难度，
但不作为论文主实验的正式 baseline，也不承担 benchmark 贡献的证明。

## 当前仓库状态

当前阶段保留论文主线、benchmark schema、synthetic v0 工具和真实仿真 pipeline，
不再把旧的本地生成数据当作仓库内容维护。

```text
EviStateBench_IDEA.md  当前定稿的论文想法和 benchmark 设计主线
README.md             项目入口说明
pyproject.toml        当前 evistatebench Python 包的最小安装配置
evistatebench/        EviStateBench v0 的轻量 Python 数据结构
tools/                通用 artifact/evaluator 工具和旧 synthetic pipeline 归档
real_data_pipeline/   BEHAVIOR / OmniGibson 真实 benchmark generator
```

`evistatebench/engine/` 是 EviStateDB reference baseline engine，属于 baseline contribution；
`real_data_pipeline/` 才是当前 benchmark 数据生成工作的主线。

`tools/artifacts/` 是真实 benchmark 仍会调用的共享 artifact/evaluator 工具；
`tools/synthetic_legacy/` 是旧 synthetic v0 顺序脚本和 BDDL audit。它们生成的
`data/` 与 `reports/` 是本地过程产物，已被 `.gitignore` 忽略，需要时可以重新生成，
不再默认保存在项目根目录。

当前真实 benchmark 的最新状态、保留 artifact、清理策略和复现实验命令见：

```text
real_data_pipeline/README.md
real_data_pipeline/REAL_BENCHMARK_PROTOCOL.md
real_data_pipeline/PROJECT_CLEANUP.md
```

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
