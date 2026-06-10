# Project Cleanup Status

清理日期：2026-06-09
最近更新：2026-06-10

本次清理目标是把当前真实 benchmark 工作线和历史试跑产物分开，避免 README 和目录结构继续指向已经过时的 v0/v1/v2/smoke 结果。

当前原则：

```text
不要随便新增 md。
优先维护已有源文档：
  README.md
  EviStateBench_IDEA.md
  EviStateBench_PAPER_WRITING_BLUEPRINT.md
  real_data_pipeline/README.md
  real_data_pipeline/REAL_BENCHMARK_PROTOCOL.md
  real_data_pipeline/ICDE_BENCHMARK_ENRICHMENT_PLAN.md
  real_data_pipeline/BEHAVIOR_DOWNLOAD_PLAN.md
  real_data_pipeline/PROJECT_CLEANUP.md
```

其中 `BEHAVIOR_DOWNLOAD_PLAN.md` 现在是数据源决策记录：
raw HDF5 exact replay 已被标注为 asset/hash mismatch 阻塞；
当前可闭环补充路线是 official 2025-challenge-demos v2.1 parquet / metadata subset。

## Retained

当前保留代码和小型配置：

```text
real_data_pipeline/*.md
real_data_pipeline/env_behavior.sh
real_data_pipeline/stages/*.py
real_data_pipeline/manifests/*.jsonl
real_data_pipeline/action_scripts/*.jsonl
real_data_pipeline/*/README.md
evistatebench/
tools/
```

`tools/artifacts/` 是当前真实 benchmark 仍复用的共享 artifact/evaluator 工具；
`tools/synthetic_legacy/` 是旧 synthetic v0 和 BDDL audit 归档。

当前保留正式 artifact：

```text
real_data_pipeline/artifacts/stage3_v7_scale72_seed6_ideal
real_data_pipeline/artifacts/public_v7_scale72_seed6_ideal_full
real_data_pipeline/artifacts/stage3_v6_local_diversity_seed6
real_data_pipeline/artifacts/stage3_v6_local_diversity_seed0
real_data_pipeline/artifacts/public_v5_scale48_seed6_full
real_data_pipeline/artifacts/stage3_v3_scale48_seed6
real_data_pipeline/artifacts/public_v3_scale48_seed6_main
real_data_pipeline/artifacts/stage3_v4_local_seed3
real_data_pipeline/artifacts/public_v4_local_seed3_main
```

`public_v7_scale72_seed6_ideal_full/` 是当前主 artifact，但状态仍是
`PASS_WITH_LIMITS`，不能写成 final ICDE-ready release。stage3 artifact 保留
`episodes/`、`benchmark_generation_summary.*` 和 `episode_run_summaries.jsonl`。
`runs/` 过程日志应继续清理。

当前保留小型诊断记录：

```text
real_data_pipeline/artifacts/environment_freeze_20260610T124824Z
real_data_pipeline/artifacts/download_probe
real_data_pipeline/artifacts/download_probe_stage_b
real_data_pipeline/artifacts/source_audits
real_data_pipeline/artifacts/stage3_selection_smoke
real_data_pipeline/artifacts/v4_task_diversity_selection
```

## Removed

已删除的本地生成内容：

```text
data/
reports/
evistatebench/__pycache__/
tools/__pycache__/
real_data_pipeline/__pycache__/
real_data_pipeline/artifacts/runtime_probe/
real_data_pipeline/artifacts/runtime_probe_from_envsh/
real_data_pipeline/reports_real_benchmark_gap_fill_validation/
real_data_pipeline/reports_real_benchmark_pilot_v0/
real_data_pipeline/reports_real_benchmark_public_v0/
real_data_pipeline/reports_real_benchmark_public_v1/
real_data_pipeline/reports_real_benchmark_public_v1_main/
real_data_pipeline/reports_real_benchmark_public_v2_main/
real_data_pipeline/reports_real_benchmark_second_batch_validation/
real_data_pipeline/reports_real_benchmark_v1/
real_data_pipeline/reports_real_benchmark_v2/
real_data_pipeline/reports_real_benchmark_v4_cook_bacon_smoke/
real_data_pipeline/reports_real_benchmark_v4_diversity_smoke/
real_data_pipeline/reports_real_benchmark_v4_local_action_smoke*/
real_data_pipeline/artifacts/stage3_v3_scale48_seed6/runs/
real_data_pipeline/artifacts/stage3_v4_local_seed3/runs/
```

清理后项目占用约 3.3 GiB；主要空间来自当前 v3 artifact、v3 public package 和 `.git/objects`。

## Policy

`data/`、`reports/` 和 `real_data_pipeline/artifacts/*` 都是本地生成产物，
默认被 `.gitignore` 忽略；`real_data_pipeline/artifacts/README.md` 例外，
作为目录说明保留。

如果需要复现旧结果，从保留的 manifest 重新运行：

```bash
python real_data_pipeline/stages/run_pilots.py ...
python real_data_pipeline/stages/build_artifacts.py ...
python real_data_pipeline/stages/profile_report.py ...
python real_data_pipeline/stages/quality_audit.py ...
```
