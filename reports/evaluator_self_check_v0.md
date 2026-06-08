# Evaluation Report v0

本报告由 `tools/evaluate_answers.py` 生成。

它对应最小验证计划的第 7 步：

```text
predicted answers + ground-truth answers -> evaluation metrics
```

## Summary

| name | ground truth | predictions | coverage | exact accuracy | confidence MAE | diff F1 | goal predicate F1 | missing | extra |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clean` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |
| `conflict` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |
| `delay` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |
| `low_confidence` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |
| `missing` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |
| `mixed` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |
| `out_of_order` | 10618 | 10618 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0 | 0 |

## Query-Type Metrics

### clean

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

### conflict

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

### delay

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

### low_confidence

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

### missing

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

### mixed

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

### out_of_order

| query_type | total | coverage | exact accuracy | value accuracy | status accuracy | satisfied accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AS_OF_STATE` | 3124 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `CHECK_GOAL` | 1128 | 1.0000 | 1.0000 | n/a | 1.0000 | 1.0000 |
| `CHECK_STATE` | 5835 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a |
| `STATE_DIFF` | 531 | 1.0000 | 1.0000 | n/a | n/a | n/a |

## Notes

- `exact_accuracy` 以 ground-truth answer 总数为分母，missing prediction 算错。
- `coverage` 表示 predicted answers 覆盖了多少 ground-truth query_id。
- `STATE_DIFF` 使用 change-set exact match 和 mean F1。
- `CHECK_GOAL` 除整体 satisfied/status 外，也计算 goal predicate set F1。
