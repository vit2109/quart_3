"""Тесты исполнения NL-плана без LLM."""

from __future__ import annotations

import polars as pl

from application.use_cases.ai.nl_query_service import AggSpec, FilterSpec, NLQueryPlan, NLQueryService


def test_execute_plan_group_sum():
    df = pl.DataFrame(
        {
            "region": ["East", "East", "West", "West"],
            "amount": [100, 50, 200, 300],
        }
    )
    plan = NLQueryPlan(
        group_by=["region"],
        aggregations=[AggSpec(column="amount", agg="sum", alias="total")],
        sort_by="total",
        sort_dir="desc",
        limit=10,
    )
    result = NLQueryService()._execute_plan(df, plan)
    assert result.height == 2
    assert result["total"][0] == 500


def test_execute_plan_filter():
    df = pl.DataFrame({"region": ["East", "West"], "amount": [10, 20]})
    plan = NLQueryPlan(
        filters=[FilterSpec(column="region", op="eq", value="East")],
        limit=10,
    )
    result = NLQueryService()._execute_plan(df, plan)
    assert result.height == 1
    assert result["region"][0] == "East"
