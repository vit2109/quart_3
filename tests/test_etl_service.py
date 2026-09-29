"""Тесты ETLService."""

from __future__ import annotations

import pytest

from application.use_cases.etl.etl_service import ETLService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dataset_id(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    record = dataset_store.save_dataset(
        original_filename="sample.csv",
        content=sample_csv.read_bytes(),
        name="Sample ETL",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_quality_metrics(dataset_id):
    data = await ETLService().quality(dataset_id)
    assert data["rows"] == 4
    assert 0 <= data["completeness"] <= 1
    assert data["duplicate_rows"] == 0


@pytest.mark.asyncio
async def test_process_creates_new_dataset(dataset_id):
    result = await ETLService().process(
        dataset_id,
        {
            "clean_missing": True,
            "remove_duplicates": True,
            "normalize_strings": True,
            "remove_outliers": False,
        },
    )
    assert result["rows_after"] == 4
    assert result["new_dataset"]["id"] != dataset_id
