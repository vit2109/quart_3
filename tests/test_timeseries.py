"""Тесты динамики (time series)."""

from __future__ import annotations

import pytest

from application.use_cases.analysis.analysis_service import AnalysisService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dated_dataset_id(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    csv = (
        "date,amount,region\n"
        "2024-01-01,100,East\n"
        "2024-01-02,200,West\n"
        "2024-01-03,150,East\n"
        "2024-01-10,300,West\n"
    ).encode()
    record = dataset_store.save_dataset(
        original_filename="dated.csv",
        content=csv,
        name="Timeseries Sample",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_timeseries_daily_sum(dated_dataset_id):
    result = await AnalysisService().timeseries(
        dated_dataset_id,
        "date",
        ["amount"],
        granularity="day",
        agg="sum",
    )
    assert result["date_col"] == "date"
    assert result["metrics"] == ["amount"]
    assert len(result["periods"]) >= 3
    assert result["chart"]["type"] == "line"
    assert len(result["rows"]) == len(result["periods"])


@pytest.mark.asyncio
async def test_timeseries_with_filters(dated_dataset_id):
    result = await AnalysisService().timeseries(
        dated_dataset_id,
        "date",
        ["amount"],
        granularity="day",
        agg="sum",
        filters=[{"column": "region", "op": "eq", "value": "East"}],
    )
    assert result["filtered_rows"] == 2
    assert result["source_rows"] == 4
