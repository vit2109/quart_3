"""Тесты разрешения путей к моделям (без загрузки весов)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import settings
from infrastructure.ai.model_config import resolve_model_profile
from infrastructure.ai.model_manager import resolve_gguf_path


def test_resolve_gguf_path_from_explicit_file(tmp_path, monkeypatch):
    gguf = tmp_path / "custom.gguf"
    gguf.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", str(gguf))

    profile = resolve_model_profile("main")
    assert resolve_gguf_path(profile) == gguf.resolve()


def test_resolve_gguf_path_relative_to_cwd(tmp_path, monkeypatch):
    rel = Path("models_test") / "rel.gguf"
    full = tmp_path / rel
    full.parent.mkdir(parents=True)
    full.write_bytes(b"x" * 2_000_000)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", str(rel))

    profile = resolve_model_profile("main")
    assert resolve_gguf_path(profile) == full.resolve()


def test_resolve_gguf_path_default_in_models_dir(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    default = models / settings.LLAMA_GGUF_FILE
    default.write_bytes(b"x" * 100)

    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", None)
    monkeypatch.setattr(settings, "LLAMA_MODELS_DIR", str(models))

    profile = resolve_model_profile("main")
    assert resolve_gguf_path(profile) == default.resolve()
