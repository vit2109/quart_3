"""Тесты построения NL-плана с замоканным LLM."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from application.use_cases.ai.nl_query_service import NLQueryService


def test_build_plan_parses_llm_json():
    plan_json = {
        "filters": [{"column": "region", "op": "eq", "value": "East"}],
        "group_by": ["region"],
        "aggregations": [{"column": "amount", "agg": "sum", "alias": "total"}],
        "limit": 20,
        "explanation": "сумма по регионам",
    }
    svc = NLQueryService()
    svc.llm = MagicMock()
    svc.llm.generate_text_sync = MagicMock(return_value=json.dumps(plan_json))

    schema = {"columns": [{"name": "region", "dtype": "Utf8"}, {"name": "amount", "dtype": "Int64"}], "rows": 10}
    plan = svc._build_plan("Сумма amount по region", schema)

    assert plan.group_by == ["region"]
    assert plan.aggregations[0].alias == "total"
    assert plan.explanation == "сумма по регионам"
    svc.llm.generate_text_sync.assert_called_once()
