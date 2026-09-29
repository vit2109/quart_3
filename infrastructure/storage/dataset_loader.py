"""Единая загрузка набора данных: meta + Polars DataFrame."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import polars as pl

from core.exceptions import DataLoadingError, NotFoundError
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import read_dataframe


def get_dataset_meta(dataset_id: int) -> Dict[str, Any]:
    """Метаданные набора или NotFoundError."""
    item = dataset_store.get_dataset(dataset_id)
    if not item:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return item


def get_dataset_file_path(dataset_id: int) -> Path:
    """Путь к файлу набора или NotFoundError."""
    path = dataset_store.get_dataset_path(dataset_id)
    if not path:
        raise NotFoundError(f"Dataset file for {dataset_id} not found")
    return path


def load_dataset_df(dataset_id: int) -> pl.DataFrame:
    """Загрузить DataFrame набора по ID."""
    path = get_dataset_file_path(dataset_id)
    try:
        return read_dataframe(path)
    except Exception as e:
        raise DataLoadingError(f"Failed to load dataset {dataset_id}: {e}") from e


def load_dataset(dataset_id: int) -> Tuple[pl.DataFrame, Dict[str, Any]]:
    """DataFrame + meta manifest одним вызовом."""
    meta = get_dataset_meta(dataset_id)
    return load_dataset_df(dataset_id), meta
