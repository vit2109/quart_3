"""Запуск изолированной индексации из PyInstaller EXE."""

from __future__ import annotations

import json
import subprocess
import sys

from application.use_cases.knowledge.knowledge_service import KnowledgeService


def test_frozen_executable_uses_worker_flag(monkeypatch):
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"chunks_indexed": 2}),
            stderr="",
        )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "application.use_cases.knowledge.knowledge_service.ensure_min_free_ram",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "application.use_cases.knowledge.knowledge_service.chroma_client.invalidate_client_cache",
        lambda: None,
    )

    result = KnowledgeService()._index_via_subprocess("doc-1", "quart_knowledge")

    assert result == {"chunks_indexed": 2}
    assert captured["command"] == [
        sys.executable,
        "--knowledge-index-worker",
        "doc-1",
        "--collection",
        "quart_knowledge",
    ]
    assert captured["kwargs"]["capture_output"] is True
