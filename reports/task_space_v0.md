# EviStateBench Task Space v0

本文件基于 `reports/bddl_task_audit.md`，完成两个 Phase 1 设计决策：

```text
1. 确认 predicate taxonomy v0
2. 选择 representative task families v0
```

这里的 v0 只代表第一版 benchmark 的任务状态空间，不代表最终边界。BEHAVIOR/BDDL 是 grounding，后续还需要结合 OmniGibson runtime object states、action logs、simulator sensors 和真实视频 annotation 扩展。

## 1. Predicate Taxonomy v0

### 1.1 分类原则

Predicate 分类不是为了复述 BDDL domain，而是为了决定 EviStateBench 要维护哪些 temporal task-state views。

分类时区分三类东西：

```text
core state predicate: 第一版 benchmark 可以直接围绕它生成 observation、state view 和 query。
context / metadata: 对任务有用，但不一定作为核心 query target。
runtime extension: BDDL domain 有或机器人任务需要，但不能只靠 BDDL init/goal 得到。
```

### 1.2 最终分类表

| predicate | category | init | goal | total | decision |
| --- | --- | ---: | ---: | ---: | --- |
| `future` | BDDL bookkeeping/source marker | 339 | 0 | 339 | metadata / exclude from core state queries |
| `insource` | BDDL bookkeeping/source marker | 442 | 0 | 442 | metadata / exclude from core state queries |
| `real` | BDDL bookkeeping/source marker | 0 | 363 | 363 | metadata / exclude from core state queries |
| `attached` | contact/configuration relation | 42 | 67 | 109 | core v0 state predicate |
| `draped` | contact/configuration relation | 8 | 30 | 38 | core v0 state predicate |
| `touching` | contact/configuration relation | 0 | 22 | 22 | core v0 state predicate |
| `contains` | containment/content relation | 0 | 248 | 248 | core v0 state predicate |
| `inside` | containment/content relation | 1889 | 781 | 2670 | core v0 state predicate |
| `covered` | material/particle state | 777 | 713 | 1490 | core v0 state predicate |
| `filled` | material/particle state | 638 | 55 | 693 | core v0 state predicate |
| `saturated` | material/particle state | 9 | 14 | 23 | core v0 state predicate |
| `broken` | object unary state | 3 | 3 | 6 | core v0 state predicate |
| `cooked` | object unary state | 315 | 116 | 431 | core v0 state predicate |
| `folded` | object unary state | 0 | 60 | 60 | core v0 state predicate |
| `frozen` | object unary state | 58 | 19 | 77 | core v0 state predicate |
| `hot` | object unary state | 19 | 17 | 36 | core v0 state predicate |
| `on_fire` | object unary state | 0 | 2 | 2 | core v0 state predicate |
| `open` | object unary state | 18 | 36 | 54 | core v0 state predicate |
| `toggled_on` | object unary state | 29 | 12 | 41 | core v0 state predicate |
| `unfolded` | object unary state | 13 | 3 | 16 | core v0 state predicate |
| `nextto` | placement/spatial relation | 0 | 166 | 166 | core v0 state predicate |
| `ontop` | placement/spatial relation | 4776 | 557 | 5333 | core v0 state predicate |
| `overlaid` | placement/spatial relation | 1 | 25 | 26 | core v0 state predicate |
| `under` | placement/spatial relation | 1 | 8 | 9 | core v0 state predicate |
| `grasped` | runtime robot interaction | 0 | 0 | 0 | runtime extension, not BDDL-only v0 |
| `inroom` | scene/localization context | 3207 | 0 | 3207 | context + scope, optional query state |

### 1.3 v0 Core Categories

#### Object Unary State

```text
cooked, frozen, open, folded, unfolded, toggled_on, hot, on_fire, broken
```

含义：单个对象自身的状态。

代表查询：

```text
CHECK_STATE(open(cabinet), t)
AS_OF_STATE(cooked(food), valid_time, transaction_time)
WHY_STATE(folded(towel), t)
```

优先级：

```text
high: cooked, open, folded, frozen, hot, toggled_on
low-frequency but retained: broken, on_fire, unfolded
```

#### Placement / Spatial Relation

```text
ontop, nextto, under, overlaid
```

含义：对象之间的空间放置、邻近或覆盖关系。

代表查询：

```text
CHECK_STATE(ontop(plate, table), t)
STATE_DIFF(scope, t1, t2)
WHY_STATE(nextto(item_a, item_b), t)
```

`ontop` 是 BDDL 中最高频 predicate，是 v0 必选。

#### Containment / Content Relation

```text
inside, contains
```

含义：物体是否在容器内，或容器是否包含某个对象/内容。

代表查询：

```text
CHECK_GOAL(task_id, t)
CHECK_STATE(inside(cup, cabinet), t)
WHY_STATE(contains(container, substance), t)
```

`inside` 是 goal 中最高频的状态之一，必须作为核心。

#### Material / Particle State

```text
covered, filled, saturated
```

含义：物体或容器与液体、粉末、污渍、化学品等物质相关的状态。

代表查询：

```text
CHECK_STATE(covered(object, substance), t)
CHECK_STATE(filled(container, substance), t)
WHY_STATE(saturated(cloth, water), t)
```

这一类是 EviStateBench 区别于简单 scene graph / object location benchmark 的关键之一。

#### Contact / Configuration Relation

```text
attached, draped, touching
```

含义：对象之间的接触、连接、悬挂或装配关系。

代表查询：

```text
CHECK_PRECONDITION(action_id, t)
CHECK_STATE(attached(part, base), t)
STATE_DIFF(scope, t1, t2)
```

这一类在总量上不如 `inside/ontop/covered` 高频，但对 assembly/setup 任务非常重要。

### 1.4 不进入核心状态查询的 Predicate

#### BDDL Bookkeeping / Source Marker

```text
real, future, insource
```

这几个 predicate 更像 BDDL 的存在性、未来对象或来源标记。它们可以作为 metadata 或 data-generation signal，但不作为 EviStateBench v0 的核心 task-state query target。

保留方式：

```text
real / future: 可辅助理解 object lifecycle，但不生成主实验 query。
insource: 可辅助构造 material/source relation，但不直接当作 maintained state view。
```

#### Scene Context

```text
inroom
```

`inroom` 在 init 中极高频，但 goal 中没有出现。它更适合做 task scope、scene context 或 index key。

保留方式：

```text
作为 context: object belongs to room / task scene scope
作为可选 query: FIND_OBJECT_SCOPE / CHECK_CONTEXT
第一版不把它作为主要 correctness metric
```

#### Runtime Robot Interaction

```text
grasped
```

`grasped` 在 domain 中存在，但在 1016 个 BDDL task 的 init/goal 中没有出现。因此它不能由 BDDL-only audit 支撑。

保留方式：

```text
v0 BDDL-only benchmark: 不作为核心 predicate
v1 runtime benchmark: 从 OmniGibson action log / robot state / simulator sensor 中抽取
```

这一点很重要：robot interaction state 是 EviStateBench 需要的，但来源应是 runtime observation，不是 BDDL task definition。

## 2. Representative Task Families v0

### 2.1 选择原则

v0 task family 选择不按数量简单排序，而按状态类型覆盖来选。

选择标准：

```text
1. 能覆盖高频 predicate。
2. 能覆盖不同 state category。
3. 能自然产生 CHECK / AS_OF / DIFF / WHY / GOAL queries。
4. 能体现 noisy / delayed / missing / conflicting observation 对任务状态维护的影响。
5. 不把 benchmark 限制成单一 inside/ontop 任务。
```

### 2.2 最终选择

v0 选择 5 类 representative task families：

```text
cleaning / washing
cooking / food preparation
storage / organization / packing
liquid / material transfer
assembly / setup
```

### 2.3 Family 详情

| family | task count | selected role | core predicates | why included |
| --- | ---: | --- | --- | --- |
| cleaning / washing | 321 | material/object state family | `covered`, `inside`, `ontop`, `saturated` | 覆盖清洁、污渍、覆盖、饱和等物质状态，是第一版必须保留的大类 |
| cooking / food preparation | 110 | unary state + content family | `cooked`, `covered`, `contains`, `inside`, `filled`, `hot` | 覆盖烹饪状态、内容关系、容器关系和目标满足 |
| storage / organization / packing | 129 | containment/spatial family | `inside`, `ontop`, `nextto`, `folded`, `open`, `attached` | 覆盖放置、收纳、整理、容器状态，是最自然的 temporal state maintenance 场景 |
| liquid / material transfer | 27 | material transfer family | `filled`, `covered`, `contains`, `inside`, `saturated` | 数量不大，但专门覆盖液体/物质转移，能暴露 observation uncertainty 和 source/content 语义 |
| assembly / setup | 15 | configuration/contact family | `attached`, `toggled_on`, `ontop`, `under`, `inside` | 数量小但状态类型独特，覆盖装配、连接、开关和配置关系 |

### 2.4 每类建议代表任务

这些不是最终 benchmark task list，只是 v0 选样时优先检查的候选。

#### Cleaning / Washing

候选任务：

```text
putting_clean_laundry_away
clean_a_company_office
cleaning_garden_tools
cleaning_up_refrigerator
cleaning_sneakers
```

适合覆盖：

```text
covered(object, substance)
saturated(object, substance)
inside(object, container)
folded(cloth)
ontop(object, surface)
```

任务意义：

```text
清洁类任务非常适合做 WHY_STATE，因为 covered / saturated 这类状态容易出现感知噪声和证据冲突。
```

#### Cooking / Food Preparation

候选任务：

```text
cook_lamb
cook_shrimp
canning_food
prepare_wine_and_cheese
cooking_lunch
```

适合覆盖：

```text
cooked(food)
hot(food/container)
contains(container, content)
inside(object, container)
covered(object, substance)
filled(container, substance)
```

任务意义：

```text
烹饪类任务适合做 CHECK_GOAL、AS_OF_STATE 和 temporal repair，因为 cooked / hot / contains 这类状态和时间变化关系更明显。
```

#### Storage / Organization / Packing

候选任务：

```text
store_baby_clothes
sorting_clothes
putting_clothes_in_storage
sorting_books_on_shelf
pack_a_beach_bag
```

适合覆盖：

```text
inside(object, container)
ontop(object, surface)
nextto(object, object)
folded(cloth)
open(container)
```

任务意义：

```text
收纳整理类任务是 CHECK_STATE / CHECK_GOAL / STATE_DIFF 的核心场景，能直接检验系统是否维护了正确的空间和容器状态。
```

#### Liquid / Material Transfer

候选任务：

```text
adding_chemicals_to_hot_tub
make_spa_water
bottling_wine
pouring_water_in_a_glass
changing_dogs_water
```

适合覆盖：

```text
filled(container, substance)
contains(container, substance)
covered(object, substance)
saturated(object, substance)
inside(object, container)
```

任务意义：

```text
液体和物质转移类任务能逼迫 schema 表达 object-object 之外的 object-substance / container-content 状态。
```

#### Assembly / Setup

候选任务：

```text
assembling_furniture
changing_light_bulbs
installing_alarms
installing_a_printer
installing_a_modem
```

适合覆盖：

```text
attached(part, base)
touching(object, object)
toggled_on(device)
ontop(object, surface)
under(object, object)
```

任务意义：

```text
装配设置类任务数量少，但对 EviStateBench 很有价值，因为它覆盖 attached / toggled_on / under 这类普通收纳任务中较少出现的状态。
```

### 2.5 暂不作为 v0 主集的 Family

#### Shopping / Acquisition

```text
task count: 42
core predicates: ontop, inside, nextto
```

暂不放入 v0 主集的原因：

```text
它主要重复 storage / organization / packing 中的空间和容器关系，
对 predicate taxonomy 的新增覆盖有限。
```

后续用途：

```text
可作为 v1 generalization split 或 held-out task family。
```

#### Other / Mixed

```text
task count: 372
```

暂不直接作为 v0 family 的原因：

```text
它不是语义干净的任务族，内部包含 clearing、decorating、composting、cooling 等混合任务。
```

后续用途：

```text
等 v0 schema/query 稳定后，从其中人工拆分出更细任务族。
```

## 3. 对后续 StateObservation Schema 的直接约束

v0 taxonomy 对 schema 有几个直接要求：

```text
predicate_name 不能只支持 subject-predicate-object 的自然语言三元组；
arguments 必须是 list/tuple，支持 unary 和 binary predicate；
observed_value 至少支持 boolean，后续扩展 categorical/numeric；
metadata 需要记录 BDDL predicate category、object type、source type 和 possible substance/content type；
evidence_ref 必须能指向 frame / simulator state / action log / annotation；
inroom 应优先作为 scope/context 字段或 index key；
real/future/insource 不作为主 query predicate；
grasped 需要从 runtime observation source 补充。
```

## 4. 对 Query Template 的直接约束

v0 query template 应该优先覆盖这些状态：

```text
CHECK_STATE(inside(object, container), t)
CHECK_STATE(covered(object, substance), t)
CHECK_STATE(cooked(food), t)
CHECK_STATE(attached(part, object), t)
AS_OF_STATE(predicate, arguments, valid_time, transaction_time)
STATE_DIFF(task_scope, t1, t2)
WHY_STATE(predicate, arguments, t)
CHECK_GOAL(task_id, t)
```

第一版不要把 query 写成泛泛接口，要给每个 query 绑定具体 task family：

```text
storage -> inside / ontop / folded / open
cleaning -> covered / saturated / inside
cooking -> cooked / hot / contains / filled
liquid transfer -> filled / contains / covered
assembly -> attached / toggled_on / touching
```

## 5. 当前结论

v0 的任务空间可以这样定：

```text
Core predicates:
  inside, contains,
  ontop, nextto, under, overlaid,
  covered, filled, saturated,
  cooked, frozen, open, folded, unfolded, toggled_on, hot, on_fire, broken,
  attached, draped, touching

Context / metadata:
  inroom, real, future, insource

Runtime extension:
  grasped

Representative families:
  cleaning / washing
  cooking / food preparation
  storage / organization / packing
  liquid / material transfer
  assembly / setup
```

这个 v0 已经足够支撑下一步：设计 StateObservation schema v0 和 query templates v0。
