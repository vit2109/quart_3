"""Паспорт набора данных: sample, профиль колонок, быстрые инсайты."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import polars as pl

from core.exceptions import NotFoundError
from core.polars_utils import NUMERIC_DTYPES, to_py as _to_py
from infrastructure.storage import dataset_store
from infrastructure.storage.dataset_loader import get_dataset_file_path, load_dataset_df
from infrastructure.storage.schema_reader import get_columns


class DatasetProfileService:
    """Формирование паспорта датасета для вкладки «Данные»."""

    async def get_profile(
        self, dataset_id: int, sample_limit: int = 50
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._get_profile_blocking, dataset_id, sample_limit
        )

    def _get_profile_blocking(
        self, dataset_id: int, sample_limit: int = 50
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")

        sample_limit = max(5, min(int(sample_limit or 50), 200))
        path = get_dataset_file_path(dataset_id)
        df = load_dataset_df(dataset_id)
        schema_cols = get_columns(path)
        kind_map = {c["name"]: c.get("kind", "string") for c in schema_cols}

        rows = df.height
        cols_count = len(df.columns)
        total_cells = rows * cols_count if rows and cols_count else 0
        missing_total = sum(int(df[c].null_count()) for c in df.columns)
        completeness = (
            round(1.0 - missing_total / total_cells, 4) if total_cells else 1.0
        )
        duplicate_rows = rows - df.unique().height if rows else 0

        column_profiles: List[Dict[str, Any]] = []
        for col in df.columns:
            s = df[col]
            kind = kind_map.get(col, "string")
            miss = int(s.null_count())
            miss_pct = round(100.0 * miss / rows, 2) if rows else 0.0
            profile: Dict[str, Any] = {
                "name": col,
                "kind": kind,
                "dtype": str(s.dtype),
                "missing": miss,
                "missing_pct": miss_pct,
                "unique": int(s.n_unique()),
            }
            if s.dtype in NUMERIC_DTYPES:
                profile.update(
                    {
                        "min": _to_py(s.min()),
                        "max": _to_py(s.max()),
                        "mean": _to_py(s.mean()),
                    }
                )
            elif kind == "datetime" or s.dtype in (pl.Date, pl.Datetime):
                non_null = s.drop_nulls()
                if non_null.len():
                    profile["min"] = _to_py(non_null.min())
                    profile["max"] = _to_py(non_null.max())
            else:
                top = (
                    s.drop_nulls()
                    .cast(pl.String)
                    .value_counts()
                    .sort("count", descending=True)
                    .head(5)
                )
                profile["top_values"] = [
                    {"value": _to_py(r[col]), "count": int(r["count"])}
                    for r in top.to_dicts()
                ]
            column_profiles.append(profile)

        sample_df = df.head(sample_limit)
        sample_rows = [
            {k: _to_py(v) for k, v in row.items()}
            for row in sample_df.to_dicts()
        ]

        insights = self._build_insights(
            df, column_profiles, rows, duplicate_rows, completeness
        )

        from infrastructure.knowledge.document_store import list_by_dataset_id

        knowledge_docs = list_by_dataset_id(dataset_id)
        lineage = item.get("lineage") or item.get("join_meta")
        if item.get("join_meta") and not item.get("lineage"):
            lineage = {"type": "join", **item.get("join_meta", {})}

        return {
            "dataset_id": dataset_id,
            "name": item.get("name"),
            "filename": item.get("filename"),
            "description": item.get("description"),
            "rows": rows,
            "columns_count": cols_count,
            "completeness": completeness,
            "duplicate_rows": duplicate_rows,
            "sample_limit": sample_limit,
            "sample_rows": sample_rows,
            "sample_columns": list(sample_df.columns),
            "columns": column_profiles,
            "insights": insights,
            "lineage": lineage,
            "knowledge_documents": [
                {
                    "id": d.get("id"),
                    "title": d.get("title"),
                    "chunk_count": d.get("chunk_count", 0),
                }
                for d in knowledge_docs
            ],
        }

    def _build_insights(
        self,
        df: pl.DataFrame,
        profiles: List[Dict[str, Any]],
        rows: int,
        duplicate_rows: int,
        completeness: float,
    ) -> List[str]:
        insights: List[str] = []
        if rows:
            insights.append(f"Набор содержит {rows} строк и {len(df.columns)} колонок.")
        if completeness < 0.95:
            insights.append(
                f"Заполненность {round(completeness * 100, 1)}% — есть пропуски, стоит проверить ETL."
            )
        if duplicate_rows:
            insights.append(f"Обнаружено {duplicate_rows} дубликатов строк.")

        cat_cols = [p for p in profiles if p["kind"] != "number" and p.get("unique", 0) <= 200]
        if cat_cols:
            best = max(cat_cols, key=lambda p: p.get("unique", 0))
            insights.append(
                f"Категориальное поле «{best['name']}»: {best['unique']} уникальных значений."
            )

        num_cols = [p for p in profiles if p["kind"] == "number"]
        if num_cols:
            insights.append(f"Числовых метрик: {len(num_cols)} — доступны sum/mean и корреляции.")

        date_cols = [p for p in profiles if p["kind"] == "datetime"]
        if date_cols:
            dc = date_cols[0]
            if dc.get("min") and dc.get("max"):
                insights.append(
                    f"Период по «{dc['name']}»: {dc['min']} — {dc['max']} (метод «Динамика»)."
                )

        high_miss = [p for p in profiles if p.get("missing_pct", 0) >= 10]
        for p in high_miss[:2]:
            insights.append(f"«{p['name']}»: {p['missing_pct']}% пропусков.")

        return insights[:8]
