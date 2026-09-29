"""Тесты сканирования локальных моделей."""

from __future__ import annotations

from core.config import settings
from infrastructure.ai.model_manager import list_local_models


def test_list_local_models_finds_gguf(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    gguf = models / "test-model.gguf"
    gguf.write_bytes(b"x" * 2_000_000)

    monkeypatch.setattr(settings, "LLAMA_MODELS_DIR", str(models))
    monkeypatch.setattr(settings, "LLAMA_MODEL_PATH", str(gguf))

    items = list_local_models()
    paths = {m["path"] for m in items}
    assert str(gguf.resolve()) in paths
