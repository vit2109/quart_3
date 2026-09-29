"""Тесты предупреждений об обрезке результатов."""

from core.config import settings
from core.result_limits import apply_result_limit_meta


def test_group_warning_when_many_rows():
    payload = {"mode": "grouped", "total_rows": 50, "returned_rows": 50}
    apply_result_limit_meta(
        payload,
        mode="grouped",
        total_rows=15_000,
        returned_rows=200,
        limit=200,
    )
    assert payload["result_truncated"] is True
    assert payload["result_total_rows"] == 15_000
    assert "15 000" in payload["result_warning"]


def test_no_warning_below_threshold():
    payload = {}
    apply_result_limit_meta(
        payload,
        mode="grouped",
        total_rows=500,
        returned_rows=500,
        limit=1000,
    )
    assert "result_warning" not in payload
    assert "result_truncated" not in payload


def test_raw_mode_skips_group_warning():
    payload = {}
    apply_result_limit_meta(
        payload,
        mode="raw",
        total_rows=20_000,
        returned_rows=100,
        limit=100,
    )
    assert payload.get("result_truncated") is True
    assert "result_warning" not in payload
