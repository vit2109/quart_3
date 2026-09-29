"""Тесты saved views store."""

from __future__ import annotations

import pytest

from core.config import settings
from infrastructure.storage import views_store


@pytest.fixture(autouse=True)
def views_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path / "data"))


def test_save_and_list_views():
    record = views_store.save_view(
        1,
        {"name": "Test view", "mode": "summary", "filters": [], "group_by": ["region"]},
    )
    assert record["id"] == 1
    items = views_store.list_views(1)
    assert len(items) == 1
    assert items[0]["name"] == "Test view"

    full = views_store.get_view(1, 1)
    assert full["group_by"] == ["region"]

    assert views_store.delete_view(1, 1) is True
    assert views_store.list_views(1) == []
