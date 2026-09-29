"""ETL: очистка табличных наборов, preview diff и оценка качества."""

from __future__ import annotations

import asyncio
import io
from typing import Any, Dict, List, Optional

import polars as pl

from application.use_cases.analysis.analysis_service import NUMERIC_DTYPES, _to_py
from core.exceptions import NotFoundError, ValidationError
from infrastructure.etl.cleaner import DataCleaner
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import read_dataframe

NUMERIC_DTYPES_SET = NUMERIC_DTYPES

MISSING_STRATEGIES = {
    "drop",
    "fill_zero",
    "fill_mean",
    "fill_median",
    "fill_unknown",
    "forward_fill",
}


class ETLService:
    """Применение DataCleaner и сохранение очищенного набора."""

    async def process(self, dataset_id: int, config: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(self._process_blocking, dataset_id, config)

    async def preview(self, dataset_id: int, config: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(self._preview_blocking, dataset_id, config)

    async def quality(self, dataset_id: int) -> Dict[str, Any]:
        return await asyncio.to_thread(self._quality_blocking, dataset_id)

    def _apply_pipeline(self, df: pl.DataFrame, config: Dict[str, Any]) -> tuple[pl.DataFrame, List[str]]:
        steps: List[str] = []
        if config.get("clean_missing", True):
            strategy = (config.get("missing_strategy") or "drop").lower()
            if strategy not in MISSING_STRATEGIES:
                strategy = "drop"
            df = DataCleaner.clean_missing_values(df, strategy=strategy)
            steps.append(f"clean_missing:{strategy}")

        if config.get("remove_duplicates", True):
            df = DataCleaner.remove_duplicates(df)
            steps.append("remove_duplicates")

        if config.get("normalize_strings", True):
            df = DataCleaner.clean_string_columns(df)
            steps.append("normalize_strings")

        if config.get("remove_outliers", False):
            numeric_cols = [c for c in df.columns if df[c].dtype in NUMERIC_DTYPES_SET]
            if numeric_cols:
                df = DataCleaner.remove_outliers(df, numeric_cols)
                steps.append("remove_outliers")

        return df, steps

    def _process_blocking(
        self, dataset_id: int, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        df = read_dataframe(path)
        rows_before = df.height
        df, steps = self._apply_pipeline(df, config)

        if df.height == 0:
            raise ValidationError("После очистки не осталось строк")

        buf = io.BytesIO()
        df.write_csv(buf)
        content = buf.getvalue()
        base_name = item.get("name") or f"dataset_{dataset_id}"
        new_record = dataset_store.save_dataset(
            original_filename=f"{base_name}_cleaned.csv",
            content=content,
            name=f"{base_name} (очищен)",
            description=f"ETL из набора #{dataset_id}: {', '.join(steps)}",
            content_type="text/csv",
        )
        dataset_store.patch_dataset_meta(
            new_record["id"],
            lineage={
                "type": "etl",
                "source_dataset_ids": [dataset_id],
                "source_name": item.get("name"),
                "steps": steps,
                "missing_strategy": config.get("missing_strategy", "drop"),
                "rows_before": rows_before,
                "rows_after": df.height,
            },
        )
        new_record = dataset_store.get_dataset(new_record["id"]) or new_record

        return {
            "source_dataset_id": dataset_id,
            "new_dataset": new_record,
            "rows_before": rows_before,
            "rows_after": df.height,
            "steps": steps,
            "missing_strategy": config.get("missing_strategy", "drop"),
        }

    def _preview_blocking(
        self, dataset_id: int, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        before = read_dataframe(path)
        after, steps = self._apply_pipeline(before.clone(), config)
        changes = DataCleaner.sample_cell_diffs(before, after)
        return {
            "dataset_id": dataset_id,
            "rows_before": before.height,
            "rows_after": after.height,
            "rows_removed": max(0, before.height - after.height),
            "steps": steps,
            "missing_strategy": config.get("missing_strategy", "drop"),
            "sample_changes": [
                {
                    "row": c["row"],
                    "column": c["column"],
                    "before": _to_py(c["before"]),
                    "after": _to_py(c["after"]),
                }
                for c in changes
            ],
        }

    def _quality_blocking(self, dataset_id: int) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        df = read_dataframe(path)
        rows = df.height
        cols = len(df.columns)
        total_cells = rows * cols if rows and cols else 0

        missing_by_col = {
            c: int(df[c].null_count()) for c in df.columns
        }
        missing_total = sum(missing_by_col.values())
        completeness = (
            round(1.0 - missing_total / total_cells, 4) if total_cells else 1.0
        )

        duplicate_rows = rows - df.unique().height
        uniqueness = round(1.0 - duplicate_rows / rows, 4) if rows else 1.0

        issues: List[Dict[str, Any]] = []
        for col, miss in missing_by_col.items():
            if miss and rows:
                pct = miss / rows
                if pct >= 0.05:
                    issues.append(
                        {
                            "type": "missing",
                            "column": col,
                            "ratio": round(pct, 4),
                            "message": f"Пропуски в «{col}»: {pct:.1%}",
                        }
                    )

        return {
            "dataset_id": dataset_id,
            "rows": rows,
            "columns": cols,
            "completeness": completeness,
            "uniqueness": uniqueness,
            "duplicate_rows": duplicate_rows,
            "missing_by_column": missing_by_col,
            "issues": issues,
        }
