# EviStateBench Real Benchmark Protocol

本文档定义 EviStateBench 真实 benchmark 的理想工程协议。它不是当前实现状态报告，
而是后续 `real_data_pipeline/` 向理想论文版本推进时必须遵守的语义边界、数据边界和质量标准。

核心问题：

```text
Temporal Task-State View Maintenance over Embodied Observation Streams
```

benchmark 评测的是：系统如何从不完美的 embodied observation streams 维护可查询、
可修正、可追溯的 temporal task-state views。被测系统可以内部使用 retrieval、SQL、
neural memory、rule engine、stream processing 或 incremental view maintenance；
benchmark 只评测统一的 `QueryAnswer` 输出。

---

## 1. Scope Principles

EviStateBench 的理想主线是：

```text
BEHAVIOR / OmniGibson-derived simulator-grounded benchmark
```

它生成：

```text
ground-truth state timelines
clean structured StateObservation streams
perturbed public observation streams
query workloads
hidden ground-truth answers
evaluation reports
```

可以表述为：

```text
simulator-grounded
BEHAVIOR-derived
structured embodied observation streams
temporal task-state view maintenance
data-management benchmark
```

不能表述为：

```text
end-to-end robot perception benchmark
low-level robot control benchmark
complete BEHAVIOR task-completion benchmark
embodied memory retrieval benchmark
VLM benchmark
real-world robot deployment benchmark
```

理想论文版本需要同时包含主 benchmark 和补充 subset：

```text
main controlled simulator-grounded benchmark
  负责可控 correctness evaluation。

supplemental low-level rollout subset
  用于分析 action gap。

supplemental perception-derived subset
  用于分析 observation gap。
```

---

## 2. Source Tiers

### 2.1 Main Controlled Simulator-Grounded Source

主 benchmark 使用 BEHAVIOR / OmniGibson task instance、明确 action source 和 simulator truth。

允许的 action source：

```text
semantic primitive script
demo replay
policy rollout
controlled simulator-state primitive
```

要求：

```text
1. 每个 episode 必须记录 action_source_type。
2. 每个 action source 必须可复现。
3. 每个状态变化必须能回指 simulator truth evidence。
4. controlled simulator-state primitives 必须明确标注，不能伪装成 low-level policy。
```

主 benchmark 的 clean observation 是从 simulator truth 派生的结构化证据，不是 hidden truth table。
hidden truth 用于 oracle，clean observation 用于构造 public stream。

### 2.2 Supplemental Low-Level Rollout Source

补充 low-level subset 用于回答：

```text
当 action source 更接近真实低层控制时，benchmark 数据分布和 failure modes 如何变化？
```

可包含：

```text
starter rollout
policy rollout
low-level controller trace
navigation / grasp / place failure trace
```

它不替代主 benchmark。它用于 gap analysis、failure analysis 和 external validity discussion。

### 2.3 Supplemental Perception-Derived Source

补充 perception subset 用于回答：

```text
当 observations 不是 simulator-truth-derived structured states，而来自 RGB / depth /
detector / VLM 时，state-view maintenance 难度如何变化？
```

可包含：

```text
RGB frame evidence_ref
depth-derived relation evidence
detector / tracker outputs
VLM-derived predicate claims
human annotation samples
```

要求：

```text
1. public observation 仍统一成 StateObservation。
2. evidence_ref 必须能指向 frame / detector result / annotation。
3. 不要求该 subset 支撑主 correctness claim。
4. 主要用于 schema portability 和 observation gap analysis。
```

---

## 3. Pipeline Stages

理想 pipeline 使用职责命名；顺序由文档定义，不靠文件名前缀定义。

```text
0  source_audit.py
1  runtime_probe.py
2  static_observation_audit.py
3  live_recorder.py
4  run_pilots.py
5  build_artifacts.py
6  profile_report.py
7  quality_audit.py
8  select_task_diversity.py
```

### 3.1 Source Audit

目标：

```text
确认 BEHAVIOR / BDDL / OmniGibson 数据源、task definitions、task-instance templates、
assets、object-state modules、tro_state snapshots 和 challenge metadata 是否存在。
```

输出：

```text
source inventory
task availability report
object-state coverage report
dataset subset limitation report
```

### 3.2 Runtime Probe

目标：

```text
确认 Python / CUDA / Vulkan / BDDL / OmniGibson runtime 可以 import、parse task、
load template 和启动最小 simulation。
```

runtime probe 只证明环境可用，不生成 benchmark 数据。

### 3.3 Static Observation Audit

目标：

```text
审计 task template / tro_state / object-state schema 能映射到哪些 StateObservation 字段。
```

这一步服务 schema alignment，但不能作为最终 temporal rollout truth 来源。

### 3.4 Live Recorder

目标：

```text
启动 OmniGibson，加载 task instance，运行明确 action source，记录 simulator truth，
并生成 episode-level benchmark core artifacts。
```

至少输出：

```text
episode_manifest.json
simulator_truth_snapshots.jsonl
hidden_state_timeline.jsonl
clean_state_observations.jsonl
task_spec.json
action_trace.jsonl
generation_report.json
generation_report.md
```

### 3.5 Batch Runner

目标：

```text
按 manifest 批量运行 tasks x instances x seeds，做 transition validation，
并生成统一 generation summary。
```

每条 manifest 必须包含：

```text
task id
activity name
scene model
definition / instance id
robot type
action source
object scope
expected semantic targets
runtime limits
known caveats
```

### 3.6 Public Artifact Builder

目标：

```text
把 stage3 episode artifacts 转成 public package、hidden answer sets 和 reports。
```

它负责：

```text
normalize task specs
merge hidden state timelines
merge clean observations
inject perturbations
generate query sets
generate hidden answer sets
sanitize public artifacts
validate leakage boundary
```

### 3.7 Profile / Quality Reports

每个 formal batch 必须生成：

```text
benchmark profile report
public artifact validation report
quality audit report
build commands manifest
```

---

## 4. Artifact Boundary

真实 benchmark artifact 分为 public input、system output、hidden evaluator-only 三层。

### 4.1 Public Input

可以提供给被测系统：

```text
public_v0/task_specs.jsonl
public_v0/queries.jsonl
public_v0/observation_streams/*.jsonl 或 *.jsonl.gz
public_v0/manifest.json
```

public input 只能包含：

```text
task specification
observation stream
query workload
non-oracle metadata
```

### 4.2 System Output

被测系统输出：

```text
predicted QueryAnswers JSONL
```

系统不需要暴露 TemporalStateView、indexes、retrieval memory 或 internal logs。

### 4.3 Hidden / Evaluator-Only

不能作为 public input 暴露：

```text
simulator_truth_snapshots.jsonl
hidden_state_timeline.jsonl
real_hidden_state_timeline_v0.jsonl
answer_sets_v0/*.jsonl
perturbation debug maps
generation_report.json
quality audit internals
```

这些文件只用于 oracle、evaluator、debug 和论文统计。

### 4.4 Leakage Rules

public artifacts 禁止包含：

```text
truth_value
oracle_answer
hidden_state_id
source_event_id
source_clean_obs_id
perturbation_label
original_observed_value
flipped_observed_value
generator-only reason
local absolute path
```

所有 formal public packages 必须通过 validator。

---

## 5. StateObservation Semantics

`StateObservation` 是原始证据，不是最终状态。

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

关键语义：

```text
event_time
  证据对应的世界时间 / valid time。

arrival_time
  系统收到证据的时间 / transaction time。

observation_kind
  predicate_state / object_pose / object_velocity / joint_state / numeric_state。

observed_value
  true / false / categorical / numeric / JSON-like measurement。

confidence
  observation-level confidence，不是最终 state confidence。

polarity
  support / contradict / correction。
```

`observed_value=False` 不等于 `polarity=contradict`：

```text
observed_value=False
  证据支持“该状态为假”。

polarity=contradict
  证据被标注为对已有判断的反驳或修正。
```

public stream 中的 conflict 不应靠直接标签泄漏。系统应从同一 state key 上的相反 claims、
不同 confidence、不同 arrival time 和 evidence provenance 中识别冲突。

---

## 6. Hidden Timeline Semantics

hidden timeline 是 oracle material。它从 simulator truth 中抽取，不由 EviStateDB 生成。

每条 hidden event 至少包含：

```text
episode_id
state_key
predicate_name
arguments
event_time
event_type
observed_value
previous_observed_value
valid_from
valid_to
simulator_evidence_ref
```

event_type：

```text
initial_state
state_change
numeric_update
relation_update
goal_condition_update
```

hidden timeline 必须支持：

```text
state value at time
valid interval construction
state diff between times
goal satisfaction at time
numeric state comparison
evidence lookup
```

---

## 7. Clean Observation Extraction

clean observation 是从 hidden truth 派生出的 public-input candidate。

它应保留：

```text
event_time
arrival_time
source
observation_kind
predicate_name
arguments
observed_value
confidence
evidence_ref
```

它不应保留：

```text
truth_value
oracle interval
query answer
hidden transition label
```

clean stream 可以高置信，但不等于 oracle。所有被测系统只能通过 observation stream
重建状态视图。

---

## 8. Perturbation Model

扰动用于模拟 embodied observation streams 中的数据质量问题，不是任意随机污染。

标准 regimes：

```text
R0 clean
R1 noisy / low_confidence
R2 delayed
R3 out_of_order
R4 conflicting
R5 missing
R6 mixed
```

每类扰动对应的系统压力：

```text
low_confidence
  uncertainty calibration。

delayed
  transaction-time semantics。

out_of_order
  late repair and historical correction。

conflicting
  support / contradict evidence arbitration。

missing
  incomplete evidence and uncertain states。

mixed
  realistic combined pressure.
```

正式 benchmark 不穷尽扰动排列组合。协议采用：

```text
diagnostic single-factor regimes
  用于定位失败原因。

main mixed regimes
  用于主榜单和真实压力测试。
```

主论文只需要报告代表性 regimes：

```text
clean
missing
temporal disorder = delay + out_of_order
conflict
mixed
```

low_confidence、不同 severity sweep、所有扰动排列组合可以放 artifact release / technical report。

建议 severity：

```text
mild
medium
heavy
```

每个 severity 必须由配置文件固定：

```text
delay distribution
missing_rate
low_confidence_rate
confidence range
conflict_rate
out_of_order delay range
noise model
random seed
```

---

## 9. Query Workload Semantics

所有 query 评测 temporal task-state view maintenance，不是 retrieval。

core query workloads：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL
```

supplemental query workloads：

```text
WHY_STATE
CHECK_PRECONDITION
FIND_UNCERTAIN_STATES
FAILURE_LOCALIZATION
```

主论文 correctness claim 以 core query workloads 为主。supplemental workloads 用于展示
provenance、precondition、uncertainty 和 failure analysis 能力，不承担主表完整性要求。

### 9.1 CHECK_STATE

```text
CHECK_STATE(predicate, arguments, valid_time)
```

回答：

```text
在 valid_time，该状态在系统维护的 task-state view 中是什么？
```

### 9.2 AS_OF_STATE

```text
AS_OF_STATE(predicate, arguments, valid_time, transaction_time)
```

回答：

```text
当系统只看到 transaction_time 前到达的 evidence 时，
它对 valid_time 的状态判断是什么？
```

这是 bitemporal benchmark 的核心 query。

### 9.3 STATE_DIFF

```text
STATE_DIFF(scope, t1, t2)
```

回答：

```text
t1 到 t2 之间，scope 内有哪些状态变化？
```

scope 可以是：

```text
state_key
object
object_set
predicate_family
task
goal
```

### 9.4 WHY_STATE

```text
WHY_STATE(predicate, arguments, valid_time[, transaction_time])
```

答案必须包含：

```text
current belief
support observations
contradict observations
confidence trace
revision history
evidence_refs
```

### 9.5 CHECK_GOAL

```text
CHECK_GOAL(task_id, valid_time)
```

答案必须包含：

```text
goal_satisfied
satisfied predicates
violated predicates
uncertain predicates
support / contradict evidence summary
```

### 9.6 CHECK_PRECONDITION

```text
CHECK_PRECONDITION(action_id, valid_time)
```

答案必须包含：

```text
precondition_satisfied
satisfied preconditions
violated preconditions
uncertain preconditions
blocking evidence
```

### 9.7 FIND_UNCERTAIN_STATES

```text
FIND_UNCERTAIN_STATES(task_id, valid_time, threshold)
```

返回：

```text
low-confidence states
conflicting states
insufficient-evidence states
states with late repairs
```

### 9.8 FAILURE_LOCALIZATION

```text
FAILURE_LOCALIZATION(episode_id)
```

返回：

```text
likely failed predicate
failed precondition
missing / contradictory evidence
time of divergence
evidence trail
```

---

## 10. Oracle And Answer Generation

ground-truth answers 由以下内容生成：

```text
simulator truth
hidden state timeline
task specification
query specification
perturbation log when transaction-time semantics matter
```

ground-truth answers 不由 EviStateDB 或任何 baseline 生成。

oracle 必须支持：

```text
value at valid_time
value as of transaction_time
state diff over intervals
goal satisfaction
```

supplemental oracle support：

```text
precondition satisfaction
uncertain-state labels
support / contradict evidence matching
failure localization labels
numeric tolerance
```

numeric answers 必须定义 tolerance：

```text
absolute tolerance
relative tolerance
directional expectation
threshold crossing
```

---

## 11. Task And Predicate Coverage

正式 benchmark 应覆盖：

```text
object unary state
  open, toggled_on, hot, cooked, frozen, folded, sliced

containment / spatial relation
  inside, ontop, nextto, under, touching

material / particle state
  covered, filled, saturated, contains

contact / configuration
  attached, draped, folded / unfolded

numeric state
  temperature, max_temperature, pose, distance

robot-related state
  grasped, holding, objects_in_fov, reachable
```

候选任务必须按以下维度记录：

```text
activity name
scene model
object scope
predicate families
expected state transitions
horizon category
action source type
template availability
known failure modes
```

---

## 12. Splits And Scale

### 12.1 Horizon Split

按 temporal state-view maintenance 难度，而不是低层轨迹长度：

```text
short
  1-2 个核心状态变化，少量对象，短时间窗口。

medium
  3-8 个核心状态变化，多对象或多阶段。

long
  多子目标、多对象、多状态族、长等待、late repair 或 failure recovery。
```

### 12.2 Predicate-Family Split

每个 release 必须报告：

```text
predicate family counts
state transition counts
query counts by workload
observation counts by stream
task counts by activity
episode counts by horizon
```

### 12.3 Recommended Scale

工程 smoke：

```text
4-8 tasks x 1-2 seeds
```

paper minimum：

```text
24-30 activities/templates
>= 2 validated activity_instance_id values where available
3 seeds/repetitions
144-180 episodes
```

strong benchmark release：

```text
40-50 activities/templates
2-3 validated activity_instance_id values where available
3 seeds/repetitions
240-450 episodes
```

supplemental subsets can be smaller but must be clearly labeled.

---

## 13. Baseline And Evaluation Protocol

主论文 baseline set：

```text
Temporal Log / SQL Scan
Recall Memory Baseline
EviStateDB
```

artifact-release / supplemental baselines：

```text
Latest Observation / Arrival-latest sanity lower bound
Static Symbolic State
Generic IVM Baseline
additional neural / LLM memory variants
```

### 13.1 Fair Comparison Requirements

所有 baseline 必须在同一个 fair-comparison protocol 下运行：

```text
same public artifact
same task specs
same observation streams
same query set
same prediction schema
same evaluator
same hidden answer sets for scoring
same hardware / software reporting template
fixed random seeds when a baseline is stochastic
fixed perturbation parameters and split definitions
```

每个 baseline 必须只读取 public input。

禁止：

```text
读取 hidden timeline
读取 answer sets
读取 perturbation labels
使用 generator-only metadata
按 episode id 写规则作弊
```

指标：

```text
state truth accuracy
state diff precision / recall
goal satisfaction accuracy
AS_OF_STATE correctness
uncertain-state calibration
late-arrival repair accuracy
p50 / p95 query latency
update throughput
memory footprint
```

supplemental metrics：

```text
state interval F1
precondition checking accuracy
WHY evidence precision / recall
failure localization accuracy
index size
repair cost
```

---

## 14. Paper Experiment Mapping

本协议支撑论文中的收敛版实验矩阵：

```text
Artifact Characterization
  由 profile report、quality audit、public artifact validation 支撑。

E1 Main Benchmark Results
  使用 core query workloads、main regimes 和主论文 baseline set。

E2 Query Semantics Breakdown
  使用 CHECK_STATE / AS_OF_STATE / STATE_DIFF / CHECK_GOAL 的分 query-type 结果。

E3 Robustness Under Representative Perturbations
  使用 clean / missing / temporal disorder / conflict / mixed 的分 regime 结果。

E4 Efficiency And Ablation
  使用 EviStateDB runtime / memory / update throughput 和 ablation variants。

Supplemental External Validation
  使用 low-level rollout subset、perception-derived subset 和 schema portability checks。
```

---

## 15. Quality Gates

一个 benchmark batch 只有满足以下条件，才能进入 formal public artifact：

```text
1. episode status = PASS。
2. expected semantic transitions / goals are validated.
3. hidden timeline contains initial and change/final evidence for query targets.
4. clean observation stream is schema-valid.
5. perturbation streams are schema-valid.
6. public package passes leakage validation.
7. answer sets cover all query ids.
8. profile report covers task / predicate / horizon / query / stream statistics.
9. known limitations are documented.
```

失败任务可以进入 candidate report，但不能进入 formal benchmark release。

---

## 16. Reporting Requirements

每个 formal release 至少保存：

```text
public_v0/manifest.json
public_v0/task_specs.jsonl
public_v0/queries.jsonl
public_v0/observation_streams/*
reports/public_artifact_validation_v0.md
reports/benchmark_profile_report_v1.md
reports/quality_audit_v0.md
build_commands.json
```

论文中必须报告：

```text
episode count
task count
predicate family distribution
horizon split
query workload distribution
stream sizes
perturbation parameters
validation status
limitations
```

---

## 17. Ideal Conformance Levels

### Core

```text
simulator-grounded episodes
structured StateObservation streams
clean + mixed perturbation
CHECK_STATE / AS_OF_STATE / STATE_DIFF / CHECK_GOAL
hidden answer sets
basic baselines
```

### Full

```text
core query workloads plus supplemental workloads
multi-severity perturbation profiles
all predicate families
short / medium / long horizon splits
full baseline suite
quality / profile / leakage validation
```

### Supplemental

```text
low-level rollout subset
perception-derived subset
external real-data ingestion examples
gap analysis
```

工程推进时应明确每个 artifact 属于 Core、Full 还是 Supplemental，不混用 claims。
