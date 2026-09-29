"""Сервис интерактивного просмотра и выгрузки данных с фильтрами и агрегацией."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import polars as pl

from core.polars_utils import NUMERIC_DTYPES, to_py as _to_py
from core.exceptions import NotFoundError, ValidationError
from infrastructure.storage import dataset_store
from infrastructure.storage import column_values_cache
from infrastructure.storage.dataset_loader import load_dataset_df

FILTER_OPS = {
    "eq",
    "ne",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "is_null",
    "not_null",
    "in_list",
}

AGG_FUNCS = {"sum", "mean", "min", "max", "count", "n_unique"}


class ExportService:
    """Построение табличных выборок: фильтрация, группировка, агрегация, экспорт."""

    def _load(self, dataset_id: int) -> pl.DataFrame:
        """Загрузить DataFrame набора по ID."""
        return load_dataset_df(dataset_id)

    def _validate_columns(
        self, df: pl.DataFrame, columns: Sequence[str], label: str
    ) -> None:
        """Проверить, что все колонки существуют в DataFrame."""
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValidationError(f"Unknown {label} columns: {', '.join(missing)}")

    def _parse_in_list(self, value: Any) -> List[Any]:
        """Разобрать значение для оператора in_list (список или CSV-строка)."""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in text.split(",") if part.strip()]

    def _parse_between(self, value: Any) -> List[Any]:
        if value is None:
            raise ValidationError("between requires two values")
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [value[0], value[1]]
        if isinstance(value, dict):
            lo = value.get("from", value.get("min"))
            hi = value.get("to", value.get("max"))
            if lo is not None and hi is not None:
                return [lo, hi]
        text = str(value).strip()
        if ".." in text:
            parts = [p.strip() for p in text.split("..", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts
        if "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts
        raise ValidationError("between value must be [from, to] or 'from..to'")

    def _compare_value(self, df: pl.DataFrame, column: str, value: Any) -> Any:
        """Привести значение фильтра к типу колонки для сравнения."""
        dtype = df[column].dtype
        if dtype in NUMERIC_DTYPES:
            return float(value)
        if dtype == pl.Date:
            return date.fromisoformat(str(value).strip()[:10])
        if dtype == pl.Datetime:
            text = str(value).strip().replace(" ", "T")
            if len(text) == 10:
                text += "T00:00:00"
            return datetime.fromisoformat(text[:19])
        if dtype == pl.Boolean:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"true", "1", "yes", "да"}
        return str(value)

    def _filter_expr(self, df: pl.DataFrame, spec: Dict[str, Any]) -> pl.Expr:
        """Сформировать Polars-выражение для одного фильтра."""
        column = spec["column"]
        op = (spec.get("op") or "eq").lower()
        value = spec.get("value")

        if op not in FILTER_OPS:
            raise ValidationError(f"Unsupported filter op: {op}")

        col = pl.col(column)
        if op == "is_null":
            return col.is_null()
        if op == "not_null":
            return col.is_not_null()
        if op == "eq":
            if df[column].dtype == pl.Boolean:
                return col == self._compare_value(df, column, value)
            return col == value
        if op == "ne":
            if df[column].dtype == pl.Boolean:
                return col != self._compare_value(df, column, value)
            return col != value
        if op == "contains":
            return col.cast(pl.String).str.contains(str(value), literal=True)
        if op == "not_contains":
            return ~col.cast(pl.String).str.contains(str(value), literal=True)
        if op == "in_list":
            values = self._parse_in_list(value)
            return col.is_in(values)
        if op == "between":
            bounds = self._parse_between(value)
            lo = self._compare_value(df, column, bounds[0])
            hi = self._compare_value(df, column, bounds[1])
            if lo > hi:
                lo, hi = hi, lo
            return (col >= lo) & (col <= hi)
        if op in {"gt", "gte", "lt", "lte"}:
            cmp_val = self._compare_value(df, column, value)
            if op == "gt":
                return col > cmp_val
            if op == "gte":
                return col >= cmp_val
            if op == "lt":
                return col < cmp_val
            return col <= cmp_val

        raise ValidationError(f"Unsupported filter op: {op}")

    def apply_filters(
        self, df: pl.DataFrame, filters: Optional[List[Dict[str, Any]]]
    ) -> pl.DataFrame:
        """Применить список фильтров к DataFrame."""
        if not filters:
            return df
        exprs = []
        for spec in filters:
            if not spec.get("column"):
                continue
            self._validate_columns(df, [spec["column"]], "filter")
            exprs.append(self._filter_expr(df, spec))
        if not exprs:
            return df
        combined = exprs[0]
        for expr in exprs[1:]:
            combined = combined & expr
        return df.filter(combined)

    _apply_filters = apply_filters

    def _agg_expr(self, df: pl.DataFrame, spec: Dict[str, Any]) -> pl.Expr:
        """Сформировать выражение агрегации."""
        column = spec["column"]
        agg = (spec.get("agg") or "sum").lower()
        alias = spec.get("alias") or f"{column}__{agg}"

        if agg not in AGG_FUNCS:
            raise ValidationError(f"Unsupported aggregation: {agg}")

        if agg == "count":
            if column == "*" or column == "_all_":
                return pl.len().alias(alias)
            self._validate_columns(df, [column], "aggregation")
            return pl.col(column).count().alias(alias)
        if agg == "n_unique":
            self._validate_columns(df, [column], "aggregation")
            return pl.col(column).n_unique().alias(alias)

        self._validate_columns(df, [column], "aggregation")
        if df[column].dtype not in NUMERIC_DTYPES:
            raise ValidationError(f"Column '{column}' is not numeric for agg '{agg}'")

        mapping = {
            "sum": pl.col(column).sum(),
            "mean": pl.col(column).mean(),
            "min": pl.col(column).min(),
            "max": pl.col(column).max(),
        }
        return mapping[agg].alias(alias)

    def _apply_grouped(
        self,
        df: pl.DataFrame,
        group_by: List[str],
        aggregations: Optional[List[Dict[str, Any]]],
    ) -> pl.DataFrame:
        """Сгруппировать и агрегировать данные."""
        if not group_by:
            raise ValidationError("group_by is required for grouped mode")

        self._validate_columns(df, group_by, "group_by")
        aggs: List[pl.Expr] = []
        for spec in aggregations or []:
            if spec.get("column"):
                aggs.append(self._agg_expr(df, spec))

        if not aggs:
            aggs = [pl.len().alias("count")]

        return df.group_by(group_by).agg(aggs)

    def _apply_sort(
        self, df: pl.DataFrame, sort_by: Optional[str], sort_dir: str
    ) -> pl.DataFrame:
        """Отсортировать результат."""
        if not sort_by or sort_by not in df.columns:
            return df
        descending = (sort_dir or "asc").lower() == "desc"
        return df.sort(sort_by, descending=descending, nulls_last=True)

    def _rows_to_dicts(self, df: pl.DataFrame) -> List[Dict[str, Any]]:
        """Преобразовать DataFrame в список JSON-сериализуемых строк."""
        return [{k: _to_py(v) for k, v in row.items()} for row in df.to_dicts()]

    def query(
        self,
        dataset_id: int,
        *,
        mode: str = "raw",
        filters: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[List[str]] = None,
        aggregations: Optional[List[Dict[str, Any]]] = None,
        columns: Optional[List[str]] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Выполнить запрос к набору: фильтры, группировка или сырой просмотр."""
        mode = (mode or "raw").lower()
        if mode not in {"raw", "grouped"}:
            raise ValidationError("mode must be raw or grouped")

        limit = max(1, min(int(limit or 100), 1000))
        offset = max(0, int(offset or 0))

        df = self._load(dataset_id)
        source_rows = df.height
        filtered = self._apply_filters(df, filters)
        filtered_rows = filtered.height

        if mode == "grouped":
            result = self._apply_grouped(filtered, group_by or [], aggregations)
        else:
            selected = [c for c in (columns or []) if c]
            if selected:
                self._validate_columns(filtered, selected, "column")
                result = filtered.select(selected)
            else:
                result = filtered

        result = self._apply_sort(result, sort_by, sort_dir)
        total_result = result.height
        page = result.slice(offset, limit)

        payload = {
            "dataset_id": dataset_id,
            "mode": mode,
            "source_rows": source_rows,
            "filtered_rows": filtered_rows,
            "total_rows": total_result,
            "offset": offset,
            "limit": limit,
            "returned_rows": page.height,
            "columns": list(page.columns),
            "rows": self._rows_to_dicts(page),
            "filters_applied": len(filters or []),
            "group_by": group_by or [],
        }
        from core.result_limits import apply_result_limit_meta

        apply_result_limit_meta(
            payload,
            mode=mode,
            total_rows=total_result,
            returned_rows=page.height,
            limit=limit,
        )
        return payload

    def export_bytes(
        self,
        dataset_id: int,
        *,
        file_format: str = "csv",
        **query_kwargs: Any,
    ) -> Tuple[bytes, str, str]:
        """Сформировать файл выгрузки (csv/json/xlsx) по тем же параметрам запроса."""
        file_format = (file_format or "csv").lower()
        if file_format not in {"csv", "json", "xlsx"}:
            raise ValidationError("format must be csv, json or xlsx")

        # Экспорт без пагинации — все строки результата
        query_kwargs = dict(query_kwargs)
        query_kwargs["limit"] = 100_000
        query_kwargs["offset"] = 0
        data = self.query(dataset_id, **query_kwargs)

        item = dataset_store.get_dataset(dataset_id) or {}
        base = f"export_{dataset_id}_{item.get('name', 'data')}".replace(" ", "_")

        if file_format == "json":
            payload = json.dumps(
                {
                    "meta": {
                        k: data[k]
                        for k in (
                            "dataset_id",
                            "mode",
                            "source_rows",
                            "filtered_rows",
                            "total_rows",
                            "group_by",
                        )
                    },
                    "columns": data["columns"],
                    "rows": data["rows"],
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            return payload, "application/json", f"{base}.json"

        if file_format == "xlsx":
            df = pl.DataFrame(data["rows"], infer_schema_length=None)
            buf = io.BytesIO()
            try:
                df.write_excel(buf)
            except Exception as e:
                raise ValidationError(
                    "Экспорт XLSX недоступен: установите пакет xlsxwriter "
                    f"(`uv add xlsxwriter`). Детали: {e}"
                ) from e
            return buf.getvalue(), (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ), f"{base}.xlsx"

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(data["columns"])
        for row in data["rows"]:
            writer.writerow([row.get(c, "") for c in data["columns"]])
        return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"{base}.csv"

    def get_column_values(
        self,
        dataset_id: int,
        column: str,
        q: str = "",
        limit: int = 30,
    ) -> Dict[str, Any]:
        """Уникальные значения колонки для автодополнения фильтров."""
        limit = max(1, min(int(limit or 30), 100))
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        df = self._load(dataset_id)
        self._validate_columns(df, [column], "column")

        stat = path.stat()
        path_key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        values, total_unique, from_cache = column_values_cache.get_or_query(
            dataset_id=dataset_id,
            column=column,
            path_key=path_key,
            df=df,
            q=q or "",
            limit=limit,
        )
        return {
            "dataset_id": dataset_id,
            "column": column,
            "query": q or "",
            "values": values,
            "returned": len(values),
            "total_unique": total_unique,
            "truncated": len(values) >= limit or total_unique > len(values),
            "cached": from_cache,
        }
