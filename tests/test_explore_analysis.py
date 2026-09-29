"""Тест универсального анализа (explore)."""

from __future__ import annotations

import pytest

from application.use_cases.analysis.analysis_service import AnalysisService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dataset_id(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    record = dataset_store.save_dataset(
        original_filename="sample.csv",
        content=sample_csv.read_bytes(),
        name="Explore Sample",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_explore_grouped_with_filters(dataset_id):
    result = await AnalysisService().explore(
        dataset_id,
        mode="grouped",
        filters=[{"column": "region", "op": "eq", "value": "East"}],
        group_by=["region"],
        aggregations=[
            {"column": "amount", "agg": "sum"},
            {"column": "qty", "agg": "mean"},
        ],
        limit=50,
    )
    assert result["filtered_rows"] == 2
    assert result["returned_rows"] >= 1


@pytest.mark.asyncio
async def test_explore_with_chart(dataset_id):
    result = await AnalysisService().explore(
        dataset_id,
        mode="grouped",
        group_by=["region"],
        aggregations=[{"column": "amount", "agg": "sum"}],
        chart={
            "enabled": True,
            "type": "bar",
            "label_column": "region",
            "value_column": "amount__sum",
        },
    )
    assert result.get("chart")
    assert result["chart"].get("labels")
