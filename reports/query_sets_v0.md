# Query Set v0

本报告由 `tools/build_query_sets.py` 生成。

它对应最小验证计划的第 5 步：

```text
生成 CHECK_STATE / AS_OF_STATE / STATE_DIFF / CHECK_GOAL query set
```

这里生成的是 public query set，不包含标准答案。标准答案会在 Step 6 中由 hidden timeline / oracle 生成。

## 配置

| item | value |
| --- | --- |
| input timeline events | `/root/autodl-tmp/EviStateBench/data/synthetic_ground_truth_timelines_v0.jsonl` |
| input goal predicate instances | `/root/autodl-tmp/EviStateBench/data/task_predicate_instances_v0.jsonl` |
| output query set | `/root/autodl-tmp/EviStateBench/data/query_sets_v0/queries.jsonl` |
| manifest | `/root/autodl-tmp/EviStateBench/data/query_sets_v0/manifest.json` |
| AS_OF before gap | 0.1 |
| AS_OF after gap | 30 |

## 总览

| item | count |
| --- | ---: |
| timeline events | 5835 |
| task files with goal specs | 597 |
| normalized goal states | 1581 |
| queries | 10618 |

## Query Types

| item | count |
| --- | ---: |
| `CHECK_STATE` | 5835 |
| `AS_OF_STATE` | 3124 |
| `CHECK_GOAL` | 1128 |
| `STATE_DIFF` | 531 |

## Task Families

| item | count |
| --- | ---: |
| `cleaning / washing` | 2809 |
| `cooking / food preparation` | 1421 |
| `storage / organization / packing` | 1304 |
| `liquid / material transfer` | 204 |
| `assembly / setup` | 97 |

## Sample Queries

| query_type | query_id | episode | state/scope | time |
| --- | --- | --- | --- | --- |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00001` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `filled(chlorine__bottle.n.01_1, chlorine.n.01_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00002` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `filled(hot_tub.n.02_1, water.n.06_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00003` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `ontop(chlorine__bottle.n.01_1, floor.n.01_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00004` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `ontop(hot_tub.n.02_1, floor.n.01_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_check_state_00005` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `contains(hot_tub.n.02_1, chlorine.n.01_1)` | valid=10.0 |
| `AS_OF_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_asof_before_00005` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `contains(hot_tub.n.02_1, chlorine.n.01_1)` | valid=10.0, tx=9.9 |
| `AS_OF_STATE` | `syn_v0__adding_chemicals_to_hot_tub__problem0__q_asof_after_00005` | `syn_v0__adding_chemicals_to_hot_tub__problem0` | `contains(hot_tub.n.02_1, chlorine.n.01_1)` | valid=10.0, tx=40.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00006` | `syn_v0__adding_chemicals_to_lawn__problem0` | `filled(herbicide__bottle.n.01_1, herbicide.n.01_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00007` | `syn_v0__adding_chemicals_to_lawn__problem0` | `ontop(fertilizer__atomizer.n.01_1, floor.n.01_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00008` | `syn_v0__adding_chemicals_to_lawn__problem0` | `ontop(herbicide__bottle.n.01_1, floor.n.01_1)` | valid=0.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00009` | `syn_v0__adding_chemicals_to_lawn__problem0` | `covered(lawn.n.01_1, fertilizer.n.01_1)` | valid=10.0 |
| `AS_OF_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_before_00009` | `syn_v0__adding_chemicals_to_lawn__problem0` | `covered(lawn.n.01_1, fertilizer.n.01_1)` | valid=10.0, tx=9.9 |
| `AS_OF_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_after_00009` | `syn_v0__adding_chemicals_to_lawn__problem0` | `covered(lawn.n.01_1, fertilizer.n.01_1)` | valid=10.0, tx=40.0 |
| `CHECK_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_check_state_00010` | `syn_v0__adding_chemicals_to_lawn__problem0` | `covered(lawn.n.01_1, herbicide.n.01_1)` | valid=15.0 |
| `AS_OF_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_before_00010` | `syn_v0__adding_chemicals_to_lawn__problem0` | `covered(lawn.n.01_1, herbicide.n.01_1)` | valid=15.0, tx=14.9 |
| `AS_OF_STATE` | `syn_v0__adding_chemicals_to_lawn__problem0__q_asof_after_00010` | `syn_v0__adding_chemicals_to_lawn__problem0` | `covered(lawn.n.01_1, herbicide.n.01_1)` | valid=15.0, tx=45.0 |

## 生成规则

1. 每条 hidden timeline event 生成一个 `CHECK_STATE` query。
2. 每条非 `init_assert` event 生成两个 `AS_OF_STATE` query：一个 transaction_time 在事件前，一个在事件后。
3. 每个 final_time > 0 的 episode 生成一个 `STATE_DIFF(scope=task, t1=0, t2=final_time)` query。
4. 每个有 BDDL goal specs 的 episode 生成 `CHECK_GOAL(t=0)`；如果 final_time > 0，再生成 `CHECK_GOAL(t=final_time)`。
5. `CHECK_GOAL` query 的 metadata 中包含 goal predicate specs。这是任务规格，不是答案；系统需要知道目标条件才能判断任务是否完成。

## 边界

这个 query set 可以和 clean / perturbed observation streams 配套使用。

`AS_OF_STATE` 的标准答案在 Step 6 里要特别小心：如果评测的是 bitemporal information availability，它可能需要按不同 observation stream 的 arrival_time 分别生成；如果评测的是 pure world truth，则只依赖 hidden timeline。第一版 oracle 需要明确采用哪一种语义。

v0 暂时没有生成 `WHY_STATE` query，因为 WHY 的 evidence correctness metric 需要单独定义。
