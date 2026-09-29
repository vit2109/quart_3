"""Тесты профилей LLM (main / sql)."""

from __future__ import annotations

from core.config import settings
from infrastructure.ai.model_config import (
    resolve_model_profile,
    sql_uses_separate_model,
)


def test_main_profile_uses_primary_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", "/models/main.gguf")
    monkeypatch.setattr(settings, "TRANSFORMERS_MODEL_ID", "org/main-model")
    monkeypatch.setattr(settings, "SQL_LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "SQL_TRANSFORMERS_MODEL_ID", None)

    profile = resolve_model_profile("main")
    assert profile.name == "main"
    assert profile.llama_model_path == "/models/main.gguf"
    assert profile.transformers_model_id == "org/main-model"
    assert profile.cache_key == "gguf:/models/main.gguf"


def test_sql_profile_fallback_to_main(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", "/models/main.gguf")
    monkeypatch.setattr(settings, "TRANSFORMERS_MODEL_ID", "org/main-model")
    monkeypatch.setattr(settings, "SQL_LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "SQL_TRANSFORMERS_MODEL_ID", None)

    sql = resolve_model_profile("sql")
    main = resolve_model_profile("main")
    assert sql.cache_key == main.cache_key
    assert sql_uses_separate_model() is False


def test_sql_profile_separate_gguf(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", "/models/main.gguf")
    monkeypatch.setattr(settings, "SQL_LLAMA_MODEL_PATH", "/models/sql.gguf")
    monkeypatch.setattr(settings, "SQL_TRANSFORMERS_MODEL_ID", None)

    sql = resolve_model_profile("sql")
    assert sql.llama_model_path == "/models/sql.gguf"
    assert sql.cache_key == "gguf:/models/sql.gguf"
    assert sql_uses_separate_model() is True


def test_sql_profile_separate_transformers_id(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "TRANSFORMERS_MODEL_ID", "org/main-model")
    monkeypatch.setattr(settings, "SQL_LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "SQL_TRANSFORMERS_MODEL_ID", "org/sql-model")

    sql = resolve_model_profile("sql")
    assert sql.transformers_model_id == "org/sql-model"
    assert sql.cache_key == "hf:org/sql-model"
    assert sql_uses_separate_model() is True


def test_cache_key_hf_when_no_gguf_path(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "TRANSFORMERS_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")

    profile = resolve_model_profile("main")
    assert profile.cache_key == "hf:Qwen/Qwen2.5-1.5B-Instruct"
