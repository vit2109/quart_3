"""Join двух наборов данных по ключу → новый dataset."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any, Dict, List, Optional, Union

import polars as pl

from core.exceptions import NotFoundError, ValidationError
from application.use_cases.analysis.analysis_service import _to_py
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import read_dataframe

JOIN_HOW = {"inner", "left", "right", "full", "cross", "semi", "anti"}


class DatasetJoinService:
    """Объединение таблиц Polars join с сохранением результата."""

    async def preview(
        self,
        left_id: int,
        right_id: int,
        left_on: Union[str, List[str]],
        right_on: Union[str, List[str]],
        how: str = "inner",
        limit: int = 20,
        left_sheet: Optional[str] = None,
        right_sheet: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._preview_blocking,
            left_id,
            right_id,
            left_on,
            right_on,
            how,
            limit,
            left_sheet,
            right_sheet,
        )

    async def join_and_save(
        self,
        left_id: int,
        right_id: int,
        left_on: Union[str, List[str]],
        right_on: Union[str, List[str]],
        how: str = "inner",
        name: Optional[str] = None,
        left_sheet: Optional[str] = None,
        right_sheet: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._join_and_save_blocking,
            left_id,
            right_id,
            left_on,
            right_on,
            how,
            name,
            left_sheet,
            right_sheet,
        )

    def _load_pair(
        self, left_id: int, right_id: int, left_sheet: Optional[str] = None,
        right_sheet: Optional[str] = None,
    ) -> tuple[pl.DataFrame, pl.DataFrame, Dict[str, Any], Dict[str, Any]]:
        if left_id == right_id:
            raise ValidationError("left_id and right_id must differ")
        left_meta = dataset_store.get_dataset(left_id)
        right_meta = dataset_store.get_dataset(right_id)
        if not left_meta:
            raise NotFoundError(f"Left dataset {left_id} not found")
        if not right_meta:
            raise NotFoundError(f"Right dataset {right_id} not found")
        left_path = dataset_store.get_dataset_path(left_id)
        right_path = dataset_store.get_dataset_path(right_id)
        if not left_path or not right_path:
            raise NotFoundError("Dataset file not found")
        return (
            read_dataframe(left_path, sheet_name=left_sheet),
            read_dataframe(right_path, sheet_name=right_sheet),
            left_meta,
            right_meta,
        )

    @staticmethod
    def _normalize_keys(keys: Union[str, List[str]]) -> List[str]:
        if isinstance(keys, str):
            return [keys]
        return [k for k in keys if k]

    def _join_df(
        self,
        left: pl.DataFrame,
        right: pl.DataFrame,
        left_on: List[str],
        right_on: List[str],
        how: str,
    ) -> pl.DataFrame:
        how = (how or "inner").lower()
        if how not in JOIN_HOW:
            raise ValidationError(f"how must be one of: {', '.join(sorted(JOIN_HOW))}")
        if not left_on or not right_on:
            raise ValidationError("left_on and right_on are required")
        if len(left_on) != len(right_on):
            raise ValidationError("left_on and right_on must have the same length")

        for col in left_on:
            if col not in left.columns:
                raise ValidationError(f"Column '{col}' not in left dataset")
        for col in right_on:
            if col not in right.columns:
                raise ValidationError(f"Column '{col}' not in right dataset")

        overlap = (set(left.columns) & set(right.columns)) - set(left_on) - set(right_on)
        right_renamed = right
        if overlap:
            right_renamed = right.rename({c: f"{c}__right" for c in overlap})

        return left.join(
            right_renamed,
            left_on=left_on,
            right_on=right_on,
            how=how,
            suffix="_r",
        )

    def _preview_blocking(
        self,
        left_id: int,
        right_id: int,
        left_on: Union[str, List[str]],
        right_on: Union[str, List[str]],
        how: str,
        limit: int,
        left_sheet: Optional[str],
        right_sheet: Optional[str],
    ) -> Dict[str, Any]:
        left, right, lmeta, rmeta = self._load_pair(left_id, right_id, left_sheet, right_sheet)
        joined = self._join_df(
            left, right, self._normalize_keys(left_on), self._normalize_keys(right_on), how
        )
        limit = max(1, min(int(limit or 20), 200))
        sample = joined.head(limit)
        return {
            "left_id": left_id,
            "right_id": right_id,
            "left_name": lmeta.get("name"),
            "right_name": rmeta.get("name"),
            "how": how,
            "left_on": self._normalize_keys(left_on),
            "right_on": self._normalize_keys(right_on),
            "left_sheet": left_sheet or lmeta.get("selected_sheet"),
            "right_sheet": right_sheet or rmeta.get("selected_sheet"),
            "left_rows": left.height,
            "right_rows": right.height,
            "joined_rows": joined.height,
            "joined_columns": list(joined.columns),
            "sample_columns": list(sample.columns),
            "sample_rows": [
                {k: _to_py(v) for k, v in row.items()} for row in sample.to_dicts()
            ],
        }

    def _join_and_save_blocking(
        self,
        left_id: int,
        right_id: int,
        left_on: Union[str, List[str]],
        right_on: Union[str, List[str]],
        how: str,
        name: Optional[str],
        left_sheet: Optional[str],
        right_sheet: Optional[str],
    ) -> Dict[str, Any]:
        left, right, lmeta, rmeta = self._load_pair(left_id, right_id, left_sheet, right_sheet)
        joined = self._join_df(
            left, right, self._normalize_keys(left_on), self._normalize_keys(right_on), how
        )
        if joined.height == 0:
            raise ValidationError("Join produced zero rows")

        buf = io.BytesIO()
        joined.write_csv(buf)
        content = buf.getvalue()

        join_meta = {
            "type": "join",
            "left_id": left_id,
            "right_id": right_id,
            "left_on": self._normalize_keys(left_on),
            "right_on": self._normalize_keys(right_on),
            "how": how,
            "left_sheet": left_sheet or lmeta.get("selected_sheet"),
            "right_sheet": right_sheet or rmeta.get("selected_sheet"),
        }
        default_name = f"{lmeta.get('name', left_id)} ⋈ {rmeta.get('name', right_id)}"
        record = dataset_store.save_dataset(
            original_filename=f"join_{left_id}_{right_id}.csv",
            content=content,
            name=name or default_name,
            description=json.dumps(join_meta, ensure_ascii=False),
            content_type="text/csv",
            allow_duplicate=True,
        )
        dataset_store.patch_dataset_meta(record["id"], join_meta=join_meta)
        return {
            "dataset": record,
            "join_meta": join_meta,
            "joined_rows": joined.height,
            "joined_columns": list(joined.columns),
        }
