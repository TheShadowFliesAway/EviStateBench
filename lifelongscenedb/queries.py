from __future__ import annotations

from typing import Any

from .schema import Fact, QueryResult


def match_object(object_desc: str, subject: str) -> bool:
    lhs = object_desc.lower()
    rhs = subject.lower()
    return lhs == rhs or lhs in rhs


def choose_best(facts: list[Fact]) -> Fact | None:
    """从候选 facts 中选出最可信、最新的一条。

    排序优先级依次是：
    1. active 状态优先；
    2. confidence 越高越优先；
    3. valid_start 越新越优先；
    4. last_updated 越新越优先。
    """

    if not facts:
        return None
    return sorted(
        facts,
        # reverse=True 表示下面这个 tuple 的值越大，排序越靠前。
        key=lambda f: (f.status == "active", f.confidence, f.valid_start, f.last_updated),
        reverse=True,
    )[0]


def result_from_fact(fact: Fact, time: float | None, alternatives: list[Fact]) -> QueryResult:
    """把内部 Fact 转成对外返回的 QueryResult。

    fact 是最终选中的最佳事实；alternatives 是同一次查询里的其他候选事实，
    用于让调用方看到备选位置、置信度和状态，从而理解结果的不确定性。
    """

    # 将除最佳 fact 自己以外的候选事实转成简化字典，作为备选答案返回。
    alt_rows = [
        {
            "object_id": alt.subject,
            "location": alt.location,
            "confidence": alt.confidence,
            "status": alt.status,
            "valid_start": alt.valid_start,
            "valid_end": alt.valid_end,
        }
        for alt in alternatives
        if alt.fact_id != fact.fact_id
    ]
    return QueryResult(
        object_id=fact.subject,
        location=fact.location,
        confidence=fact.confidence,
        time=time,
        # evidence 保存支持最佳 fact 的 observation id，便于后续溯源。
        evidence=list(fact.supporting_obs_ids),
        alternatives=alt_rows,
        # metadata 保存内部事实信息，方便调试和评估，但不直接作为主答案字段。
        metadata={
            "fact_id": fact.fact_id,
            "predicate": fact.predicate,
            "object": fact.object,
            "status": fact.status,
            "valid_start": fact.valid_start,
            "valid_end": fact.valid_end,
        },
    )


def fact_claim_matches(fact: Fact, subject: str, predicate: str, object_: str) -> bool:
    return fact.subject == subject and fact.predicate == predicate and fact.object == object_


def row_location(row: dict[str, Any] | QueryResult | None) -> str | None:
    if row is None:
        return None
    if isinstance(row, QueryResult):
        return row.location
    return row.get("location")
