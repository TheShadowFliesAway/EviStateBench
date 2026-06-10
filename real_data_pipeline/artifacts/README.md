# Artifacts

这里保存本地生成结果。默认不要把这个目录提交为代码资产。

当前保留：

```text
stage3_v7_scale72_seed6_ideal/
public_v7_scale72_seed6_ideal_full/
stage3_v6_local_diversity_seed6/
stage3_v6_local_diversity_seed0/
stage3_v3_scale48_seed6/
public_v5_scale48_seed6_full/
public_v3_scale48_seed6_main/
stage3_v4_local_seed3/
public_v4_local_seed3_main/
download_probe/
download_probe_stage_b/
environment_freeze_20260610T124824Z/
source_audits/
stage3_selection_smoke/
v4_task_diversity_selection/
```

`stage3_*` 是 raw episode / simulator truth / clean observation 中间产物。
`public_*` 是给 benchmarked systems 使用的 public package，加上 evaluator-only hidden answer sets。

## Current Main Artifact

当前可用的主 pilot artifact：

```text
public_v7_scale72_seed6_ideal_full/
```

规模：

```text
tasks: 12
episodes: 72
queries: 900
public streams: clean / delay / out_of_order / missing / low_confidence / conflict / mixed
clean observations: 853100
validation: PASS
profile: PASS_WITH_LIMITS
```

主要报告：

```text
public_v7_scale72_seed6_ideal_full/reports/benchmark_profile_report_v1.md
public_v7_scale72_seed6_ideal_full/reports/quality_audit_v0.md
public_v7_scale72_seed6_ideal_full/reports/release_validation_v0/release_validation_report.md
public_v7_scale72_seed6_ideal_full/reports/release_validation_v0/artifact_card.md
public_v7_scale72_seed6_ideal_full/reports/release_validation_v0/data_statement.md
public_v7_scale72_seed6_ideal_full/reports/paper_tables_v0/paper_tables_report.md
public_v7_scale72_seed6_ideal_full/reports/breakdown_tables_v0/breakdown_tables_report.md
```

限制：

```text
queries remain target-scoped, not full task-level BDDL semantics
release validation status is PASS_WITH_LIMITS
formal baseline results are not included yet
not a final ICDE-ready release
```
