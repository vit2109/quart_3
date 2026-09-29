"""Тесты Pareto-анализа."""

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
        name="Pareto Sample",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_pareto_cumulative_share(dataset_id):
    result = await AnalysisService().pareto(
        dataset_id,
        ["region"],
        "amount",
        agg="sum",
        top_n=10,
    )
    assert result["metric"] == "amount"
    assert result["rows"]
    assert "share_%" in result["rows"][0]
    assert "cum_share_%" in result["rows"][0]
    assert result["rows"][-1]["cum_share_%"] <= 100.01
    assert result["hhi"] >= 0
    assert result["chart"]
