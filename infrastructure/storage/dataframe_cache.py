"""LRU-кэш Polars DataFrame по пути файла и mtime."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, Tuple

import polars as pl

from core.config import settings

_lock = threading.RLock()
_cache: Dict[Tuple[str, int, int], Tuple[float, pl.DataFrame]] = {}


def _cache_key(path: Path) -> Tuple[str, int, int]:
    resolved = path.resolve()
    stat = resolved.stat()
    return (str(resolved), stat.st_mtime_ns, stat.st_size)


def get_cached(path: Path) -> pl.DataFrame | None:
    """Вернуть кэшированный DataFrame или None."""
    if not path.exists():
        return None
    key = _cache_key(path)
    ttl = max(int(getattr(settings, "DATAFRAME_CACHE_TTL", 600)), 60)
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    return None


def put_cached(path: Path, df: pl.DataFrame) -> None:
    """Сохранить DataFrame в кэш."""
    if not path.exists():
        return
    key = _cache_key(path)
    now = time.monotonic()
    with _lock:
        _cache[key] = (now, df)
        _prune_locked(max_entries=16)


def invalidate_path(path: Path) -> None:
    """Сбросить кэш для файла (после update/delete датасета)."""
    resolved = str(path.resolve())
    with _lock:
        drop = [k for k in _cache if k[0] == resolved]
        for key in drop:
            _cache.pop(key, None)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _prune_locked(*, max_entries: int) -> None:
    if len(_cache) <= max_entries:
        return
    oldest = sorted(_cache.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_cache) - max_entries]:
        _cache.pop(key, None)
