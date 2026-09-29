"""Чтение схемы и данных из файлов CSV, Excel, JSON, Parquet (Polars)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import polars as pl

from infrastructure.storage import dataframe_cache

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".json", ".parquet", ".xlsx", ".xls"}


def _read_preview(path: Path) -> pl.DataFrame:
    """Прочитать первые строки файла для определения схемы колонок."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pl.read_csv(path, n_rows=50, ignore_errors=True, infer_schema_length=50)
    if suffix == ".tsv":
        return pl.read_csv(
            path,
            separator="\t",
            n_rows=50,
            ignore_errors=True,
            infer_schema_length=50,
        )
    if suffix == ".json":
        try:
            return pl.read_json(path)
        except Exception:
            return pl.read_ndjson(path, n_rows=50)
    if suffix == ".parquet":
        return pl.read_parquet(path, n_rows=50)
    if suffix in {".xlsx", ".xls"}:
        return pl.read_excel(path, infer_schema_length=50)
    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def get_columns(path: Path) -> List[Dict[str, Any]]:
    """Вернуть метаданные колонок: name, dtype, kind (number/string/datetime)."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")

    df = _read_preview(path)
    return _columns_meta(df)


def read_dataframe(path: Path, *, use_cache: bool = True) -> pl.DataFrame:
    """Полностью загрузить файл в Polars DataFrame (с опциональным кэшем)."""
    if use_cache:
        cached = dataframe_cache.get_cached(path)
        if cached is not None:
            return cached

    df = _read_dataframe_uncached(path)
    if use_cache:
        dataframe_cache.put_cached(path, df)
    return df


def invalidate_dataframe_cache(path: Path) -> None:
    """Сбросить кэш после изменения файла набора данных."""
    dataframe_cache.invalidate_path(path)


def _read_dataframe_uncached(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pl.read_csv(path, ignore_errors=True, infer_schema_length=1000)
    if suffix == ".tsv":
        return pl.read_csv(
            path,
            separator="\t",
            ignore_errors=True,
            infer_schema_length=1000,
        )
    if suffix == ".json":
        try:
            return pl.read_json(path)
        except Exception:
            return pl.read_ndjson(path)
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix in {".xlsx", ".xls"}:
        return pl.read_excel(path, infer_schema_length=1000)
    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def _columns_meta(df: pl.DataFrame) -> List[Dict[str, Any]]:
    """Классифицировать типы колонок для UI-пикеров."""
    columns: List[Dict[str, Any]] = []
    for name, dtype in zip(df.columns, df.dtypes):
        kind = "string"
        dtype_str = str(dtype)
        if dtype in (
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
        ):
            kind = "number"
        elif dtype in (pl.Date, pl.Datetime, pl.Time):
            kind = "datetime"
        elif dtype == pl.Boolean:
            kind = "boolean"
        elif "Date" in dtype_str or "Datetime" in dtype_str:
            kind = "datetime"
        columns.append({"name": name, "dtype": dtype_str, "kind": kind})
    return columns
