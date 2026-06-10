# EviStateBench ICDE Benchmark Enrichment Plan

本文档给出 EviStateBench 从当前真实 benchmark artifact 推进到强版本 ICDE EAB benchmark 所需的工程计划。

目标不是“看起来数据很多”，而是让 benchmark 达到以下状态：

```text
1. 有清楚的数据管理问题边界；
2. 有可复现的真实 simulator-grounded artifact；
3. 有代表性的 workload / query / perturbation / scale 设计；
4. 有能揭示现有方法强弱的 baseline 评测；
5. 有质量审计、artifact validation 和 failure analysis；
6. 论文中的每个 claim 都能由 artifact 或实验支撑。
```

本文档只保留强版本路线，不维护临时降级目标。当前已有结果只作为 gap 起点；后续工程、实验和写作都按本文档的 full benchmark target 推进。

---

## 1. External Standards From Deep Research

### 1.1 ICDE EAB 硬要求

ICDE 2026 research CFP 对 EAB paper 的定义是：EAB 论文关注对算法、数据结构、系统的 extensive evaluation，或提出与数据管理主题相关的 benchmark；贡献必须体现为对现有方法强弱的新洞察，或新的评价方式。

对 EviStateBench 的含义：

```text
只发布数据不够。
只跑一个 toy baseline 不够。
必须证明该 benchmark 能揭示 temporal task-state view maintenance 的方法差异、失败模式和数据管理挑战。
```

ICDE 2026 还明确：EAB paper 必须提供复现实验结果所需 artifacts，且 no appendix。这意味着正文必须写清楚最关键的 design、artifact、实验和限制，不能把核心定义放到附录。

来源：

```text
ICDE 2026 Call for Research Papers
https://icde2026.github.io/cf-research-papers.html
```

### 1.2 数据库 benchmark 论文的共同标准

从 LDBC SNB、LDBC FinBench、TSM-Bench 等 benchmark 论文看，扎实的数据库 benchmark 通常包含：

```text
domain motivation
data model / workload model
representative workload design
query taxonomy
scale factors and scale profile
execution / evaluation rules
baseline systems
metrics
artifact availability
audit / reproducibility description
failure and bottleneck analysis
```

LDBC SNB specification 明确包含 data specification、workload specification、execution rules、auditing rules 和 full disclosure report required contents。这说明 benchmark 不是一组数据文件，而是一套可执行、可审计的协议。

LDBC FinBench 采用 choke-point-driven methodology，从真实场景的瓶颈设计 benchmark 特征；这对 EviStateBench 很重要：我们的 “choke points” 应该是 event-time/arrival-time mismatch、uncertainty、conflict、task-derived views、provenance，而不是任意加噪。

TSM-Bench 强调 benchmark 要提供多种 metrics、代表性数据流、可扩展数据生成、以及帮助 debug 性能或系统能力差异的分析。

来源：

```text
LDBC SNB specification
https://ldbcouncil.org/ldbc_snb_docs/ldbc-snb-specification.pdf

LDBC FinBench Transaction Workload
https://www.vldb.org/pvldb/vol18/p3007-qi.pdf

TSM-Bench
https://www.vldb.org/pvldb/vol16/p3363-khelifati.pdf
```

### 1.3 BEHAVIOR / OmniGibson 给我们的合理性边界

BEHAVIOR-1K 提供 1,000 everyday activities、50 scenes、丰富对象和 predicate-logic activity definitions。OmniGibson 支持 extended object states，例如 Temperature、MaxTemperature、ToggledState、SoakedLevel，以及 Cooked / Frozen / Heated 等 logical predicates。

对 EviStateBench 的含义：

```text
使用 BEHAVIOR / OmniGibson 作为 simulator-grounded source 是合理的。
但是论文不能声称 EviStateBench 覆盖了完整 BEHAVIOR-1K。
必须清楚报告我们实际选取了哪些 activities、instances、scenes、state families、action sources。
```

来源：

```text
BEHAVIOR-1K paper
https://arxiv.org/html/2403.09227v1
https://proceedings.mlr.press/v205/li23a.html
```

---

## 2. Current v7 Artifact As Gap Baseline

当前主 artifact：

```text
real_data_pipeline/artifacts/public_v7_scale72_seed6_ideal_full
```

当前已完成：

```text
episodes: 72
task specs: 72
tasks / templates: 12
queries: 900
public streams: 7
clean observations: 853100
validation: PASS
profile: PASS_WITH_LIMITS
```

query 类型：

```text
CHECK_STATE: 324
AS_OF_STATE: 360
STATE_DIFF: 72
CHECK_GOAL: 144
```

state / predicate 覆盖：

```text
open: 6
toggled_on: 24
covered: 6
inside: 30
cooked: 12
temperature: 30
frozen: 18
attached: 6
max_temperature: 6
hot: 6
```

transition 覆盖：

```text
boolean_flip: 84
eventual_boolean: 24
numeric_transition: 36
```

当前与强版本目标的差距：

```text
1. activity_instance_id 基本都是 inst000。
2. queries remain target-scoped, not full task-level BDDL semantics。
3. 没有 perception-derived subset。
4. 没有 low-level rollout subset。
5. 没有正式 baseline predictions。
6. 当前 profile 是 PASS_WITH_LIMITS，不是 final release PASS。
7. 部分 episode observation count 过大，需要解释或控制。
8. p6_freeze_pies_medium 有 horizon seed drift。
```

结论：

```text
当前 v7 是可复用的工程 checkpoint。
它不能作为最终强版本 benchmark，也不能支撑 final release claim。
```

### 2.1 Current-To-Strong-Target Scorecard

| dimension | current v7 | strong-version target | status |
| --- | ---: | ---: | --- |
| activities / templates | 12 | 50 | gap |
| episodes | 72 | 450 | gap |
| activity instances | effectively inst000 | 3 validated instances per activity | gap |
| query types | 4 | 8-workload suite | gap |
| queries | 900 | 8,000 | gap |
| state families | 5-ish | 8 robust state-family groups | gap |
| public streams | 7 | 7 streams x low/medium/high severity profiles | gap |
| perception-derived subset | 0 | 50 demo/perception-derived episodes | gap |
| execution-gap subset | 0 | 20 official demo execution-diagnostic episodes plus rawdata asset lock report | gap |
| formal baselines | 0 in benchmark repo | Temporal Log / SQL Scan, Recall Memory, EviStateDB, Latest/Arrival diagnostic lower bound + EviStateDB ablations | gap |
| artifact validation | PASS | one-command release validation + checksums + leakage audit | gap |
| readiness | PASS_WITH_LIMITS | final release PASS | gap |

This scorecard is the working target for the rest of the project.

---

## 3. Final Benchmark Claim After Enrichment

完成本文档计划后，论文可以主张：

```text
EviStateBench is a simulator-grounded data-management benchmark for temporal task-state view maintenance over embodied observation streams. It provides reproducible task-state episodes, structured observations, controlled perturbation regimes, query workloads, hidden answer sets, and evaluation protocols that reveal how state maintenance systems handle uncertainty, event-time/arrival-time mismatch, conflict, task-derived views, and provenance.
```

仍然不能主张：

```text
EviStateBench solves embodied memory.
EviStateBench solves robot policy learning.
EviStateBench is a complete BEHAVIOR-1K benchmark.
EviStateBench proves real-world robot deployment performance.
EviStateBench evaluates end-to-end perception quality as its main claim.
```

---

## 4. Enrichment Axis A: Task / Instance / Scene Diversity

### A1. 目标

把 benchmark 从 “12 templates x seeds” 推进到真正有 benchmark diversity 的 artifact。

### A2. Strong-version state families

强版本覆盖：

```text
object unary states:
  open / closed
  toggled_on / toggled_off

spatial / containment relations:
  inside
  ontop
  nextto

thermal / numeric states:
  temperature
  cooked
  frozen
  heated / hot
  max_temperature

material / particle states:
  covered
  soaked
  filled

contact / assembly states:
  attached
  grasped / touching

cleanliness / visual substance:
  dusty / stained / dirty / clean
```

当前已有：

```text
open, toggled_on, covered, inside, cooked, temperature, frozen, attached, max_temperature, hot
```

当前缺口：

```text
ontop and nextto
soaked and filled
dirty and clean
closed / toggled_off true-to-false style transitions
more stable medium-horizon tasks
```

### A3. Strong-version scale target

```text
activities: 50
activity instances: 3
seeds / repetitions: 3
episodes: 450
queries: 8,000
public streams: clean + missing + delay + out_of_order + low_confidence + conflict + mixed
severity profiles: low + medium + high
demo/perception-derived subset: 50 episodes
execution-gap diagnostic subset: 20 official demo execution-diagnostic episodes + rawdata asset lock report
```

### A4. 验收标准

产物：

```text
reports/task_diversity_matrix.csv
reports/task_diversity_matrix.md
```

字段包含：

```text
activity_name
task_id
scene_model
activity_instance_id
seed
state_family
predicate_name
transition_kind
horizon_bucket
action_source_type
generation_status
transition_validation_status
clean_observation_count
query_count
audit_note
```

验收标准：

```text
state family groups: 8
core predicates: 20
activities: 50
episodes: 450
activity_instance_id values per activity: 3
short / medium / long horizon buckets all populated
no predicate family dominates target events
all public validation checks pass
```

---

## 5. Enrichment Axis B: Action Source Stratification

### B1. Why

当前主 benchmark 使用 controlled symbolic / semantic primitives 更稳定，但它会被审稿人质疑：

```text
这是真实仿真状态维护 benchmark，还是手工状态脚本？
```

解决方式不是放弃 controlled benchmark，而是分层报告 action source。

### B2. Action-source plan

强版本 action-source 采用一个分层但固定的设计：

```text
controlled_semantic_primitive
official_demo_derived
execution_gap_diagnostic
```

用途：

```text
controlled_semantic_primitive:
  生成主 correctness benchmark，保证状态变化明确、可复现、可审计。

official_demo_derived:
  接入官方 replayed demo 的 low-dim / metadata / video-derived observations，
  用于 action / observation gap analysis。

execution_gap_diagnostic:
  使用 official demo execution traces 形成 execution-gap diagnostic subset，
  并用 rawdata asset lock report 记录 exact replay 的版本对齐状态。
```

### B3. Strong-version action-source target

```text
controlled semantic primitive episodes: 450
official demo-derived episodes: 50
execution-gap diagnostic episodes: 20
asset / data lock report: one frozen record for every action-source family
```

### B4. Artifact 字段

每个 episode manifest 必须包含：

```text
action_source_type
action_source_file
action_source_version
uses_symbolic_state_primitive
uses_low_level_controller
replay_or_policy_name
controller_failure_status
asset_snapshot_id
data_source_revision
```

---

## 6. Enrichment Axis C: Query Workload Semantics

### C1. 当前状态

当前有：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL
```

当前问题：

```text
CHECK_GOAL 和 STATE_DIFF 仍是 target-scoped。
缺少 provenance / explanation 类 query。
缺少 uncertainty-oriented query。
没有 task-level BDDL full goal semantics。
```

### C2. Strong-version query suite

强版本 query workload 一次性实现完整套件：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
CHECK_GOAL
WHY_STATE
FIND_UNCERTAIN_STATES
CHECK_PRECONDITION
FAILURE_LOCALIZATION
```

WHY_STATE、FIND_UNCERTAIN_STATES、CHECK_PRECONDITION 和 FAILURE_LOCALIZATION
把 benchmark 从普通 state classification 拉回 data management：

```text
support evidence
contradict evidence
confidence
arrival-time repair
revision / provenance
```

### C3. Query scope 分层

保留 target-scoped queries，但必须新增 scope label：

```text
target_state
target_state_set
target_goal
bddl_goal_subset
full_bddl_goal
uncertain_state_set
provenance_state
```

query_scope 采用以下固定集合：

```text
target-scoped: main correctness
bddl_goal_subset: validated task-goal subset
full_bddl_goal: validated full-goal subset
```

每个 CHECK_GOAL query 必须声明自己属于 `target_goal`、`bddl_goal_subset`
还是 `full_bddl_goal`，不能混用。

### C4. 验收标准

产物：

```text
query_semantics_report.md
query_semantics_matrix.csv
answer_schema_validation_report.md
```

验收标准：

```text
each query type has formal answer schema
evaluator supports all eight query types
every query has query_scope and semantic intent
WHY_STATE evidence ids only refer to public observations
CHECK_GOAL semantics are explicit per query
baseline predicted answers never require hidden timeline access
```

---

## 7. Enrichment Axis D: Perturbation Model

### D1. Principle

扰动不能是“为了难而加噪”。它必须对应 embodied observation streams 的真实数据管理问题：

```text
missing observations
delayed arrival
out-of-order arrival
low confidence / uncertain evidence
conflicting evidence
mixed real-world-like stream
```

### D2. 主设计

单一 regime 用于 attribution：

```text
clean
missing
delay
out_of_order
low_confidence
conflict
```

mixed regime 用于主 robustness：

```text
mixed = missing + delay + out_of_order + low_confidence + conflict
```

不要穷举所有排列组合。数据库 benchmark 通常更重视 representative workload 和瓶颈覆盖，而不是组合爆炸。

### D3. Severity levels

需要把之前临时 severity sweep 变成正式、可解释的设计：

```text
severity_low
severity_medium
severity_high
```

每个 severity 定义：

```text
missing_rate
delay_distribution
out_of_order_window
low_confidence_rate
conflict_injection_rate
affected_predicate_families
random_seed
```

论文展示固定为：

```text
mixed severity curve
single-regime attribution table
```

### D4. 验收标准

产物：

```text
perturbation_protocol.md
perturbation_profile.json
perturbation_audit_report.md
```

验收标准：

```text
every perturbed stream has reproducible profile and seed
mixed stream includes missing / delay / out_of_order / low_confidence / conflict
perturbation does not leak hidden truth
severity levels show monotonic difficulty trend with written explanation
timestamps and evidence ids pass validation
```

---

## 8. Enrichment Axis E: Observation Gap Subset

### E1. Why

用户担心的 gap 是真实的：

```text
主 benchmark 的 clean observations 来自 simulator truth-derived structured observations。
真实机器人场景中 observations 可能来自 RGB / depth / detector / VLM。
```

这个 gap 不能靠话术消掉。必须用 subset 正面承认并测量。

### E2. Strong-version subset

建立 demo/perception-derived subset：

```text
episodes: 50
state families: inside / open / toggled_on / temperature / cooked
observation sources:
  official 2025-challenge-demos v2.1 parquet / metadata
  RGB frame evidence_ref
  depth-derived spatial relation
  detector / tracker output
  VLM predicate claim
```

输出仍统一为：

```text
StateObservation
```

### E3. 论文中如何用

它不支撑主 correctness claim。它支撑：

```text
schema portability
observation gap analysis
failure examples
future work boundary
```

### E4. 验收标准

```text
every perception-derived observation has evidence_ref
RGB / depth / detector-tracker / VLM sources are represented
the same evaluator runs on mapped StateObservation streams
report compares simulator-truth-derived vs perception-derived answer status
perception subset is clearly labeled as gap analysis, not full real-world validation
```

---

## 9. Enrichment Axis F: Baseline And Discriminativeness

### F1. Formal baseline set

Benchmark 论文必须证明 benchmark 能区分方法。

正式 baseline set：

```text
Temporal Log / SQL Scan
Recall Memory Baseline
EviStateDB
Latest Observation / Arrival-latest
```

`Latest Observation / Arrival-latest` 作为诊断下界进入 breakdown，不作为主贡献 claim。

### F2. Metrics

correctness：

```text
exact accuracy
value accuracy
status accuracy
goal satisfied accuracy
state diff F1
WHY_STATE evidence precision / recall
uncertainty calibration
```

robustness：

```text
accuracy by stream
accuracy by severity
accuracy drop from clean to mixed
repair success under delay / out_of_order
conflict detection rate
unknown / uncertain handling quality
```

efficiency：

```text
p50 / p95 query latency
update throughput
memory footprint
index build time if applicable
scaling with #observations and #episodes
```

### F3. Discriminativeness gate

验收标准：

```text
all formal baselines produce predictions for all public streams
methods differ by query type and perturbation regime
EviStateDB ablation reveals which design components matter
benchmark identifies failure modes, not only ranking
results are audited against target-scoped leakage
```

---

## 10. Enrichment Axis G: Quality Audit And Artifact Validation

### G1. Required validation reports

当前已有：

```text
public_artifact_validation_v0.md
quality_audit_v0.md
benchmark_profile_report_v1.md
```

需要升级为 final release reports：

```text
artifact_card.md
data_statement.md
license_and_source_statement.md
public_hidden_boundary_audit.md
query_semantics_audit.md
perturbation_audit_report.md
task_diversity_audit.md
baseline_input_leakage_audit.md
reproducibility_report.md
```

### G2. Artifact package

final public release 必须包含：

```text
public_v0/
answer_sets_v0/
evaluator/
baseline_prediction_format.md
generation_manifest.json
artifact_checksums.sha256
environment.yml
Dockerfile
run_reproduce.sh
reports/
```

BEHAVIOR / OmniGibson 原始 assets 的再分发边界写入 release statement：

```text
which files are redistributed
which files must be downloaded from upstream
which version / commit / install command is required
```

### G3. One-command validation

必须提供：

```bash
python real_data_pipeline/stages/validate_release.py \
  --artifact real_data_pipeline/artifacts/{final_release}
```

检查项：

```text
schema validity
query coverage
stream counts
answer set coverage
public-hidden leakage
evidence id consistency
timestamp sanity
checksum consistency
baseline prediction format
```

---

## 11. Final Experimental Matrix

### E0. Artifact Characterization

目的：

```text
证明 benchmark 本身的覆盖范围、规模和质量。
```

表 / 图：

```text
task/state-family coverage matrix
horizon distribution
query workload distribution
stream size distribution
answer status distribution by regime
```

### E1. Main Baseline Results

目的：

```text
证明 benchmark 能区分不同 state maintenance approaches。
```

比较：

```text
Temporal Log / SQL Scan
Recall Memory
EviStateDB
Latest Observation / Arrival-latest diagnostic lower bound
```

按：

```text
stream
query type
predicate family
horizon
```

### E2. Perturbation Robustness

目的：

```text
证明 event-time/arrival-time mismatch、missing、conflict、uncertainty 是真实 choke points。
```

展示：

```text
single regime attribution
mixed severity curve
repair success under delay/out_of_order
conflict / uncertainty handling
```

### E3. Query Semantics Breakdown

目的：

```text
证明 benchmark 不是普通 retrieval / memory accuracy，而是 state maintenance。
```

展示：

```text
CHECK_STATE vs AS_OF_STATE vs STATE_DIFF vs CHECK_GOAL vs WHY_STATE
target-scoped vs bddl-goal-subset
known / unknown / uncertain / conflict handling
```

### E4. Scale And Efficiency

目的：

```text
证明数据库系统视角成立。
```

展示：

```text
latency vs #observations
update throughput
memory footprint
index / view maintenance overhead
```

### E5. Gap Analysis

目的：

```text
诚实讨论 simulator-truth-derived structured observation 与 perception-derived observation 的 gap。
```

展示：

```text
controlled main benchmark vs perception-derived subset
controlled semantic primitive vs official demo-derived subset
failure case examples
```

---

## 12. Concrete Engineering Roadmap

### Milestone 1: Release-Grade Artifact Foundation

Tasks:

```text
1. Add release validator script.
2. Add artifact card and data statement.
3. Add public-hidden leakage audit.
4. Freeze current v7 as gap-baseline checkpoint.
5. Keep answer_sets_v0 for evaluator and baseline self-eval.
```

Exit criteria:

```text
one-command validation passes
documented known limitations
baseline repo can self-evaluate predictions
```

### Milestone 2: Add task / state diversity

Tasks:

```text
1. Extend candidate manifests to 50 activities.
2. Add 3 validated activity_instance_id values per activity.
3. Add ontop/nextto, soaked/filled, dirty/clean, grasped/touching transitions.
4. Add stable medium-horizon tasks.
5. Generate the full diversity release artifact.
```

Exit criteria:

```text
activities: 50
episodes: 450
state family groups: 8
core predicates: 20
release validation passes
no single predicate family dominates > 35% target events
```

### Milestone 3: Add query semantics

Tasks:

```text
1. Implement WHY_STATE query generation.
2. Implement WHY_STATE answer generation and evaluator metrics.
3. Add query_scope labels.
4. Add bddl_goal_subset and full_bddl_goal query scopes.
5. Add query semantics audit.
```

Exit criteria:

```text
all eight query workloads are generated and evaluated
evidence precision / recall metric works
target-scoped vs bddl-goal-subset clearly separated
```

### Milestone 4: Formalize perturbation model

Tasks:

```text
1. Write perturbation_profile.json.
2. Rebuild streams with low/medium/high severity.
3. Keep mixed as primary robustness stream.
4. Add perturbation audit and timestamp sanity checks.
```

Exit criteria:

```text
severity curve is monotonic with written explanation
mixed contains documented missing/delay/out_of_order/low_confidence/conflict components
timestamps and evidence ids are valid
```

### Milestone 5: Perception and rollout gap subsets

Tasks:

```text
1. Select 50 stable demo/perception-derived episodes.
2. Use official 2025-challenge-demos v2.1 parquet / metadata as the demo-derived source.
3. Export RGB/depth evidence refs.
4. Add detector/depth/VLM-derived StateObservation mapping.
5. Add 20 execution-gap diagnostic episodes and asset lock report.
```

Exit criteria:

```text
perception subset runs through same schema/evaluator
gap analysis has real examples
no claim inflation
```

### Milestone 6: Baseline integration

Tasks:

```text
1. Receive predictions from baseline repo.
2. Run official evaluator.
3. Export paper tables.
4. Add by-regime / by-query / by-family / by-horizon breakdowns.
5. Add EviStateDB ablations.
```

Exit criteria:

```text
all formal baselines evaluated
all main streams evaluated
query-type and perturbation breakdowns non-empty
failure analysis examples selected
```

---

## 13. Final Release Checklist

强版本 final release requirements：

### Scope

```text
data-management contribution is explicit
not framed as robot control / VLM / end-to-end perception benchmark
EviStateDB is reference baseline, not oracle
```

### Data

```text
activities: 50
episodes: 450
state family groups: 8
core predicates: 20
multi-instance support is real, not only seed repetition
short / medium / long splits all populated
```

### Query

```text
query workloads include CHECK_STATE, AS_OF_STATE, STATE_DIFF, CHECK_GOAL,
WHY_STATE, FIND_UNCERTAIN_STATES, CHECK_PRECONDITION, FAILURE_LOCALIZATION
target-scoped and task-level semantics are separated
evaluator supports every reported query type
```

### Perturbation

```text
perturbation profiles are documented and reproducible
mixed stream is formally defined
severity curve and attribution table exist
```

### Baseline

```text
Temporal Log / SQL Scan, Recall Memory, EviStateDB, and Latest/Arrival diagnostic lower bound are evaluated
results reported by stream, query type, predicate family, horizon
EviStateDB ablations are evaluated
failure analysis exists
```

### Artifact

```text
public artifact validates with one command
answer sets are evaluator-only
no public-hidden leakage
code/data/environment are sufficient for reproduction
all tables/figures can be regenerated
```

The project does not claim final benchmark readiness until this entire checklist is satisfied.

---

## 14. Strong-Version Risk Control

### Current Verdict

```text
BUILD-TO-FULL-RELEASE
```

The plan is now a full-release engineering target.

### Strong points

```text
1. The plan directly maps ICDE EAB standards to artifact requirements.
2. It separates benchmark contribution from EviStateDB baseline contribution.
3. It recognizes current v7 limitations instead of hiding them.
4. It turns perturbations into documented workload pathologies.
5. It includes reproducibility and public-hidden boundary checks.
```

### Risks To Control

```text
1. Multi-instance support may be blocked by available BEHAVIOR assets and environment stability.
2. Full BDDL task-level semantics may be expensive and unreliable.
3. Perception-derived subset may take longer than controlled generation.
4. Baseline results depend on the baseline repo owner.
5. Scale can hurt quality if we add tasks faster than we can audit state transitions.
```

### Engineering Rule

```text
No scale expansion is accepted without validation, diversity audit, query audit,
perturbation audit, and public-hidden leakage audit.
```

### Execution Order

The engineering order is:

```text
1. release-grade validation foundation
2. full task / state / instance diversity expansion
3. full query suite
4. formal perturbation model
5. demo/perception and execution-gap subsets
6. baseline integration and paper tables
```

---

## 15. Execution TODO

这个 TODO 是后续唯一执行清单。完成一项就只在这里打勾；不再另开新路线。

### 15.1 Release-Grade Artifact Foundation

- [x] Freeze v7 as gap-baseline checkpoint and record `PASS_WITH_LIMITS` status.
- [x] Generate v7 release validation report, artifact card, data statement, public-hidden boundary audit, reproducibility report, and checksums.
- [x] Remove release portability warnings from the current checkpoint.
- [x] Promote release validator from v7 checkpoint validation to final-release validation rules.
- [x] Add license/source statement to the release validation output.
- [x] Add baseline prediction format validation to the release validator.

### 15.2 Full Task / State / Instance Diversity

- [x] Build candidate manifest for 50 activities.
- [x] Validate 3 activity instances per activity.
- [ ] Generate 450 controlled semantic primitive episodes.
- [ ] Cover 8 state-family groups and 20 core predicates.
- [ ] Generate `task_diversity_matrix.csv` and `task_diversity_matrix.md`.
- [ ] Validate short / medium / long horizon coverage.
- [ ] Validate that no predicate family dominates target events.

### 15.3 Full Query Suite

- [ ] Implement WHY_STATE query generation.
- [ ] Implement WHY_STATE answer generation and evaluator metrics.
- [ ] Implement FIND_UNCERTAIN_STATES.
- [ ] Implement CHECK_PRECONDITION.
- [ ] Implement FAILURE_LOCALIZATION.
- [ ] Add `target_goal`, `bddl_goal_subset`, and `full_bddl_goal` query scopes.
- [ ] Generate query semantics report, query semantics matrix, and answer schema validation report.

### 15.4 Formal Perturbation Model

- [ ] Write `perturbation_profile.json`.
- [ ] Rebuild public streams with low / medium / high severity.
- [ ] Keep mixed as the primary robustness stream.
- [ ] Add perturbation audit report.
- [ ] Validate timestamp and evidence id consistency after perturbation.

### 15.5 Demo / Perception / Execution-Gap Subsets

- [ ] Select 50 official demo/perception-derived episodes.
- [ ] Map official demos parquet / metadata into StateObservation.
- [ ] Export RGB/depth evidence refs.
- [ ] Add detector/depth/VLM-derived StateObservation mapping.
- [ ] Add 20 execution-gap diagnostic episodes.
- [ ] Generate rawdata asset lock report.

### 15.6 Baseline Integration And Paper Tables

- [ ] Receive baseline predictions from the baseline repo.
- [ ] Evaluate Temporal Log / SQL Scan.
- [ ] Evaluate Recall Memory Baseline.
- [ ] Evaluate EviStateDB.
- [ ] Evaluate Latest Observation / Arrival-latest diagnostic lower bound.
- [ ] Run EviStateDB ablations.
- [ ] Export paper tables by stream, query type, predicate family, and horizon.
- [ ] Select failure analysis examples.

### 15.7 Final Release Gate

- [ ] Public artifact validates with one command.
- [ ] Answer sets are evaluator-only.
- [ ] Public-hidden leakage audit passes.
- [ ] Code/data/environment reproduce the reported results.
- [ ] All tables and figures can be regenerated.
- [ ] Final release status is `PASS`.

---

## 16. Source Notes

Key external sources used:

```text
ICDE 2026 Call for Research Papers
https://icde2026.github.io/cf-research-papers.html

LDBC Social Network Benchmark specification
https://ldbcouncil.org/ldbc_snb_docs/ldbc-snb-specification.pdf

LDBC Financial Benchmark: Transaction Workload
https://www.vldb.org/pvldb/vol18/p3007-qi.pdf

TSM-Bench: Benchmarking Time Series Database Systems for Monitoring Applications
https://www.vldb.org/pvldb/vol16/p3363-khelifati.pdf

BEHAVIOR-1K paper
https://arxiv.org/html/2403.09227v1
https://proceedings.mlr.press/v205/li23a.html
```
