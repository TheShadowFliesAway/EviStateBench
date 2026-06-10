# BEHAVIOR Data Download Plan

本文档定义 EviStateBench 后续补真实 episode / instance diversity 时，应该下载什么、先探测什么、避免下载什么。

当前状态更新：

```text
2025-challenge-rawdata HDF5 exact replay 不是当前可闭环主线。
我们已经验证：本地 replay 会遇到 public assets 与 rawdata 期望 USD/hash 不一致；
HF public zipped-datasets 历史中没有可切换的不同 assets snapshot。

当前可闭环补充路线是：
  2025-challenge-demos v2.1 parquet / metadata / selected videos

主 benchmark 仍然走：
  controlled OmniGibson / BEHAVIOR simulator-grounded generation
```

结论先写清楚：

```text
不要用 tro_state 作为主 benchmark episode 来源。
不要把 raw HDF5 exact replay 当成当前默认主线，除非 upstream 解决 asset/hash 对齐。
要补 perception/observation gap subset，优先使用 2025-challenge-demos 的 parquet / metadata / selected videos。
不要直接下载全量数据。
```

---

## 1. Official Sources

官方 BEHAVIOR dataset page:

```text
https://behavior.stanford.edu/challenge/dataset.html
```

HuggingFace datasets:

```text
behavior-1k/2025-challenge-task-instances
behavior-1k/2025-challenge-rawdata
behavior-1k/2025-challenge-demos
behavior-1k/2025-challenge-hidden-instances
```

官方说明中最关键的是：

```text
2025-challenge-demos:
  10000 human-collected teleoperation demos across 50 tasks.
  LeRobot format.
  Includes annotations, low-dim data, metadata, and videos.

2025-challenge-rawdata:
  original raw HDF5 data of the 10k teleoperation demos.
  Contains everything needed to replay the exact trajectory in OmniGibson.
```

对 EviStateBench 来说，`rawdata` 在概念上比 `tro_state` 更接近 replay episode，
但当前工程上被 asset/hash mismatch 阻塞。`2025-challenge-demos` 的 parquet /
metadata / videos 虽然不是 raw HDF5 exact simulator replay，但可以先作为官方
demo-derived observation/action-gap subset。

---

## 2. What Not To Do

不要下载全量：

```text
full 2025-challenge-demos
full 2025-challenge-rawdata
all videos
all cameras
all tasks
```

原因：

```text
1. 官方数据整体约 TB 级。
2. 当前 /root/autodl-tmp 可用空间约 252G，不能无脑全拉。
3. 我们需要的是 benchmark state-maintenance subset，不是训练 VLA policy。
4. 全量下载不能自动解决 query semantics / artifact validation / baseline discriminativeness。
```

不要把这些当作主 benchmark episode：

```text
joylo/sampled_task/*-tro_state.json
```

tro_state 可用于 source audit / schema audit / task selection，但不是 temporal rollout。

---

## 3. Download Priority

### Priority A: LeRobot metadata / low-dim data

目标：

```text
快速分析官方 demo 的 episode length、task id、metadata、actions/proprio，
并接入小规模 demo-derived subset。
```

只下载：

```text
meta/
data/task-XXXX/*.parquet for selected tasks
annotations/ if useful
```

暂时不下载：

```text
videos/
```

### Priority B: Raw HDF5 replay samples, blocked until assets align

目标：

```text
如果 upstream 给出匹配 assets snapshot，再验证能否从官方 HDF5 demo replay
中抽 simulator truth / StateObservation。
```

先选 5-10 个 task，每个 task 下载 2-5 个 episode。

优先任务：

```text
task-0000 turning_on_radio
task-0019 outfit_a_basic_toolbox
task-0023 boxing_books_up_for_storage
task-0035 attach_a_camera_to_a_tripod
task-0036 clean_a_patio
task-0040 make_microwave_popcorn
task-0045 cook_hot_dogs
task-0046 cook_bacon
task-0047 freeze_pies
```

这些任务和当前 EviStateBench state families 对齐：

```text
toggled_on
inside
attached
covered / cleaning-related
open
cooked / temperature
frozen / temperature
```

### Priority C: Perception-derived subset

目标：

```text
补 observation gap subset。
```

在 official demos parquet / metadata 跑通后，再按任务下载少量 selected videos：

```text
videos/task-XXXX/observation.images.rgb.*
videos/task-XXXX/observation.images.depth.*
videos/task-XXXX/observation.seg_instance_id.*
```

这部分用于 gap analysis，不作为主 correctness benchmark。

---

## 4. Expected Local Layout

建议下载到：

```text
/root/autodl-tmp/BEHAVIOR-1K/datasets/
```

目标结构：

```text
/root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-rawdata/
  task-0000/
    episode_00000010.hdf5
    ...
  task-0045/
    episode_00450010.hdf5
    ...

/root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-demos/
  meta/
  data/
  annotations/
  videos/   # optional, small selected subset only
```

OmniGibson replay script expects rawdata paths like:

```text
2025-challenge-rawdata/task-XXXX/episode_XXXXXXXX.hdf5
```

Relevant local replay code:

```text
/root/autodl-tmp/BEHAVIOR-1K/OmniGibson/scripts/learning/replay_obs.py
```

---

## 5. Probe Before Download

Run:

```bash
python real_data_pipeline/stages/probe_behavior_hf_datasets.py
```

Outputs:

```text
real_data_pipeline/artifacts/download_probe/behavior_hf_probe_v0.json
real_data_pipeline/artifacts/download_probe/behavior_hf_probe_v0.md
real_data_pipeline/artifacts/download_probe/rawdata_download_candidates_v0.jsonl
```

The probe does not download large files. It only queries HuggingFace file trees and local metadata.

---

## 6. Download Command Shape

After probe selects files, use HuggingFace download tooling.

当前优先下载 demos parquet / metadata：

```bash
huggingface-cli download behavior-1k/2025-challenge-demos \
  --repo-type dataset \
  --include "meta/*" \
  --include "data/task-0000/episode_00000010.parquet" \
  --local-dir /root/autodl-tmp/behavior1k_closed_combo/datasets/2025-challenge-demos
```

raw HDF5 命令仅在 asset/hash 对齐后再使用：

```bash
huggingface-cli download behavior-1k/2025-challenge-rawdata \
  --repo-type dataset \
  --include "task-0045/episode_00450010.hdf5" \
  --local-dir /root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-rawdata
```

For multiple raw HDF5 files:

```bash
huggingface-cli download behavior-1k/2025-challenge-rawdata \
  --repo-type dataset \
  --include "task-0000/episode_00000010.hdf5" \
  --include "task-0045/episode_00450010.hdf5" \
  --local-dir /root/autodl-tmp/BEHAVIOR-1K/datasets/2025-challenge-rawdata
```

If `huggingface-cli` is unavailable, install into the active BEHAVIOR environment, not blindly into base:

```bash
python -m pip install "huggingface_hub[cli]>=0.34.4"
```

---

## 7. Go / No-Go

Go:

```text
official demos parquet / metadata files are visible on HF
download size for probe subset is small enough for local disk
pyarrow can read at least one selected parquet episode
we can map demo low-dim / metadata / selected video refs into StateObservation
```

No-go:

```text
HF access requires unavailable credentials
raw HDF5 exact replay remains asset/hash mismatched
selected task files are too large for current disk
selected tasks do not overlap with EviStateBench state families
```

If no-go happens, demo-derived subset remains a documented limitation, and Milestone 2 should focus on task/state diversity from available challenge templates.
