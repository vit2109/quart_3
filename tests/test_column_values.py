"""Тест автодополнения значений колонок."""

from __future__ import annotations

import pytest

from application.use_cases.export.export_service import ExportService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dataset_id(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    record = dataset_store.save_dataset(
        original_filename="sample.csv",
        content=sample_csv.read_bytes(),
        name="Sample Values",
    )
    return record["id"]


def test_column_values_search(dataset_id):
    svc = ExportService()
    all_regions = svc.get_column_values(dataset_id, "region", q="", limit=10)
    assert set(all_regions["values"]) == {"East", "West"}

    east = svc.get_column_values(dataset_id, "region", q="Eas", limit=10)
    assert east["values"] == ["East"]

    amounts = svc.get_column_values(dataset_id, "amount", q="1", limit=10)
    assert any("1" in str(v) for v in amounts["values"])
