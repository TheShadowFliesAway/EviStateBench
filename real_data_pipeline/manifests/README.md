# Manifests

这里保存真实 benchmark 的任务候选、pilot 配置和已验证任务列表。

当前主要入口：

```text
real_benchmark_pilot_tasks_v2.jsonl
real_benchmark_v4_local_action_candidates_v0.jsonl
```

manifest 中的 `primitive_jsonl` 指向 `real_data_pipeline/action_scripts/`。
旧 manifest 里可能保留已经清理掉的 historical validation path，仅用于复盘。
