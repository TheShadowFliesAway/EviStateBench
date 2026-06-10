# Tools Layout

`tools/` 现在只放 benchmark artifact 相关的共享脚本和历史 synthetic pipeline 归档。

## artifacts

当前真实 benchmark pipeline 仍会调用这些脚本：

```text
tools/artifacts/build_perturbed_observations.py
tools/artifacts/build_query_sets.py
tools/artifacts/build_ground_truth_answers.py
tools/artifacts/build_public_artifacts.py
tools/artifacts/validate_public_artifacts.py
tools/artifacts/evaluate_answers.py
```

它们不负责启动 OmniGibson，也不负责生成 simulator truth。它们接收已经抽取好的
timeline、clean observations、task specs，然后生成 perturbation streams、queries、
answer sets、public package 和 evaluator reports。

## synthetic_legacy

这里保留旧 synthetic v0 顺序脚本和 BDDL audit：

```text
tools/synthetic_legacy/audit_bddl_tasks.py
tools/synthetic_legacy/0_extract_task_predicate_instances.py
tools/synthetic_legacy/1_build_synthetic_timelines.py
tools/synthetic_legacy/2_build_clean_observations.py
```

这些脚本不是当前真实 benchmark 的主线。保留它们是为了复盘早期设计和必要时再生成
synthetic v0 本地数据。
