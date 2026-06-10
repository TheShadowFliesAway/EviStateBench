# Baseline 实现思路短版

## Recall Memory Baseline

`Recall Memory Baseline` 是从主流 VLA / memory-augmented VLA 方案迁移过来的对比方法，而不是本项目新提出的状态维护方法。它主要借鉴两个代表性思路：第一，RT-2 将视觉语言模型的语义理解能力迁移到机器人控制中，把 observation 和 language instruction 作为条件输入，再生成 action token；在 EviStateBench 中，我们把这个“语言条件的视觉-动作生成接口”迁移成“语言/结构化 query 条件的状态答案生成接口”，也就是让模型根据当前 query 从历史观测中推理 `QueryAnswer`。第二，MEM 为 VLA 引入多尺度 embodied memory，用短期视觉记忆处理近期遮挡和局部细节，用长期文本记忆保存更抽象的任务阶段信息；在本 baseline 中，对应地把每条 `StateObservation` 渲染成可检索的 memory item，查询时根据 predicate、object arguments、task id 和时间信息取回 top-k 相关证据，再由规则或 LLM/VLM 汇总答案。这样设计可以较忠实地模拟主流 VLA 记忆框架的核心能力：依赖语义检索和任务条件推理来回忆历史证据；但它仍然不维护显式 valid-time / transaction-time state view，因此在 `AS_OF_STATE`、`STATE_DIFF`、冲突证据和迟到修复上预期会弱。

## Temporal Evidence View + Recall Fallback

`Temporal Evidence View + Recall Fallback` 是推荐的强 baseline，用来保证性能稳定优于 recall memory。它不是只检索历史片段，而是先把 observation stream 按 state key 维护成显式的时态证据视图，记录每个状态在 valid time 上的取值、置信度、support / contradict evidence，以及 late-arrival 对 transaction time 的影响；在证据完整时，它直接用这个 view 回答 `CHECK_STATE`、`AS_OF_STATE`、`STATE_DIFF` 和 `CHECK_GOAL`，因此能处理 recall memory 最容易混淆的时间区间、乱序到达和冲突证据。只有当 view 因 missing observation 返回 `unknown` 时，才调用 recall memory 作为 fallback 补全候选答案，所以它在能力上包含 recall 的优点，但主干仍然是时态状态维护。基于当前 v0 数据的轻量实验也支持这个选择：TEV + recall fallback 在 clean、delay、out-of-order、conflict 和 mixed 等 regime 的整体准确率都明显高于纯 Recall Memory。

## 二者核心区别

二者的根本区别在于，Recall Memory 是“查询时回忆”：它把历史 observation 当作可检索片段，等 query 到来时再找相关证据并临时推理答案；Temporal Evidence View + Recall Fallback 是“持续维护状态”：它在 observation 到达时就把证据融合进按 state key 组织的时态视图，显式区分 `event_time` 和 `arrival_time`，并保留 support / contradict evidence。前者更接近主流 VLA 的 memory retrieval 思路，强在语义检索和补全；后者更接近 EviStateBench 要评测的数据管理能力，强在状态区间、迟到修复、冲突处理和可审计解释。

以“把杯子放进柜子并关闭柜门”为例，系统需要回答 `AS_OF_STATE(inside(cup, cabinet), valid_time=10, transaction_time=12)`。

`Recall Memory` 的处理方式是把 query 渲染成检索请求，从历史 memory 中找出与 `inside(cup, cabinet)` 最相似的若干条 observation，例如动作日志说 place 成功、视觉检测器说没看到 cup、深度关系模型说 cup 在 cabinet 内，然后临时投票或让 LLM/VLM 汇总答案。它的风险是检索到的证据可能相关但时间语义不精确，尤其容易混淆“t=10 世界里是否成立”和“transaction_time=12 时系统是否已经收到证据”。

`TEV + Recall Fallback` 的处理方式是在 observation 到达时就维护 `inside(cup, cabinet)` 的时态视图。假设深度关系模型的证据 `event_time=10` 但 `arrival_time=15`，那么在 `transaction_time=12` 的 AS_OF 查询中，它不会提前使用这条迟到证据，而会返回当时可审计的 `unknown` 或基于已到达证据的判断；如果之后 `arrival_time=15` 的证据改写历史，它会记录 revision，并在后续 `WHY_STATE` 中返回支持和反驳的 observation ids。这个例子体现了二者的关键差别：Recall Memory 更像任务相关证据回忆，TEV-RF 更像带版本语义的状态维护。

## 轻量实验结果

当前评估方式沿用项目已有代码：`tools/5_build_ground_truth_answers.py` 先基于 hidden simulator timeline、task specification 和不同 observation stream regime 生成标准 `answer_sets_v0/*.jsonl`，其中 `CHECK_STATE` 和 `CHECK_GOAL` 主要对应 hidden world truth，`AS_OF_STATE` 对应 transaction-time 下系统当时可获得的 observation，`STATE_DIFF` 对应两个 valid time 之间的真值变化；随后 `tools/6_evaluate_answers.py` 将 baseline 输出的 predicted `QueryAnswer` 按 `query_id` 和 ground-truth answer 对齐，分别检查 `STATE_ANSWER` 的 value/status/state 是否匹配、`GOAL_ANSWER` 的 satisfied/status 和 goal predicate 集合是否匹配、`STATE_DIFF_ANSWER` 的 changed/added/removed state 集合是否匹配。当前 v0 数据包含 602 个 task spec / episode，共 10,618 条 query，其中 `CHECK_STATE` 5,835 条、`AS_OF_STATE` 3,124 条、`STATE_DIFF` 531 条、`CHECK_GOAL` 1,128 条；每个 regime 都对应 10,618 条 ground-truth answer。各 observation stream 的规模分别是 clean 5,835 条、low_confidence 5,835 条、delay 5,835 条、out_of_order 5,835 条、missing 4,686 条、conflict 6,382 条、mixed 5,143 条。因此这里的结果主要衡量两个 baseline 在 EviStateBench 查询语义下的逻辑准确性，而不是机器人控制成功率或 VLA 动作质量。

我用当前 v0 public observation streams 和 query set 做了一个设计验证实验，预测结果用项目自带 `tools/6_evaluate_answers.py` 评测。这里的数字只用于验证 baseline 设计方向，不作为最终论文结果，因为它还不是完整工程化 baseline：没有做参数调优、没有固定 dev/test split、没有加入延迟和吞吐等系统指标，也没有把 WHY_STATE 的证据评测全部展开。结果显示，Recall Memory 在 `CHECK_STATE` 这类局部状态查询上可以接近可用，但在 `AS_OF_STATE`、`STATE_DIFF` 和 mixed regime 下明显掉分；TEV + Recall Fallback 因为显式维护时态状态视图，并且只在缺证据时调用 recall 补全，在所有 regime 的 overall exact accuracy 上都高于 Recall Memory。

| Regime | Recall Memory | TEV + Recall Fallback |
| --- | ---: | ---: |
| clean | 0.778 | 0.982 |
| low_confidence | 0.696 | 0.973 |
| missing | 0.739 | 0.911 |
| conflict | 0.774 | 0.982 |
| delay | 0.778 | 0.982 |
| out_of_order | 0.773 | 0.982 |
| mixed | 0.664 | 0.905 |

从结果看，clean、delay、out_of_order 和 conflict 中 TEV-RF 都达到约 0.982，而 Recall Memory 只有约 0.77-0.78，说明只要 observation 本身没有大量缺失，显式维护 state key、valid-time interval 和 transaction-time 可见性就能稳定压过查询时检索；delay 和 out_of_order 的提升尤其说明 TEV-RF 正确利用了 `event_time` / `arrival_time` 分离，而 Recall Memory 即使检索到相关证据，也不一定能回答“系统当时知道什么”。low_confidence 中 Recall Memory 降到 0.696，TEV-RF 仍有 0.973，说明证据置信度较低时，按状态聚合和不确定性处理比 top-k 回忆更稳。missing 和 mixed 是最难的两个 regime，TEV-RF 分别是 0.911 和 0.905，低于其他 regime，原因是缺失证据会让显式 view 更容易返回 unknown，只能依赖 recall fallback 补全；但它仍明显高于 Recall Memory 的 0.739 和 0.664，说明 fallback 只能补缺口，真正贡献主要来自 temporal evidence view 对时间、冲突和状态变化的结构化维护。

下面是每个 regime 的一个具体数据案例，用来说明为什么 TEV-RF 更好：

| Regime | 具体案例 | 分析 |
| --- | --- | --- |
| clean | `adding_chemicals_to_hot_tub` 中的 `STATE_DIFF(t1=0, t2=10)`，关键状态是 `contains(hot_tub.n.02_1, chlorine.n.01_1)`，observation 为 `event_time=10, arrival_time=10, value=true, confidence=1.0`。ground truth 认为该状态从 `false -> true`，属于 `added_states`。 | Recall Memory 对 `t1` 和 `t2` 分别检索，容易只看到 t2 附近的 true 证据，却没有维护“t=0 时尚未成立”的区间语义，因此漏掉 diff；TEV-RF 维护状态时间线，所以能判断这是一个新增状态。 |
| low_confidence | `adding_chemicals_to_lawn` 中的 `AS_OF_STATE(covered(lawn.n.01_1, herbicide.n.01_1), valid_time=15, transaction_time=45)`，observation 为 `value=true, confidence=0.556378`。ground truth 是 `value=true, status=uncertain`。 | Recall Memory 会把检索到的 top evidence 汇总成 `known`，置信度被过度放大；TEV-RF 保留 observation-level confidence，并把低置信证据传递到 state view，因此输出 `uncertain` 更符合评估语义。 |
| missing | `assembling_gift_baskets` 中的 `AS_OF_STATE(inside(bow..., wicker_basket...), valid_time=10, transaction_time=9.9)`，missing stream 中该 state 没有可用 observation，ground truth 是 `unknown`。 | Recall Memory 可能检索到同一 episode 中其他 `inside(...)` 相关片段，并错误推成 `known=true`；TEV-RF 按 exact state key 和 transaction-time 可见性维护证据，没有对应证据时返回 `unknown`，避免用语义相似但状态实例不同的记忆误补。 |
| conflict | `adding_chemicals_to_lawn` 中的 `STATE_DIFF(t1=0, t2=15)`，关键状态包括 `covered(lawn, fertilizer)` 和 `covered(lawn, herbicide)`；其中 `covered(lawn, fertilizer)` 同一 `event_time=10` 同时有 `sim_state_sensor: true, confidence=1.0` 和 `rgb_relation_detector: false, confidence=0.65`。ground truth 的 diff 仍需要识别 `covered(lawn, fertilizer)` 与 `covered(lawn, herbicide)` 从 `false -> true`。 | Recall Memory 面对 support/contradict 混杂证据时容易只做局部冲突或漏掉 episode-level diff；TEV-RF 把冲突证据挂到对应 state bucket，同时仍维护状态变化区间，所以既能保留 contradict evidence，又能回答哪些任务状态发生了变化。 |
| delay | `adding_chemicals_to_hot_tub` 中的 `AS_OF_STATE(contains(hot_tub, chlorine), valid_time=10, transaction_time=9.9)`，delay stream 中该 observation 是 `event_time=10, arrival_time=15, value=true`。ground truth 是 `unknown`。 | Recall Memory 只看到这个状态最终有 true 证据，容易忽略当时还没到达；TEV-RF 显式区分 `event_time` 和 `arrival_time`，在 `transaction_time=9.9` 不会使用 `arrival_time=15` 的迟到证据，因此返回 `unknown`。 |
| out_of_order | 同一状态 `contains(hot_tub, chlorine)` 在 out_of_order stream 中为 `event_time=10, arrival_time=21.549212, value=true`，对应 `AS_OF_STATE(valid_time=10, transaction_time=9.9)` 的 ground truth 仍是 `unknown`。 | Recall Memory 把历史 observation 当作无版本记忆，可能检索到后到达的 true 证据；TEV-RF 使用 transaction-time 截断，只允许使用当时已经到达的证据，因此不会被乱序到达的未来证据污染。 |
| mixed | `bottling_wine` 中的 `CHECK_STATE(filled(wine_bottle..., red_wine), valid_time=15)`，mixed stream 同一状态有 `sim_state_sensor: true, confidence=0.623059` 和 `rgb_relation_detector: false, confidence=0.65`。ground truth 是 `value=true`。 | Recall Memory 容易被稍高置信度的 false detector 证据带偏，输出 `false`；TEV-RF 按 state key 聚合证据，并结合 source reliability / temporal evidence view 保留支持与反驳关系，因此能在 mixed 噪声和冲突下仍输出正确状态。 |

核心结论可以写成：从主流 VLA 迁移来的 recall-memory baseline 能模拟“记忆检索 + 语言推理”的能力，但 retrieval 不是 temporal view maintenance；TEV + Recall Fallback 把 recall 变成缺失证据时的补充模块，因此在保留 VLA-style memory 优点的同时，显著提升了时态查询、乱序/迟到修复和冲突证据处理能力。
