"""Тесты SQL-lite."""

from __future__ import annotations

import pytest

from application.use_cases.query.sql_query_service import SqlQueryService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dataset_id(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    record = dataset_store.save_dataset(
        original_filename="sample.csv",
        content=sample_csv.read_bytes(),
        name="SQL Sample",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_sql_select(dataset_id):
    result = await SqlQueryService().execute(
        "SELECT region, amount FROM ds ORDER BY amount DESC LIMIT 2",
        [{"alias": "ds", "dataset_id": dataset_id}],
    )
    assert result["rows"]
    assert "region" in result["columns"]


@pytest.mark.asyncio
async def test_sql_rejects_drop(dataset_id):
    with pytest.raises(Exception):
        await SqlQueryService().execute(
            "DROP TABLE ds",
            [{"alias": "ds", "dataset_id": dataset_id}],
        )
