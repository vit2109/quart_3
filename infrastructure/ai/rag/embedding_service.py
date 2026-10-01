"""Обёртка над sentence-transformers для офлайн-эмбеддингов (ленивая загрузка)."""

from __future__ import annotations

import gc
import logging
from pathlib import Path
import sys
import threading
import time
from typing import List

from core.config import settings
from infrastructure.ai.device_utils import resolve_embedding_device

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_model = None


def _load_model():
    import torch
    from sentence_transformers import SentenceTransformer

    device = resolve_embedding_device()
    threads = max(1, int(settings.EMBEDDING_TORCH_THREADS or 2))
    if device == "cpu":
        torch.set_num_threads(threads)
    logger.info(
        "Loading embedding model %s (device=%s, torch_threads=%s)",
        settings.EMBEDDING_MODEL,
        device,
        threads if device == "cpu" else "n/a",
    )
    model_source: str | Path = settings.EMBEDDING_MODEL
    local_only = False
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "embedding_model"
        external = Path(settings.EMBEDDING_MODEL)
        if bundled.is_dir():
            model_source = bundled
        elif external.is_dir():
            model_source = external
        else:
            raise RuntimeError(
                "Модель эмбеддингов не найдена в EXE. Пересоберите приложение "
                "после запуска scripts/prepare_embedding_model.py."
            )
        local_only = True
    return SentenceTransformer(
        str(model_source), device=device, local_files_only=local_only
    )


def get_embedding_model():
    """Ленивая загрузка модели; блокировка не удерживается во время инициализации."""
    global _model
    if _model is not None:
        return _model

    with _lock:
        if _model is not None:
            return _model

    loaded = _load_model()

    with _lock:
        if _model is None:
            _model = loaded
            logger.info("Embedding model ready")
        return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Получить эмбеддинги для списка текстов (мини-пакетами для экономии RAM)."""
    if not texts:
        return []
    model = get_embedding_model()
    batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE or 8))
    if len(texts) <= batch_size:
        vectors = model.encode(
            texts,
            show_progress_bar=False,
            batch_size=batch_size,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    out: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = model.encode(
            batch,
            show_progress_bar=False,
            batch_size=batch_size,
            convert_to_numpy=True,
        )
        out.extend(vectors.tolist())
        del vectors
        gc.collect()
        pause_ms = int(settings.KNOWLEDGE_INDEX_PAUSE_MS or 0)
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)
    return out


def embed_query(text: str) -> List[float]:
    """Эмбеддинг одного запроса."""
    return embed_texts([text])[0]
