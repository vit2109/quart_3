"""Тесты устойчивости chunk_store к повреждённому manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import settings
from infrastructure.knowledge import chunk_store


@pytest.fixture
def knowledge_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KNOWLEDGE_DIR", str(tmp_path))
    return tmp_path


def test_read_recovers_from_corrupt_utf8(knowledge_dir):
    path = knowledge_dir / "chunks_manifest.json"
    # Valid prefix + binary garbage (simulates interrupted write)
    path.write_bytes(b'[{"id": "chk_test", "text": "hello"' + b"\x00" * 16)

    items = chunk_store._read()
    assert isinstance(items, list)
    # Recovery falls back to empty or Chroma rebuild
    assert path.exists()


def test_atomic_write_and_read(knowledge_dir):
    chunk_store.add_chunks(
        [
            {
                "id": "chk_abc",
                "document_id": "doc_1",
                "text": "sample",
                "char_count": 6,
                "word_count": 1,
                "collection": "quart_knowledge",
            }
        ]
    )
    items = chunk_store._read()
    assert len(items) == 1
    assert items[0]["id"] == "chk_abc"


def test_delete_chunks_removes_only_requested_records(knowledge_dir):
    chunk_store.add_chunks(
        [
            {"id": "old-1", "document_id": "doc", "text": "old"},
            {"id": "old-2", "document_id": "doc", "text": "old"},
            {"id": "new-1", "document_id": "doc", "text": "new"},
        ]
    )

    assert chunk_store.delete_chunks(["old-1", "old-2"]) == 2
    assert [item["id"] for item in chunk_store.all_chunks()] == ["new-1"]
