# Real Data Pipeline

这个目录用于放 BEHAVIOR / OmniGibson 真实数据接入相关脚本。

它和 `tools/` 的边界如下：

```text
tools/
  artifacts/            真实 benchmark 仍复用的 public/evaluation 工具
  synthetic_legacy/     旧 synthetic v0 pipeline 和 BDDL audit 归档

real_data_pipeline/
  BEHAVIOR / OmniGibson real-data source audit
  task instance probing
  simulator truth extraction
  real hidden timeline construction
  real observation stream generation
```

当前优先级：

```text
1. 维护当前可复现的 controlled simulator-grounded benchmark generator。
2. 把 public artifact 做到 release-grade validation。
3. 扩 task / state / horizon / query diversity。
4. 用官方 replayed demos v2.1 补 observation/action gap subset。
5. raw HDF5 exact replay 只作为阻塞诊断线，不作为当前主线。
```

这里的脚本应该服务真实数据 pipeline，不要和 `tools/synthetic_legacy/` 混在一起。

## 当前目录结构

```text
stages/
  0-9 真实 benchmark pipeline 可执行入口。

manifests/
  pilot tasks、candidate tasks、v4 local-action 配置。

action_scripts/
  recorder replay 的 primitive JSONL 动作脚本。

artifacts/
  本地生成结果，包括当前保留的 v3/v4 stage3 和 public artifact。
  该目录默认被 .gitignore 忽略，只有 artifacts/README.md 作为说明保留。
```

## 当前 Benchmark Scope 决策

当前真实 benchmark 的主定位是：

```text
Simulator-grounded temporal state observation benchmark
```

也就是说，它不是端到端机器人视觉感知 benchmark，也不是低层机器人控制 benchmark。
它评测的是：系统如何从带延迟、缺失、冲突、低置信度、乱序等问题的结构化状态观察流中，
维护可查询、可修正、可追溯的 temporal task-state view。

因此当前路线明确分为主 benchmark 和补充 subset：

```text
主 benchmark
  symbolic primitive + simulator truth + perturbed structured observations

  目标：
    大规模、稳定、可控地生成有真实 OmniGibson object-state 支撑的状态变化 episode。
    hidden truth timeline 来自 simulator truth。
    public observation stream 来自 clean StateObservation 再注入扰动。

  论文表述边界：
    可以说 simulator-grounded / BEHAVIOR-derived / structured temporal state observations。
    不能说这是完整真实机器人视觉观测流。
    不能说 symbolic primitive episode 证明机器人通过低层控制完成任务。

补充 subset
  少量 RGB / depth / detector / VLM-derived observations
  官方 replayed demos v2.1 parquet / metadata / video-derived observations
  starter / policy rollout episode if runtime becomes stable

  目标：
    做 gap analysis，展示主 benchmark 的结构化 observation 与更接近真实感知 /
    低层执行轨迹之间的差异。
    这部分用于增强说服力，不阻塞主 benchmark 数据生成。
```

这里需要显式承认两个 gap：

```text
action gap
  symbolic semantic primitive 触发真实 simulator state change，
  但不是完整低层导航、抓取、操作 policy。

observation gap
  clean StateObservation 是从 simulator truth 派生的结构化观察，
  后续扰动模拟真实感知系统常见问题，
  但它不是直接从 RGB / depth / VLM / detector 端到端得到的原始观测。
```

这两个 gap 不是要隐藏的问题，而是 benchmark scope 的一部分：
主 benchmark 刻意隔离 perception 和 low-level control，集中评测 temporal state maintenance。
补充 subset 再用于衡量和缩小真实感知 / 真实执行 gap。

第一批真实 benchmark pilot 任务选择已经记录在：

```text
real_data_pipeline/artifacts/stage3_selection_smoke/benchmark_task_selection_report.md
real_data_pipeline/manifests/real_benchmark_pilot_tasks_v0.jsonl
```

第一批正式生成报告、第二批扩展候选和后续 gap-fill manifest 属于历史迭代记录。
大体积的旧 generation / public artifact 已清理，只保留小型 manifest / selection report
用于复盘和复现：

```text
real_data_pipeline/manifests/real_benchmark_pilot_tasks_v0.jsonl
real_data_pipeline/manifests/real_benchmark_pilot_tasks_v1.jsonl
real_data_pipeline/manifests/real_benchmark_pilot_tasks_v2.jsonl
real_data_pipeline/manifests/real_benchmark_second_batch_candidates_v0.jsonl
real_data_pipeline/manifests/real_benchmark_gap_fill_candidates_v0.jsonl
```

真实 benchmark 的工程协议写在：

```text
real_data_pipeline/REAL_BENCHMARK_PROTOCOL.md
```

面向 ICDE EAB 标准的 benchmark 丰富计划写在：

```text
real_data_pipeline/ICDE_BENCHMARK_ENRICHMENT_PLAN.md
```

当前 BEHAVIOR 官方数据源状态：

```text
可闭环：
  controlled OmniGibson / BEHAVIOR generator
  official 2025-challenge-demos v2.1 parquet / metadata subset

阻塞：
  official 2025-challenge-rawdata HDF5 exact replay
  原因是 public assets 与 rawdata replay 期望的 USD/hash 不一致；
  已验证 HF public zipped-datasets 历史中没有不同的 assets snapshot 可切换。

不作为主线：
  tro_state snapshot
  它只能做 source/schema audit，不能替代 temporal rollout。
```

当前 Milestone 1-lite 的 release gate 写在：

```text
real_data_pipeline/stages/validate_release.py
```

当前 v7 的 release validation 输出在：

```text
real_data_pipeline/artifacts/public_v7_scale72_seed6_ideal_full/reports/release_validation_v0/
```

BEHAVIOR 官方 demo/rawdata 的下载计划与下载前探测写在：

```text
real_data_pipeline/BEHAVIOR_DOWNLOAD_PLAN.md
real_data_pipeline/stages/probe_behavior_hf_datasets.py
real_data_pipeline/artifacts/download_probe/behavior_hf_probe_v0.md
```

注意：`BEHAVIOR_DOWNLOAD_PLAN.md` 现在是数据源决策记录，不再表示 raw HDF5
replay 是当前默认路线。

后续扩任务、改 query、改扰动、划分 split，都应先和这个 protocol 对齐。

## 真实 Benchmark Stage 设计

`real_data_pipeline/` 是 BEHAVIOR / OmniGibson-derived benchmark generator，
不是 EviStateDB baseline engine。需要明确三条边界：

```text
tools/artifacts/
  通用 artifact 工具：扰动、query、answer、public package、validation 和 evaluator。
  当前真实 benchmark pipeline 仍会调用这里的脚本。

tools/synthetic_legacy/
  旧 synthetic v0 pipeline 和 BDDL audit 归档。

evistatebench/engine/
  EviStateDB reference baseline engine，属于 baseline contribution。
  它不是 benchmark oracle，也不是 public artifact 依赖。

real_data_pipeline/
  真实 BEHAVIOR / OmniGibson benchmark generator。
  目标是从 simulator truth 和 task specification 生成真实 benchmark 数据。
```

真实 benchmark pipeline 的阶段定义如下：

```text
0. Source audit
   只读扫描本地 BEHAVIOR / BDDL / OmniGibson 文件，确认 task definitions、
   task-instance templates、assets、object-state modules、tro_state snapshots、
   challenge metadata 等数据源是否存在。

1. Runtime readiness probe
   验证 Python / CUDA / Vulkan / BDDL / OmniGibson 环境是否能 import、解析 task、
   定位 template。它只证明 runtime 可用，不生成 benchmark 数据。

2. Static observation audit
   审计 tro_state snapshot 和 task template 能映射到哪些 StateObservation 字段。
   这一步服务 schema 对齐，但 tro_state 不是完整 temporal rollout，所以不能作为
   最终真实 benchmark 的 hidden timeline 来源。

3. Live simulator benchmark generator
   启动 OmniGibson，加载真实 BEHAVIOR task instance，从明确 action source 运行
   episode，记录 simulator truth，并生成真实 benchmark 的核心中间产物。
```

第 3 步的最终职责不是“能 reset / step 就算完成”，而是替换 synthetic pipeline 中
人为构造的 hidden timeline。它应该逐步做到：

```text
3.1 Episode setup
    加载 cached BEHAVIOR task instance，绑定 scene、robot、task object scope、
    BDDL goal conditions 和稳定 episode_id。

3.2 Action-source replay
    从明确 action source 运行仿真。action source 可以是 demo replay、policy rollout、
    semantic primitive script，或者 no-op smoke。recorder 不负责自己求解 BEHAVIOR 任务；
    任务进展来自 action source。

3.3 Simulator-truth recording
    每一步记录 hidden world truth：object pose、object state、relation predicate、
    robot state、action trace、task object scope、BDDL goal satisfaction。
    这些是 oracle material，不是 public observation。

3.4 Hidden state timeline extraction
    把逐步 simulator truth 转成 episode-scoped state timeline：
    predicate_name、arguments、value、event_time、change point / valid interval、
    simulator evidence reference。

3.5 Clean observation extraction
    用明确的 observation-source policy 从 hidden truth 生成 clean StateObservation stream。
    clean observation 可以高置信，但仍然是 public input candidate，不是 hidden truth table。

3.6 Perturbation / query / answer / public packaging handoff
    后续阶段或通用工具负责注入 delay、missing、conflict、low confidence、out-of-order，
    生成 queries、hidden ground-truth answers，并清理 public artifacts。
```

最终第 3 步至少应输出：

```text
episode_manifest.json
  task、scene、action source、object scope、版本和运行配置。

simulator_truth_snapshots.jsonl
  每步原始 simulator truth，hidden / oracle-only。

hidden_state_timeline.jsonl
  从 simulator truth 抽出的状态变化和有效区间，hidden / oracle-only。

clean_state_observations.jsonl
  符合 StateObservation schema 的 clean observation stream，后续用于 public stream 生成。

task_spec.json 或 task_specs.jsonl row
  public task spec、object scope、goal predicates。

generation_report.{json,md}
  predicate 覆盖、对象数量、goal 进展、失败阶段、耗时和环境信息。
```

已建立的入口：

```text
source_audit.py
  只读扫描本地 BEHAVIOR / OmniGibson 文件源，回答“有哪些数据可以用”。

runtime_probe.py
  轻量验证当前 Python 环境、依赖、PYTHONPATH、BDDL parse、OmniGibson import，
  同时检查 task template + tro_state snapshot 是否足够支撑 snapshot-grounded pilot。

static_observation_audit.py
  双向审计 tro_state snapshot 和 StateObservation v0：
  一方面统计 tro_state 实际能抽出哪些 observation candidates，
  另一方面检查 StateObservation 各字段能否被 tro_state 直接提供。

live_recorder.py
  第 3 步 live simulator benchmark generator 的当前实现入口：
  加载一个 cached BEHAVIOR task instance，从明确 action source 运行 headless episode，
  记录 simulator truth snapshots，并派生 hidden_state_timeline、clean_state_observations、
  episode_manifest、task_spec 和 generation_report。
  目前 action source 支持 noop / random / jsonl action vector / primitive_jsonl。
  `primitive_jsonl` 是显式 semantic primitive script replay；policy rollout 是下一步要接入的动作源。

run_pilots.py
  批量运行真实 benchmark pilot manifest：
  读取 real_benchmark_pilot_tasks_v0.jsonl，按 seed / instance 生成多个 episode，
  自动传 focused relation sampling，验证目标 transition，并输出统一 generation summary。

build_artifacts.py
  把第 4 步生成的真实 episode artifact 接到 public benchmark artifact 链路：
  先把真实 hidden_state_timeline / clean_state_observations / task_spec 规范化成
  real-v0 intermediate，再调用通用工具生成 perturbed observation streams、query set、
  hidden answer sets、sanitized public package，并运行 public artifact validation。

  当前默认只把每个 episode 的 expected semantic transition 作为 query target，
  例如 open / toggled_on / covered / inside；完整 clean/public observation stream
  仍保留 pose、velocity、joint_state 等背景观测，作为扰动和状态维护的输入上下文。

profile_report.py
  读取 public artifact、intermediate manifest、episode index、query set 和 answer sets，
  生成 benchmark profile / split 报告。它负责报告 horizon split、predicate family、
  query workload、stream profile、artifact size 和 scale readiness。
```

推荐运行环境：

```text
/root/autodl-tmp/conda/envs/behavior-cu128
```

这个环境已经包含 Python 3.10、BDDL、OmniGibson、Isaac Sim、PyTorch/CUDA 等依赖，
并使用 PyTorch cu128 以支持 RTX 5090 / Blackwell 的 sm_120 CUDA kernel。旧的
`/root/autodl-tmp/conda/envs/behavior` 环境保留作回退，不作为默认真实仿真运行环境。
当前 `base` 环境是 Python 3.12，缺少 OmniGibson runtime 依赖，且 PyTorch/CUDA 版本过旧，
不适合跑真实数据 pipeline。

终端中使用：

```bash
source real_data_pipeline/env_behavior.sh
python real_data_pipeline/stages/runtime_probe.py --output-dir real_data_pipeline/artifacts/runtime_probe
python real_data_pipeline/stages/static_observation_audit.py --output-dir real_data_pipeline/artifacts/runtime_probe
python real_data_pipeline/stages/live_recorder.py --output-dir real_data_pipeline/artifacts/runtime_probe
python real_data_pipeline/stages/build_artifacts.py --clean-output
```

第 3 步默认会把正式 episode artifact 写到：

```text
<output-dir>/episodes/<episode_id>/
  episode_manifest.json
  simulator_truth_snapshots.jsonl
  hidden_state_timeline.jsonl
  clean_state_observations.jsonl
  task_spec.json
  generation_report.json
  generation_report.md
  action_trace.jsonl
```

semantic primitive script 是 JSONL，每行一条明确动作，例如：

```json
{"primitive": "OPEN", "object": "microwave.n.02_1"}
{"primitive": "WAIT", "steps": 10}
{"primitive": "CLOSE", "object": "microwave.n.02_1"}
```

当前默认 primitive backend 是 `symbolic`，它使用 OmniGibson 的 symbolic semantic
primitive，直接把对象推进到 primitive 的后置状态，适合先做可控 benchmark episode。
如果要尝试真实低层导航 / 抓取 / 放置规划，可以显式指定 `--primitive-backend starter`，
但这条路线更慢，也更容易受机器人控制器、CuRobo 和场景几何影响。

较大的真实仿真任务建议显式提高 timeout，例如：

```bash
python real_data_pipeline/stages/live_recorder.py \
  --output-dir real_data_pipeline/artifacts/runtime_probe_gift_baskets \
  --activity-name assembling_gift_baskets \
  --scene-model house_double_floor_lower \
  --activity-definition-id 0 \
  --activity-instance-id 0 \
  --steps 1 \
  --runtime-timeout 900
```

VSCode 工作区的本地解释器也已经指向：

```text
/root/autodl-tmp/conda/envs/behavior-cu128/bin/python
```

## 当前真实 Public Artifact

当前最新正式结果是 v3 controlled scale-up。

原计划扩成 `8 tasks x 3 seeds x 2 instances = 48 episodes`。但当前本机
BEHAVIOR-1K challenge-task-instances 子集里，这 8 个任务都只有
`definition=0, instance=0` 的缓存模板，没有 `instance=1` 模板。因此 v3 采用当前
数据条件下可复现的等规模配置：

```text
8 tasks x 6 seeds x 1 available instance = 48 episodes
seeds: 0, 1, 2, 3, 4, 5
activity_instance_ids: 0
stage3 status: 48 / 48 PASS, 48 / 48 transition_ok
```

v3 继承 v2 补上的两个 split 空洞，并扩大到 48 episodes：

```text
medium horizon
  5 episodes。p6_freeze_pies_medium 有 5 个 seed 被按实际 target event_time 归为 medium。
  另有 1 个 seed 的 frozen 出现较晚，final_target_time=731，被 profile 归为 long。

contact / attached family
  6 episodes。p7_attach_camera_to_tripod，attached false -> true。
```

v3 保留主发布 profile：

```text
main release profile
  path: real_data_pipeline/artifacts/public_v3_scale48_seed6_main
  streams: clean + mixed
  compression: public streams 和 perturbation streams 均为 .jsonl.gz
  用途: 默认 public artifact / leaderboard 输入。
```

v3 生成和构建命令：

```bash
python real_data_pipeline/stages/run_pilots.py \
  --manifest real_data_pipeline/manifests/real_benchmark_pilot_tasks_v2.jsonl \
  --output-dir real_data_pipeline/artifacts/stage3_v3_scale48_seed6 \
  --clean-output \
  --seeds 0,1,2,3,4,5 \
  --activity-instance-ids 0 \
  --max-runtime-steps 1200 \
  --runtime-timeout 1200 \
  --max-primitive-low-level-steps 260
```

v3 public artifact 构建命令：

```bash
python real_data_pipeline/stages/build_artifacts.py \
  --stage3-dir real_data_pipeline/artifacts/stage3_v3_scale48_seed6 \
  --output-dir real_data_pipeline/artifacts/public_v3_scale48_seed6_main \
  --clean-output \
  --perturbation-profile main \
  --gzip-perturbation-streams \
  --gzip-public-streams

python real_data_pipeline/stages/profile_report.py \
  --artifact-dir real_data_pipeline/artifacts/public_v3_scale48_seed6_main
```

v3 main+gzip artifact：

```text
real_data_pipeline/manifests/real_benchmark_pilot_tasks_v2.jsonl
real_data_pipeline/artifacts/stage3_v3_scale48_seed6/benchmark_generation_summary.md
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/reports/real_public_artifact_build_v0.md
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/reports/public_artifact_validation_v0.md
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/reports/benchmark_profile_report_v1.md
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/reports/benchmark_profile_summary_v1.json
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/public_v0/manifest.json
```

v3 main+gzip 验证结果：

```text
status: PASS
episodes: 48
tasks: 8
semantic_timeline_events: 180
clean_observations: 841208
queries: 516
public_observation_streams: 2
validation_errors: 0
target_predicates: open, toggled_on, covered, inside, cooked, temperature, frozen, attached
total_build_size: 924.39 MiB
public_v0_size: 60.61 MiB
public_observation_streams_size: 60.29 MiB
```

v3 main+gzip profile / split 结果：

```text
scale_readiness: PASS_WITH_LIMITS
stream_profile: main_release
horizon_split: short=30, medium=5, long=13
predicate_families:
  object_unary_state=36
  containment_or_spatial_relation=24
  numeric_state=12
  material_or_particle_state=6
  contact_configuration=6
query_scopes: target_state=372, target_goal=96, target_state_set=48
query_types: AS_OF_STATE=192, CHECK_STATE=180, CHECK_GOAL=96, STATE_DIFF=48
cautions:
  - CHECK_GOAL / STATE_DIFF 仍是 target-scoped，不是完整 BDDL task-level 语义。
```

v3 main+gzip public package 可以提供给被测系统：

```text
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/public_v0/task_specs.jsonl
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/public_v0/queries.jsonl
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/public_v0/observation_streams/*.jsonl.gz
```

v3 hidden / evaluator-only 内容不要作为 public input 暴露：

```text
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/intermediate/real_hidden_state_timeline_v0.jsonl
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/answer_sets_v0/*.jsonl
```

v3 quality audit：

```text
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/reports/quality_audit_v0.md
real_data_pipeline/artifacts/public_v3_scale48_seed6_main/reports/quality_audit_v0.json
```

v3 audit 结论：

```text
status: PASS
horizon_split: short=30, medium=5, long=13
主要 caution:
  - p5 / p6 frozen 相关任务存在 seed-sensitive horizon drift。
  - p5 seed005 和 p6 seed005 clean observation 数量偏大。
  - mixed stream 产生 unknown / uncertain / conflict answer，说明扰动确实提高了维护难度。
  - CHECK_GOAL / STATE_DIFF 仍必须标注为 target-scoped。
```

v4 task-diversity candidate / smoke 结果：

```text
real_data_pipeline/stages/select_task_diversity.py
real_data_pipeline/manifests/real_benchmark_v4_diversity_candidates_v0.jsonl
real_data_pipeline/artifacts/v4_task_diversity_selection/v4_task_diversity_selection_report.md
real_data_pipeline/artifacts/v4_task_diversity_selection/v4_task_diversity_smoke_report.md
```

当前 v4 smoke 结论：

```text
local BEHAVIOR templates scanned: 74
ready_for_validation: 0
smoke pass_runs: 0 / 2

v4_c0_boxing_books_inside:
  PLACE_INSIDE(book, box) 后 object dropped，symbolic primitive 不稳定。

v4_c1_cook_bacon_heat:
  PLACE_NEAR_HEATING_ELEMENT 仍卡在 OmniGibson 下游 pose sampler tensor conversion。
```

因此现在不要直接产出 v4 public artifact。v3 仍是当前正式 validated artifact。
下一步需要先解决 v4 action-source 策略：增加可控 local simulator-state primitives、
继续搜索已能稳定通过的 symbolic task，或把 starter / policy rollout 做成 supplemental subset。

v4 local-action validated artifact：

```text
stage3:
  real_data_pipeline/artifacts/stage3_v4_local_seed3

public artifact:
  real_data_pipeline/artifacts/public_v4_local_seed3_main

manifest:
  real_data_pipeline/manifests/real_benchmark_v4_local_action_candidates_v0.jsonl
```

v4 local-action 不是 symbolic / low-level policy rollout。它使用 recorder 内部显式
local simulator-state primitives：

```text
SET_STATE
SET_RELATION
```

这条路线的作用是快速补 task diversity / predicate diversity，并且必须在论文和报告中
标注为 controlled simulator-state action-source episodes。

v4 local-action validation 结果：

```text
tasks: 4
seeds: 0, 1, 2
episodes: 12
stage3 status: 12 / 12 PASS
transition_ok: 12 / 12
public validation: PASS
validation errors: 0
queries: 192
clean_observations: 5946
public streams: clean + mixed, .jsonl.gz
```

v4 local-action tasks：

```text
v4_local_c0_boxing_books_inside:
  boxing_books_up_for_storage
  inside(book.n.02_1, box.n.01_1) false -> true

v4_local_c1_cook_bacon_thermal:
  cook_bacon
  toggled_on(stove), temperature/max_temperature increase, cooked true

v4_local_c2_thaw_lobster:
  thawing_frozen_food
  frozen(lobster) true -> false, temperature increase

v4_local_c3_cool_fruitcake:
  cool_cakes
  toggled_on(oven) true -> false, hot(fruitcake) true -> false, temperature decrease
```

v4 local-action profile / audit：

```text
scale_readiness: PASS_WITH_LIMITS
horizon_split: short=12, medium=0, long=0
predicate_families:
  containment_or_spatial_relation=3
  object_unary_state=15
  numeric_state=12

主要 caution:
  - 仍是 pilot scale，只有 12 episodes。
  - 全部是 short horizon，medium / long 为空。
  - contact / attached family 未覆盖。
  - CHECK_GOAL / STATE_DIFF 仍是 target-scoped。
```

v4 local-action sanity：

```text
clean baseline:
  exact_accuracy: 0.9531
  state_diff_f1: 0.7833
  goal_predicate_f1: 1.0000

mixed baseline:
  exact_accuracy: 0.6823
  state_diff_f1: 0.3528
  goal_predicate_f1: 0.5833
```

关键报告：

```text
real_data_pipeline/artifacts/stage3_v4_local_seed3/benchmark_generation_summary.md
real_data_pipeline/artifacts/public_v4_local_seed3_main/reports/real_public_artifact_build_v0.md
real_data_pipeline/artifacts/public_v4_local_seed3_main/reports/public_artifact_validation_v0.md
real_data_pipeline/artifacts/public_v4_local_seed3_main/reports/benchmark_profile_report_v1.md
real_data_pipeline/artifacts/public_v4_local_seed3_main/reports/quality_audit_v0.md
```

## Artifact Retention / Cleanup

当前保留的真实 benchmark artifact：

```text
real_data_pipeline/artifacts/stage3_v3_scale48_seed6
real_data_pipeline/artifacts/public_v3_scale48_seed6_main
real_data_pipeline/artifacts/stage3_v4_local_seed3
real_data_pipeline/artifacts/public_v4_local_seed3_main
```

stage3 目录中保留 `episodes/`、`benchmark_generation_summary.*` 和
`episode_run_summaries.jsonl`；大体积 `runs/` recorder 过程日志已清理。

当前保留的小型诊断 / 候选记录：

```text
real_data_pipeline/artifacts/source_audits
real_data_pipeline/artifacts/stage3_selection_smoke
real_data_pipeline/artifacts/v4_task_diversity_selection
```

已经清理的内容包括：

```text
根目录 synthetic data / reports
旧 real pilot/public v0/v1/v2/gap-fill/second-batch 过程目录
v4 symbolic/local-action smoke scratch 目录
Python __pycache__ 缓存
当前 stage3 artifact 内的 runs/ 过程日志副本
```

旧结果如需复现，应从对应 manifest 重新运行 `run_pilots.py` 和
`build_artifacts.py`。当前默认不要把大体积生成目录提交进仓库；
`.gitignore` 已忽略 `data/`、`reports/` 和 `real_data_pipeline/artifacts/*`；
`real_data_pipeline/artifacts/README.md` 作为目录说明例外保留。
