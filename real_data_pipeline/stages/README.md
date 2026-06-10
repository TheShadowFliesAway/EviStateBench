# Stages

真实 benchmark generator 的可执行入口。文件名表达职责，执行顺序写在这里：

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
9  validate_release.py
10 probe_behavior_hf_datasets.py
```

这些脚本默认把新生成结果写到 `real_data_pipeline/artifacts/`，不再写到
`real_data_pipeline/` 顶层。

`validate_release.py` 是 Milestone 1-lite 的 release gate。它读取一个 public artifact，
生成 release validation、public-hidden boundary audit、artifact card、data statement、
reproducibility report 和 checksum 文件。当前 v7 跑出的状态应视为 `PASS_WITH_LIMITS`，
即结构可用但还不是 final ICDE-ready release。

`probe_behavior_hf_datasets.py` 是 BEHAVIOR 官方 HuggingFace 数据下载前探针。它只查询
repo file tree 和本地 metadata，不下载 HDF5/parquet/video 大文件，用于决定下一步
official demos parquet / metadata subset，或在 asset/hash 对齐后再决定 rawdata 下载清单。

`download_behavior_rawdata_subset.py` 和 `validate_behavior_rawdata_subset.py` 是 raw HDF5
诊断工具。当前 raw HDF5 exact replay 受 asset/hash mismatch 阻塞，所以它们不是默认主线。
