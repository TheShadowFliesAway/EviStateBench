# EviStateBench Query Templates v0

本文件基于：

```text
reports/bddl_task_audit.md
reports/task_space_v0.md
evistatebench/schema.py
```

目标是定义第一版 benchmark 要问哪些问题。这里先设计 query template，不急着写查询执行代码。查询设计清楚后，再反推 public answer schema、ground-truth answer generator、baseline，以及 EviStateDB 内部的 `TemporalStateView` 语义。

## 1. 设计原则

EviStateBench 的 query 不是通用数据库 API，而是机器人任务执行中会真实需要的 task-state question。

v0 查询必须满足：

```text
1. 来自 BEHAVIOR/BDDL task family 和 predicate taxonomy。
2. 能评测 temporal task-state view maintenance。
3. 能暴露 noisy / delayed / out-of-order / missing / conflicting observation 的影响。
4. 能区分只做 latest observation、log scan、retrieval memory 和 materialized temporal view 的方法。
5. 能回答机器人任务执行中的具体问题，而不是为了接口完整而堆函数。
```

v0 先聚焦 5 类 query：

```text
CHECK_STATE
AS_OF_STATE
STATE_DIFF
WHY_STATE
CHECK_GOAL
```

后续再扩展：

```text
CHECK_PRECONDITION
FIND_UNCERTAIN_STATES
FAILURE_LOCALIZATION
```

## 2. 共同输入约定

所有 query 至少需要 episode 语境。

```text
episode_id
task_id
```

状态实例统一用：

```text
predicate_name
arguments
```

不要写死成 subject/object/location，因为 v0 已经包含：

```text
open(cabinet)
inside(cup, cabinet)
covered(table, dust)
filled(cup, water)
attached(bulb, socket)
```

时间分两类：

```text
valid_time: 查询世界中某个状态在什么事件时间成立
transaction_time: 查询系统在某个接收/维护版本下知道什么
```

`CHECK_STATE` 和 `WHY_STATE` 默认只需要 valid_time；`AS_OF_STATE` 必须同时指定 valid_time 和 transaction_time。

## 3. 共同输出约定

v0 query answer 不只是返回 true/false。至少要包含：

```text
value
confidence
status
```

其中：

```text
value: true / false / categorical / numeric
confidence: 系统维护出的状态置信度，不是单条 observation 的置信度
status: known / unknown / uncertain / conflict
```

涉及证据或审计时，需要返回：

```text
support_observations
contradict_observations
evidence_refs
revision_history
```

v0 暂不强制自然语言解释。`WHY_STATE` 的核心是 evidence provenance，不是生成一段解释文本。

## 4. CHECK_STATE

### 4.1 目的

回答某个状态在某个时间是否成立。

机器人任务意义：

```text
当前杯子是否在柜子里？
毛巾是否已经折叠？
炉子是否打开？
工具是否仍被污渍覆盖？
零件是否已经安装到位？
```

### 4.2 输入

```text
CHECK_STATE(
  episode_id,
  task_id,
  predicate_name,
  arguments,
  valid_time
)
```

### 4.3 输出

```text
StateAnswer(
  value,
  confidence,
  status,
  valid_interval,
  transaction_time,
  state_id
)
```

字段含义：

```text
value: 该状态在 valid_time 的维护判断
confidence: 融合后的状态置信度
status: known / unknown / uncertain / conflict
valid_interval: 该判断覆盖的有效时间区间
transaction_time: 系统当前知识版本
state_id: 可选字段；如果系统内部维护 state/view id，可以返回被命中的内部 id
```

### 4.4 v0 Predicate 绑定

| task family | query examples |
| --- | --- |
| storage / organization / packing | `CHECK_STATE(inside(cloth, drawer), t)`, `CHECK_STATE(folded(cloth), t)`, `CHECK_STATE(open(cabinet), t)` |
| cleaning / washing | `CHECK_STATE(covered(tool, dirt), t)`, `CHECK_STATE(saturated(cloth, water), t)` |
| cooking / food preparation | `CHECK_STATE(cooked(food), t)`, `CHECK_STATE(hot(food), t)`, `CHECK_STATE(contains(container, ingredient), t)` |
| liquid / material transfer | `CHECK_STATE(filled(cup, water), t)`, `CHECK_STATE(contains(pool, chlorine), t)` |
| assembly / setup | `CHECK_STATE(attached(part, base), t)`, `CHECK_STATE(toggled_on(device), t)` |

### 4.5 对 EviStateDB 内部视图语义的要求

```text
predicate_name
arguments
value
valid_start
valid_end
transaction_start
transaction_end
confidence
status
```

## 5. AS_OF_STATE

### 5.1 目的

回答在某个系统知识版本下，某个有效时间的状态判断。

机器人任务意义：

```text
系统在 t_tx 当时，以为 t_valid 发生了什么？
后来迟到的 observation 是否改变了历史判断？
out-of-order observation 是否触发了 repair？
```

这个 query 是 EviStateBench 区别于普通 state tracking benchmark 的关键之一。

### 5.2 输入

```text
AS_OF_STATE(
  episode_id,
  task_id,
  predicate_name,
  arguments,
  valid_time,
  transaction_time
)
```

### 5.3 输出

```text
StateAnswer(
  value,
  confidence,
  status,
  valid_interval,
  transaction_interval,
  state_id
)
```

### 5.4 示例

```text
AS_OF_STATE(
  predicate_name="inside",
  arguments=("cup_1", "cabinet_1"),
  valid_time=10.0,
  transaction_time=12.0
)
```

含义：

```text
问系统在 transaction_time=12.0 这个知识版本下，
对 valid_time=10.0 时 cup 是否在 cabinet 里的判断。
```

如果后来 transaction_time=20.0 到达一条迟到证据，新的 AS_OF 结果可能不同。

### 5.5 重点扰动

```text
delayed observations
out-of-order observations
late correction
missing observations
```

### 5.6 对 EviStateDB 内部视图语义的要求

```text
valid_start
valid_end
transaction_start
transaction_end
revision_history
```

## 6. STATE_DIFF

### 6.1 目的

回答一个任务范围内，两个时间点之间哪些状态发生了变化。

机器人任务意义：

```text
刚刚执行动作后，场景到底变了什么？
失败前后哪些状态偏离目标？
恢复任务时，需要把哪些状态恢复到之前？
```

### 6.2 输入

```text
STATE_DIFF(
  episode_id,
  task_id,
  scope,
  t1,
  t2,
  predicate_filter = optional
)
```

`scope` 可以是：

```text
task
room
object_set
predicate_category
```

### 6.3 输出

```text
StateDiffAnswer(
  changed_states,
  added_states,
  removed_states,
  unchanged_but_uncertain_states
)
```

每个 changed state 至少包含：

```text
predicate_name
arguments
value_at_t1
value_at_t2
confidence_at_t1
confidence_at_t2
support_observations
contradict_observations
```

### 6.4 v0 Predicate 绑定

| task family | diff focus |
| --- | --- |
| storage / organization / packing | `inside`, `ontop`, `folded`, `open` |
| cleaning / washing | `covered`, `saturated`, `inside` |
| cooking / food preparation | `cooked`, `hot`, `contains`, `filled` |
| liquid / material transfer | `filled`, `contains`, `covered` |
| assembly / setup | `attached`, `toggled_on`, `touching`, `under` |

### 6.5 对 EviStateDB 内部视图语义的要求

```text
time-indexed state lookup
valid intervals
confidence at time
support / contradict evidence around t1 and t2
```

## 7. WHY_STATE

### 7.1 目的

回答系统为什么相信某个状态判断。

机器人任务意义：

```text
为什么系统认为杯子已经在柜子里？
为什么系统认为桌子还被污渍覆盖？
为什么系统认为灯泡已经安装好？
是否存在反驳证据？
```

WHY_STATE 是 EviStateBench 的 provenance query，不是自然语言解释任务。

### 7.2 输入

```text
WHY_STATE(
  episode_id,
  task_id,
  predicate_name,
  arguments,
  valid_time,
  transaction_time = optional
)
```

如果没有给 `transaction_time`，默认使用当前系统版本。

### 7.3 输出

```text
WhyStateAnswer(
  value,
  confidence,
  status,
  support_observations,
  contradict_observations,
  evidence_refs,
  confidence_trace,
  revision_history
)
```

字段含义：

```text
support_observations: 支持当前 value 的 observation ids
contradict_observations: 反驳当前 value 的 observation ids
evidence_refs: frame / simulator state / action log / annotation 指针
confidence_trace: 置信度如何被不同 observation 改变
revision_history: 是否因为迟到证据修正过历史判断
```

### 7.4 示例

```text
WHY_STATE(
  predicate_name="covered",
  arguments=("table_1", "dust_1"),
  valid_time=18.0
)
```

可能返回：

```text
value = false
confidence = 0.82
support = [obs_rgb_18, obs_sim_18]
contradict = [obs_vlm_17]
evidence_refs = ["frame_0018", "sim_state_18", "vlm_output_17"]
```

### 7.5 重点扰动

```text
noisy observations
conflicting observations
late correction
source disagreement
```

### 7.6 对 EviStateDB 内部视图语义的要求

```text
support_observations
contradict_observations
confidence
revision_history
source metadata
```

## 8. CHECK_GOAL

### 8.1 目的

回答某个任务在某个时间是否满足目标条件。

机器人任务意义：

```text
任务是否完成？
哪些 goal predicate 已满足？
哪些还没满足？
哪些因为证据不足或冲突而不确定？
```

CHECK_GOAL 是 task-derived view，不是单个 predicate query。

### 8.2 输入

```text
CHECK_GOAL(
  episode_id,
  task_id,
  valid_time,
  transaction_time = optional
)
```

### 8.3 输出

```text
GoalAnswer(
  satisfied,
  confidence,
  satisfied_predicates,
  violated_predicates,
  uncertain_predicates,
  supporting_evidence,
  contradicting_evidence
)
```

字段含义：

```text
satisfied: 整个任务目标是否满足
confidence: 对目标满足判断的整体置信度
satisfied_predicates: 已满足的 goal predicate instances
violated_predicates: 未满足的 goal predicate instances
uncertain_predicates: 证据不足或冲突的 goal predicate instances
supporting_evidence: 支持目标满足的 observation ids
contradicting_evidence: 反驳目标满足的 observation ids
```

### 8.4 示例

Storage 任务：

```text
goal:
  inside(plate_1, cabinet_1)
  inside(plate_2, cabinet_1)
  not open(cabinet_1)
```

查询：

```text
CHECK_GOAL(task_id="putting_dishes_away_after_cleaning", valid_time=30.0)
```

可能回答：

```text
satisfied = false
satisfied_predicates = [inside(plate_1, cabinet_1)]
violated_predicates = [open(cabinet_1)]
uncertain_predicates = [inside(plate_2, cabinet_1)]
```

### 8.5 v0 Task Family 绑定

| task family | goal focus |
| --- | --- |
| cleaning / washing | objects no longer `covered`, relevant objects `inside` target containers |
| cooking / food preparation | food `cooked`, container `contains` ingredients, container `filled` |
| storage / organization / packing | objects `inside` containers, objects `ontop` target surfaces, containers `open=false` |
| liquid / material transfer | containers `filled`, containers `contains` substance |
| assembly / setup | parts `attached`, devices `toggled_on`, objects `ontop/under` target places |

### 8.6 对 EviStateDB 内部视图语义的要求

```text
goal predicate instances
state lookup for each goal predicate
aggregation rule over satisfied / violated / uncertain predicates
evidence aggregation
transaction-time aware goal evaluation
```

## 9. v0 Query Coverage Matrix

| query | main capability | temporal semantics | evidence/provenance | task-derived | first metrics |
| --- | --- | --- | --- | --- | --- |
| CHECK_STATE | point state lookup | valid_time | optional | no | state accuracy |
| AS_OF_STATE | bitemporal lookup | valid_time + transaction_time | optional | no | late repair accuracy |
| STATE_DIFF | change detection | valid_time interval | optional | no | diff precision / recall |
| WHY_STATE | evidence query | valid_time + optional transaction_time | required | no | evidence precision / recall |
| CHECK_GOAL | task goal evaluation | valid_time + optional transaction_time | required | yes | goal satisfaction accuracy |

## 10. 对 EviStateDB 内部 TemporalStateView 语义的直接约束

Query templates 反推出 EviStateDB 内部 TemporalStateView 至少需要：

```text
state_id
episode_id
task_id
predicate_name
arguments
value
valid_start
valid_end
transaction_start
transaction_end
confidence
status
support_observation_ids
contradict_observation_ids
revision_history
metadata
```

其中：

```text
CHECK_STATE 需要 value / confidence / valid interval
AS_OF_STATE 需要 transaction interval
STATE_DIFF 需要按时间比较多个 state view
WHY_STATE 需要 support / contradict / revision history
CHECK_GOAL 需要 goal predicate instances 和 task-level aggregation
```

## 11. 暂缓到 v1 的 Query

### CHECK_PRECONDITION

需要 action schema 和 action precondition 来源。BDDL task goal 不能直接提供完整 action-level precondition。

### FIND_UNCERTAIN_STATES

需要先确定 uncertainty 的定义：

```text
low confidence
high conflict
missing evidence
stale observation
```

### FAILURE_LOCALIZATION

需要 episode failure label、action trace 或 goal failure point。仅靠 BDDL task definition 不够。

## 12. 当前结论

v0 query templates 可以支撑下一步定义：

```text
Query schema:
  StateQuery
  AsOfStateQuery
  StateDiffQuery
  WhyStateQuery
  GoalQuery

Answer schema:
  StateAnswer
  StateDiffAnswer
  WhyStateAnswer
  GoalAnswer

View schema:
  TemporalStateView
  GoalView
```

下一步建议先写 Python public query/answer schema，再写 EviStateDB 内部 TemporalStateView schema。这样代码会由 benchmark workload 反推，而不是为了存储而存储。
