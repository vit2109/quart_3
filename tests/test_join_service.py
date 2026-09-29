"""Тесты join наборов."""

from __future__ import annotations

import pytest

from application.use_cases.datasets.join_service import DatasetJoinService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def pair_ids(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    left = dataset_store.save_dataset(
        original_filename="left.csv",
        content=sample_csv.read_bytes(),
        name="Left",
        allow_duplicate=True,
    )
    right = dataset_store.save_dataset(
        original_filename="right.csv",
        content=sample_csv.read_bytes(),
        name="Right",
        allow_duplicate=True,
    )
    return left["id"], right["id"]


@pytest.mark.asyncio
async def test_join_preview(pair_ids):
    left_id, right_id = pair_ids
    result = await DatasetJoinService().preview(
        left_id, right_id, ["region"], ["region"], how="inner"
    )
    assert result["joined_rows"] >= 1
    assert result["sample_rows"]

@pytest.mark.asyncio
async def test_join_save(pair_ids):
    left_id, right_id = pair_ids
    result = await DatasetJoinService().join_and_save(
        left_id, right_id, ["region"], ["region"], how="inner", name="Joined"
    )
    assert result["dataset"]["id"]
    assert result["joined_rows"] >= 1
