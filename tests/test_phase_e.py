"""Тесты webhook и связей knowledge/dataset."""

from __future__ import annotations

import pytest

from infrastructure.knowledge.document_store import list_by_dataset_id
from infrastructure.knowledge import document_store
from infrastructure.storage import job_store


def test_create_schedule_with_webhook(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path))
    schedule = job_store.create_schedule(
        "Daily",
        "report_generate",
        {"dataset_id": 1},
        "0 8 * * *",
        webhook_url="https://example.com/hook",
    )
    assert schedule["webhook_url"] == "https://example.com/hook"
    fetched = job_store.get_schedule(schedule["id"])
    assert fetched["webhook_url"] == "https://example.com/hook"


def test_list_by_dataset_id(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    document_store.save_document(
        original_filename="ds.csv",
        content=b"a,b\n1,2",
        title="From dataset",
        source_type="table",
        extra_meta={"dataset_id": 42},
    )
    document_store.save_document(
        original_filename="other.txt",
        content=b"hello",
        title="Other",
        source_type="text",
    )
    linked = list_by_dataset_id(42)
    assert len(linked) == 1
    assert linked[0]["title"] == "From dataset"


@pytest.mark.asyncio
async def test_send_webhook_invalid_url():
    from core.webhook_notify import send_webhook

    assert await send_webhook("", event="x", job_type="t", run_id="1", status="ok") is False
    assert (
        await send_webhook(
            "ftp://bad",
            event="x",
            job_type="t",
            run_id="1",
            status="ok",
        )
        is False
    )
