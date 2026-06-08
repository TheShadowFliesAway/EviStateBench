# Public Artifact Validation v0

本报告由 `tools/8_validate_public_artifacts.py` 生成。

## Status

```text
PASS
```

## Public Directory

```text
/root/autodl-tmp/EviStateBench/data/public_v0
```

## Summary

| item | value |
| --- | ---: |
| task specs | 602 |
| query rows | 10618 |
| observation streams | 7 |
| validation errors | 0 |

## Query Counts

| query_type | count |
| --- | ---: |
| `AS_OF_STATE` | 3124 |
| `CHECK_GOAL` | 1128 |
| `CHECK_STATE` | 5835 |
| `STATE_DIFF` | 531 |

## Stream Counts

| stream | observations |
| --- | ---: |
| `clean` | 5835 |
| `conflict` | 6382 |
| `delay` | 5835 |
| `low_confidence` | 5835 |
| `missing` | 4686 |
| `mixed` | 5143 |
| `out_of_order` | 5835 |

## Manifest Version

```text
public_v0
```

## Errors

- none
