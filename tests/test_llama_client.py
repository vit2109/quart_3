"""Тесты LocalLLMClient (без загрузки моделей)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from infrastructure.ai.llama_client import LocalLLMClient


@pytest.mark.asyncio
async def test_health_main_profile_includes_sql_block(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "TRANSFORMERS_MODEL_ID", "org/main")
    monkeypatch.setattr(settings, "SQL_LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "SQL_TRANSFORMERS_MODEL_ID", None)

    client = LocalLLMClient(profile="main")
    with patch.object(client, "_detect_backend", return_value="transformers"):
        data = await client.health()

    assert data["profile"] == "main"
    assert data["transformers_model_id"] == "org/main"
    assert "sql_model" in data
    assert data["sql_model"]["uses_main_fallback"] is True
    assert data["sql_model"]["separate"] is False


@pytest.mark.asyncio
async def test_health_sql_profile_no_nested_sql_block(monkeypatch):
    monkeypatch.setattr(settings, "SQL_TRANSFORMERS_MODEL_ID", "org/sql-only")
    client = LocalLLMClient(profile="sql")
    with patch.object(client, "_detect_backend", return_value="transformers"):
        data = await client.health()

    assert data["profile"] == "sql"
    assert data["transformers_model_id"] == "org/sql-only"
    assert "sql_model" not in data


def test_client_sql_profile_resolves_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "SQL_LLAMA_MODEL_PATH", "/x/sql.gguf")
    client = LocalLLMClient(profile="sql")
    assert client._profile.llama_model_path == "/x/sql.gguf"


def test_generate_text_sync_delegates_to_backend(monkeypatch):
    client = LocalLLMClient(profile="main")
    client.ensure_backend_sync = MagicMock(
        return_value={"backend": "llama_cpp", "model": "m.gguf", "profile": "main"}
    )
    client._chat_llama_cpp = MagicMock(return_value='{"ok": true}')

    out = client.generate_text_sync("prompt", system="sys")
    assert out == '{"ok": true}'
    client._chat_llama_cpp.assert_called_once()
