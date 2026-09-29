"""Тесты хранилища отчётов: удаление и очистка истории."""

from __future__ import annotations

import pytest

from core.config import settings
from infrastructure.storage import report_store


@pytest.fixture(autouse=True)
def isolated_report_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_DIR", str(tmp_path / "reports"))


def test_delete_and_clear_reports():
    report_store.save_report({"name": "A", "dataset_id": 1, "report_type": "summary", "tables": []})
    report_store.save_report({"name": "B", "dataset_id": 1, "report_type": "summary", "tables": []})
    items = report_store.list_reports()
    assert len(items) == 2

    assert report_store.delete_report(items[0]["id"]) is True
    assert len(report_store.list_reports()) == 1

    assert report_store.delete_report(9999) is False

    deleted = report_store.clear_reports()
    assert deleted == 1
    assert report_store.list_reports() == []
