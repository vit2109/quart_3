"""Тесты паспорта набора данных."""

from __future__ import annotations

import pytest

from application.use_cases.datasets.dataset_profile_service import DatasetProfileService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dataset_id(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    record = dataset_store.save_dataset(
        original_filename="sample.csv",
        content=sample_csv.read_bytes(),
        name="Profile Sample",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_dataset_profile_structure(dataset_id):
    profile = await DatasetProfileService().get_profile(dataset_id, sample_limit=10)
    assert profile["dataset_id"] == dataset_id
    assert profile["rows"] == 4
    assert profile["columns_count"] == 4
    assert len(profile["sample_rows"]) <= 10
    assert len(profile["columns"]) == 4
    assert profile["insights"]
    assert "region" in {c["name"] for c in profile["columns"]}
