"""Общие утилиты Polars: типы, сериализация скаляров."""

from __future__ import annotations

from typing import Any, Dict

import polars as pl

NUMERIC_DTYPES = {
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
    pl.Float32,
    pl.Float64,
}


def to_py(value: Any) -> Any:
    """Привести Polars/NumPy скаляр к нативному Python-типу."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def stringify_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Сериализовать строку DataFrame для JSON-ответа."""
    return {k: to_py(v) for k, v in row.items()}
