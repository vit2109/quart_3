"""Тесты AnalysisService."""

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
        name="Sample",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_statistics(dataset_id):
    svc = AnalysisService()
    result = await svc.get_statistics(dataset_id, columns=["amount"])
    assert result["rows"] == 4
    assert "amount" in result["stats"]
    assert result["stats"]["amount"]["mean"] == 187.5


@pytest.mark.asyncio
async def test_correlations(dataset_id):
    svc = AnalysisService()
    result = await svc.get_correlations(dataset_id, "pearson")
    assert "amount" in result["columns"]
    assert "qty" in result["columns"]
    matrix = result["matrix"]
    assert matrix["amount"]["amount"] == 1.0
    assert matrix["amount"]["qty"] is not None


@pytest.mark.asyncio
async def test_compare_periods(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    csv_content = (
        "date,amount,qty\n"
        "2024-01-05,100,10\n"
        "2024-01-20,200,20\n"
        "2024-02-05,150,15\n"
        "2024-02-20,300,30\n"
    ).encode("utf-8")
    record = dataset_store.save_dataset(
        original_filename="periods.csv",
        content=csv_content,
        name="Periods",
    )
    svc = AnalysisService()
    result = await svc.compare_periods(
        record["id"],
        "date",
        {"from": "2024-01-01", "to": "2024-01-31"},
        {"from": "2024-02-01", "to": "2024-02-29"},
        metrics=["amount"],
    )
    assert result["period_a"]["row_count"] == 2
    assert result["period_b"]["row_count"] == 2
    metric = result["metrics"][0]
    assert metric["column"] == "amount"
    assert metric["delta"]["sum"] == 150.0
