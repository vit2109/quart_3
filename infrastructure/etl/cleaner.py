"""Расширенные стратегии очистки пропусков и дубликатов."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional

import polars as pl


class DataCleaner:
    @staticmethod
    def clean_missing_values(
        df: pl.DataFrame,
        strategy: str = "drop",
        fill_value: Optional[Any] = None,
    ) -> pl.DataFrame:
        strategy = (strategy or "drop").lower()
        if strategy == "drop":
            return df.drop_nulls()
        if strategy == "fill" and fill_value is not None:
            return df.fill_null(fill_value)
        if strategy in {"fill_zero", "zero"}:
            exprs = []
            for col in df.columns:
                if df[col].dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32]:
                    exprs.append(pl.col(col).fill_null(0).alias(col))
                else:
                    exprs.append(pl.col(col))
            return df.select(exprs) if exprs else df
        if strategy in {"fill_mean", "mean"}:
            exprs = []
            for col in df.columns:
                if df[col].dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32]:
                    mean_val = df[col].mean()
                    exprs.append(pl.col(col).fill_null(mean_val).alias(col))
                else:
                    exprs.append(pl.col(col))
            return df.select(exprs) if exprs else df
        if strategy in {"fill_median", "median"}:
            exprs = []
            for col in df.columns:
                if df[col].dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32]:
                    med = df[col].median()
                    exprs.append(pl.col(col).fill_null(med).alias(col))
                else:
                    exprs.append(pl.col(col))
            return df.select(exprs) if exprs else df
        if strategy in {"fill_unknown", "unknown"}:
            exprs = []
            for col in df.columns:
                if df[col].dtype == pl.String:
                    exprs.append(pl.col(col).fill_null("Unknown").alias(col))
                elif df[col].dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32]:
                    exprs.append(pl.col(col).fill_null(0).alias(col))
                elif df[col].dtype == pl.Boolean:
                    exprs.append(pl.col(col).fill_null(False).alias(col))
                else:
                    exprs.append(pl.col(col))
            return df.select(exprs) if exprs else df
        if strategy in {"forward_fill", "ffill"}:
            return df.fill_null(strategy="forward")
        # legacy fill with type defaults
        if strategy == "fill":
            for col in df.columns:
                if df[col].dtype == pl.String:
                    df = df.with_columns(pl.col(col).fill_null(""))
                elif df[col].dtype in [pl.Float64, pl.Int64]:
                    df = df.with_columns(pl.col(col).fill_null(0))
                elif df[col].dtype == pl.Datetime:
                    df = df.with_columns(pl.col(col).fill_null(datetime.now()))
        return df

    @staticmethod
    def remove_duplicates(df: pl.DataFrame, subset: Optional[List[str]] = None) -> pl.DataFrame:
        return df.unique(subset=subset)

    @staticmethod
    def clean_string_columns(df: pl.DataFrame) -> pl.DataFrame:
        for col in df.columns:
            if df[col].dtype == pl.String:
                df = df.with_columns(
                    pl.col(col)
                    .str.strip_chars()
                    .str.replace_all(r"\s+", " ")
                    .str.to_lowercase()
                    .alias(col)
                )
        return df

    @staticmethod
    def remove_outliers(
        df: pl.DataFrame,
        columns: List[str],
        method: str = "iqr",
        threshold: float = 1.5,
    ) -> pl.DataFrame:
        if method == "iqr":
            for col in columns:
                q1 = df[col].quantile(0.25)
                q3 = df[col].quantile(0.75)
                iqr = q3 - q1
                lower_bound = q1 - threshold * iqr
                upper_bound = q3 + threshold * iqr
                df = df.filter((pl.col(col) >= lower_bound) & (pl.col(col) <= upper_bound))
        return df

    @staticmethod
    def sample_cell_diffs(
        before: pl.DataFrame,
        after: pl.DataFrame,
        max_rows: int = 5,
        max_cells: int = 20,
    ) -> List[dict]:
        """Примеры изменённых ячеек (по индексу строки до min height)."""
        changes: List[dict] = []
        limit = min(before.height, after.height, max_rows)
        cols = [c for c in before.columns if c in after.columns]
        for i in range(limit):
            for col in cols:
                if len(changes) >= max_cells:
                    return changes
                b_val = before[col][i]
                a_val = after[col][i]
                if b_val != a_val and not (b_val is None and a_val is None):
                    changes.append(
                        {
                            "row": i + 1,
                            "column": col,
                            "before": b_val,
                            "after": a_val,
                        }
                    )
        return changes
