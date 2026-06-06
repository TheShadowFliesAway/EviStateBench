# LifelongSceneDB Core

这是从 `main` 分支瘦身出来的核心版本，只保留 LifelongSceneDB 主方法相关代码，方便继续理解和改动。

这个分支刻意删掉了 benchmark、baseline、sweep、绘图、历史输出和测试结果。当前重点不是把论文实验外壳做厚，而是先把主方法本身看清楚、改扎实。

## 保留内容

```text
lifelongscenedb/
  schema.py       Observation / Fact / QueryResult 数据结构
  store.py        原始观察、融合事实、证据流水的内存存储
  indexes.py      面向事实查询的轻量索引
  confidence.py   置信度融合、冲突衰减、时间衰减
  updater.py      Observation -> Fact 的核心更新逻辑
  queries.py      候选排序和 QueryResult 封装
  db.py           LifelongSceneDB 对外查询接口
  utils.py        toy case 用到的少量文件工具

scripts/
  run_toy_case.py 最小可运行示例
```

核心管线可以理解成：

```text
Observation
  -> SceneUpdater.ingest_observation
  -> MemoryStore / MemoryIndexes
  -> Fact
  -> LifelongSceneDB 查询接口
```

## 运行

```bash
cd /root/autodl-tmp/LifelongSceneDB-core-slim
conda activate lscene
python -m pip install -e .
python scripts/run_toy_case.py
```

如果当前 shell 没有激活 conda，也可以直接使用这个解释器：

```bash
/root/autodl-tmp/conda/envs/lscene/bin/python scripts/run_toy_case.py
```

toy case 会写出：

```text
outputs/toy_case/facts.csv
outputs/toy_case/observations.csv
outputs/toy_case/results.json
```

`outputs/` 已经被 `.gitignore` 忽略，不会再把实验结果提交进仓库。

## 当前边界

这个 core 版本仍然主要表达：

```text
subject predicate object/location
```

也就是当前代码最主要支持的 `object in location` 这一类事实。后续如果要接入 BEHAVIOR1000 或真实视频流，优先应该扩展主方法的数据表示和 Observation 抽取接口，而不是继续堆更多 benchmark 脚本。
