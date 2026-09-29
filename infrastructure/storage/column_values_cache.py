"""Кэш уникальных значений колонок для автодополнения фильтров."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Tuple

import polars as pl

from application.use_cases.analysis.analysis_service import _to_py
from core.config import settings

_lock = threading.RLock()
_cache: Dict[Tuple[int, str, str, int, int], Tuple[float, List[Any], int]] = {}


def _cache_key(dataset_id: int, column: str, path_key: Tuple[str, int, int]) -> Tuple[int, str, str, int, int]:
    return (dataset_id, column, path_key[0], path_key[1], path_key[2])


def get_or_query(
    *,
    dataset_id: int,
    column: str,
    path_key: Tuple[str, int, int],
    df: pl.DataFrame,
    q: str,
    limit: int,
) -> Tuple[List[Any], int, bool]:
    """Вернуть (values, total_unique, from_cache)."""
    q_norm = (q or "").strip().lower()
    ttl = max(int(getattr(settings, "COLUMN_VALUES_CACHE_TTL", 300)), 60)
    now = time.monotonic()
    key = _cache_key(dataset_id, column, path_key)

    total_unique = int(df[column].drop_nulls().n_unique())

    if not q_norm:
        with _lock:
            entry = _cache.get(key)
            if entry and now - entry[0] < ttl:
                cached_values, cached_total = entry[1], entry[2]
                return cached_values[:limit], cached_total, True

    values = _query_values(df, column, q_norm, limit)

    if not q_norm:
        with _lock:
            _cache[key] = (now, values, total_unique)
            _prune_locked(max_entries=128)

    truncated = len(values) >= limit or (q_norm and total_unique > len(values))
    return values, total_unique, False


def invalidate_dataset(dataset_id: int) -> None:
    with _lock:
        drop = [k for k in _cache if k[0] == dataset_id]
        for key in drop:
            _cache.pop(key, None)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _query_values(df: pl.DataFrame, column: str, q_lower: str, limit: int) -> List[Any]:
    base = df.select(column).drop_nulls()
    if base.height == 0:
        return []

    if q_lower:
        work = (
            base.with_columns(pl.col(column).cast(pl.String).alias("_s"))
            .filter(pl.col("_s").str.to_lowercase().str.contains(q_lower, literal=False))
            .select(column)
        )
    else:
        work = base

    unique = work.unique().sort(column).head(limit)
    return [_to_py(v) for v in unique[column].to_list()]


def _prune_locked(*, max_entries: int) -> None:
    if len(_cache) <= max_entries:
        return
    oldest = sorted(_cache.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_cache) - max_entries]:
        _cache.pop(key, None)
