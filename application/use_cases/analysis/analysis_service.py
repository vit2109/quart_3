"""Сервис аналитических операций над наборами данных (Polars).

Поддерживаемые методы: описательная статистика, корреляции Pearson/Spearman,
поиск аномалий по Z-score, базовый прогноз временного ряда, KPI-агрегации.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import polars as pl

from core.exceptions import NotFoundError, ValidationError
from core.polars_utils import NUMERIC_DTYPES, stringify_row as _stringify_row, to_py as _to_py
from infrastructure.storage.dataset_loader import load_dataset_df

CHART_TYPES = {"bar", "horizontal_bar", "line", "pie", "doughnut"}


class AnalysisService:
    """Оркестратор аналитических запросов к загруженным наборам данных."""

    def _load(self, dataset_id: int) -> pl.DataFrame:
        """Загрузить DataFrame по ID набора из файлового хранилища."""
        return load_dataset_df(dataset_id)

    def _pick_columns(
        self, df: pl.DataFrame, columns: Optional[List[str]]
    ) -> List[str]:
        """Проверить и вернуть список колонок; все — если columns пуст."""
        if not columns:
            return list(df.columns)
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValidationError(f"Unknown columns: {', '.join(missing)}")
        return columns

    def _filtered(
        self, dataset_id: int, filters: Optional[List[Dict[str, Any]]]
    ) -> tuple:
        """Один load: отфильтрованный DF, исходное число строк, число фильтров."""
        from application.use_cases.export.export_service import ExportService

        df = self._load(dataset_id)
        specs = [f for f in (filters or []) if f.get("column")]
        filtered = ExportService().apply_filters(df, specs)
        return filtered, df.height, len(specs)

    def _apply_filters(
        self, dataset_id: int, filters: Optional[List[Dict[str, Any]]]
    ) -> pl.DataFrame:
        filtered, _, _ = self._filtered(dataset_id, filters)
        return filtered

    async def get_statistics(
        self,
        dataset_id: int,
        columns: Optional[List[str]] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._get_statistics_blocking, dataset_id, columns, filters
        )

    def _get_statistics_blocking(
        self,
        dataset_id: int,
        columns: Optional[List[str]] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        df, source_rows, n_filters = self._filtered(dataset_id, filters)
        stats = self._statistics_from_df(df, dataset_id, columns)
        if n_filters:
            stats["source_rows"] = source_rows
            stats["filtered_rows"] = df.height
            stats["filters_applied"] = n_filters
        return stats

    async def get_correlations(
        self,
        dataset_id: int,
        method: str = "pearson",
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._get_correlations_blocking, dataset_id, method, filters
        )

    def _get_correlations_blocking(
        self,
        dataset_id: int,
        method: str = "pearson",
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        df, source_rows, n_filters = self._filtered(dataset_id, filters)
        result = self._correlations_from_df(df, dataset_id, method)
        if n_filters:
            result["source_rows"] = source_rows
            result["filtered_rows"] = df.height
        return result

    def _statistics_from_df(
        self,
        df: pl.DataFrame,
        dataset_id: int,
        columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        cols = self._pick_columns(df, columns)
        stats: Dict[str, Any] = {}

        for col in cols:
            s = df[col]
            dtype = s.dtype
            entry: Dict[str, Any] = {
                "dtype": str(dtype),
                "count": int(s.len()),
                "missing": int(s.null_count()),
            }
            if dtype in NUMERIC_DTYPES:
                entry.update(
                    {
                        "mean": _to_py(s.mean()),
                        "median": _to_py(s.median()),
                        "std": _to_py(s.std()),
                        "min": _to_py(s.min()),
                        "max": _to_py(s.max()),
                        "q25": _to_py(s.quantile(0.25)),
                        "q75": _to_py(s.quantile(0.75)),
                    }
                )
            elif dtype == pl.String:
                modes = s.drop_nulls().mode().to_list()[:5]
                entry.update(
                    {
                        "unique": int(s.n_unique()),
                        "most_common": modes,
                    }
                )
            else:
                entry["unique"] = int(s.n_unique())
            stats[col] = entry

        return {
            "dataset_id": dataset_id,
            "rows": df.height,
            "columns": cols,
            "stats": stats,
        }

    def _correlations_from_df(
        self, df: pl.DataFrame, dataset_id: int, method: str = "pearson"
    ) -> Dict[str, Any]:
        numeric_cols = [c for c in df.columns if df[c].dtype in NUMERIC_DTYPES]
        if len(numeric_cols) < 2:
            return {
                "dataset_id": dataset_id,
                "method": method,
                "columns": numeric_cols,
                "matrix": {},
            }

        work = df.select(numeric_cols).drop_nulls()
        if method == "spearman":
            work = work.with_columns(
                [pl.col(c).rank().alias(c) for c in numeric_cols]
            )

        corr_df = work.corr()
        matrix: Dict[str, Dict[str, Any]] = {c: {} for c in numeric_cols}
        for i, row in enumerate(corr_df.to_dicts()):
            if i >= len(numeric_cols):
                break
            row_name = numeric_cols[i]
            for col in numeric_cols:
                val = row.get(col)
                matrix[row_name][col] = (
                    None if val is None else round(float(val), 6)
                )

        return {
            "dataset_id": dataset_id,
            "method": method,
            "columns": numeric_cols,
            "matrix": matrix,
        }

    def _detect_anomalies_from_df(
        self,
        df: pl.DataFrame,
        dataset_id: int,
        columns: List[str],
        contamination: float = 0.1,
    ) -> Dict[str, Any]:
        cols = self._pick_columns(df, columns)
        numeric_cols = [c for c in cols if df[c].dtype in NUMERIC_DTYPES]
        if not numeric_cols:
            raise ValidationError("Select at least one numeric column")

        work = df.select(numeric_cols).drop_nulls()
        if work.height == 0:
            return {
                "dataset_id": dataset_id,
                "columns": numeric_cols,
                "contamination": contamination,
                "anomaly_count": 0,
                "anomalies": [],
            }

        z_parts = []
        for col in numeric_cols:
            series = work[col].cast(pl.Float64)
            mean = series.mean()
            std = series.std()
            if mean is None or not std:
                z_parts.append(pl.lit(0.0).alias(f"z_{col}"))
            else:
                z_parts.append(
                    ((series - mean).abs() / std).fill_null(0.0).alias(f"z_{col}")
                )

        scored = work.with_columns(z_parts)
        z_cols = [f"z_{c}" for c in numeric_cols]
        scored = scored.with_columns(
            pl.max_horizontal([pl.col(c) for c in z_cols]).alias("score")
        )
        threshold = scored["score"].quantile(1.0 - contamination) or 0.0
        anomalies_df = (
            scored.filter(pl.col("score") >= threshold)
            .sort("score", descending=True)
            .head(100)
        )
        anomaly_count = int(scored.filter(pl.col("score") >= threshold).height)
        anomalies = [_stringify_row(r) for r in anomalies_df.to_dicts()]
        return {
            "dataset_id": dataset_id,
            "columns": numeric_cols,
            "contamination": contamination,
            "anomaly_count": anomaly_count,
            "anomalies": anomalies,
        }

    async def detect_anomalies(
        self,
        dataset_id: int,
        columns: List[str],
        contamination: float = 0.1,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._detect_anomalies_blocking,
            dataset_id,
            columns,
            contamination,
            filters,
        )

    def _detect_anomalies_blocking(
        self,
        dataset_id: int,
        columns: List[str],
        contamination: float = 0.1,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        df, source_rows, n_filters = self._filtered(dataset_id, filters)
        result = self._detect_anomalies_from_df(
            df, dataset_id, columns, contamination
        )
        if n_filters:
            result["source_rows"] = source_rows
            result["filtered_rows"] = df.height
        return result

    async def forecast(
        self,
        dataset_id: int,
        date_col: str,
        target_col: str,
        periods: int = 30,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._forecast_blocking, dataset_id, date_col, target_col, periods
        )

    def _forecast_blocking(
        self,
        dataset_id: int,
        date_col: str,
        target_col: str,
        periods: int = 30,
    ) -> Dict[str, Any]:
        df = self._load(dataset_id)
        if date_col not in df.columns or target_col not in df.columns:
            raise ValidationError("date_col/target_col not found in dataset")

        work = (
            df.select([date_col, target_col])
            .drop_nulls()
            .sort(date_col)
        )
        if work.height < 2:
            raise ValidationError("Not enough rows for forecast")

        values = work[target_col].cast(pl.Float64)
        mean = float(values.mean() or 0.0)
        recent = values.tail(min(7, values.len())).mean() or mean
        last = float(values[-1])
        drift = (last - float(values[0])) / max(values.len() - 1, 1)

        last_date = work[date_col][-1]
        forecast_rows = []
        for i in range(1, periods + 1):
            forecast_rows.append(
                {
                    "step": i,
                    "yhat": round(float(recent) + drift * i, 4),
                    "baseline_mean": round(mean, 4),
                }
            )

        return {
            "dataset_id": dataset_id,
            "date_col": date_col,
            "target_col": target_col,
            "periods": periods,
            "last_date": str(last_date),
            "method": "baseline_drift",
            "forecast": forecast_rows,
        }

    async def calculate_kpis(
        self,
        dataset_id: int,
        kpi_definitions: Dict[str, Dict[str, Any]],
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._calculate_kpis_blocking, dataset_id, kpi_definitions, filters
        )

    def _calculate_kpis_blocking(
        self,
        dataset_id: int,
        kpi_definitions: Dict[str, Dict[str, Any]],
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        df, source_rows, n_filters = self._filtered(dataset_id, filters)
        results: Dict[str, Any] = {}
        for name, spec in kpi_definitions.items():
            if name not in df.columns:
                results[name] = {"error": "column not found"}
                continue
            agg = (spec or {}).get("agg", "sum")
            series = df[name]
            if series.dtype not in NUMERIC_DTYPES:
                results[name] = {"error": "column is not numeric"}
                continue
            value = {
                "sum": series.sum(),
                "mean": series.mean(),
                "min": series.min(),
                "max": series.max(),
                "count": series.len(),
            }.get(agg, series.sum())
            results[name] = {"agg": agg, "value": _to_py(value)}
        payload: Dict[str, Any] = {"dataset_id": dataset_id, "kpis": results}
        if n_filters:
            payload["source_rows"] = source_rows
            payload["filtered_rows"] = df.height
        return payload

    async def explore(
        self,
        dataset_id: int,
        *,
        mode: str = "grouped",
        filters: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[List[str]] = None,
        aggregations: Optional[List[Dict[str, Any]]] = None,
        columns: Optional[List[str]] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        limit: int = 200,
        chart: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._explore_blocking,
            dataset_id,
            mode=mode,
            filters=filters,
            group_by=group_by,
            aggregations=aggregations,
            columns=columns,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            chart=chart,
        )

    def _explore_blocking(
        self,
        dataset_id: int,
        *,
        mode: str = "grouped",
        filters: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[List[str]] = None,
        aggregations: Optional[List[Dict[str, Any]]] = None,
        columns: Optional[List[str]] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        limit: int = 200,
        chart: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from application.use_cases.export.export_service import ExportService

        export = ExportService()
        mode = (mode or "grouped").lower()
        if mode not in {"raw", "grouped"}:
            raise ValidationError("mode must be raw or grouped")

        limit = max(1, min(int(limit or 200), 2000))
        df = self._load(dataset_id)
        source_rows = df.height
        filtered = export.apply_filters(df, [f for f in (filters or []) if f.get("column")])
        filtered_rows = filtered.height

        if mode == "grouped":
            if not group_by:
                raise ValidationError("group_by is required for grouped mode")
            result = export._apply_grouped(filtered, group_by, aggregations)
        else:
            selected = [c for c in (columns or []) if c]
            if selected:
                export._validate_columns(filtered, selected, "column")
                result = filtered.select(selected)
            else:
                result = filtered

        result = export._apply_sort(result, sort_by, sort_dir)
        total_rows = result.height
        page = result.head(limit)
        rows = export._rows_to_dicts(page)

        chart_spec = None
        if chart and chart.get("enabled") and rows:
            chart_spec = self._build_explore_chart(rows, chart)

        payload = {
            "dataset_id": dataset_id,
            "mode": mode,
            "source_rows": source_rows,
            "filtered_rows": filtered_rows,
            "total_rows": total_rows,
            "returned_rows": len(rows),
            "columns": list(page.columns),
            "rows": rows,
            "filters_applied": len([f for f in (filters or []) if f.get("column")]),
            "group_by": group_by or [],
            "aggregations": aggregations or [],
            "chart": chart_spec,
        }
        from core.result_limits import apply_result_limit_meta

        apply_result_limit_meta(
            payload,
            mode=mode,
            total_rows=total_rows,
            returned_rows=len(rows),
            limit=limit,
        )
        return payload

    def _resolve_row_column(self, row: Dict[str, Any], col: str) -> Any:
        """Найти значение колонки с учётом алиасов агрегации (col__sum и т.д.)."""
        if not col:
            return None
        if col in row:
            return row[col]
        prefix = f"{col}__"
        for key, value in row.items():
            if key.startswith(prefix):
                return value
        return None

    def _build_explore_chart(
        self, rows: List[Dict[str, Any]], chart: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        ctype = (chart.get("type") or "bar").lower()
        if ctype not in CHART_TYPES:
            ctype = "bar"
        label_col = chart.get("label_column")
        value_col = chart.get("value_column")
        if not label_col or not value_col:
            return None

        top_n = max(3, min(int(chart.get("top_n") or 30), 100))
        source = rows[:top_n]
        labels: List[str] = []
        values: List[float] = []
        value_label = value_col
        for row in source:
            label_val = self._resolve_row_column(row, label_col)
            raw_val = self._resolve_row_column(row, value_col)
            if raw_val is None:
                for key in row:
                    if key != label_col and not str(key).startswith(f"{label_col}__"):
                        if key.startswith(f"{value_col}__") or (
                            value_col not in row and "__" in key
                        ):
                            raw_val = row[key]
                            value_label = key
                            break
            labels.append(str(label_val if label_val is not None else ""))
            try:
                values.append(float(raw_val or 0))
            except (TypeError, ValueError):
                values.append(0.0)

        if not labels:
            return None

        chart_js_type = {
            "bar": "bar",
            "horizontal_bar": "bar",
            "line": "line",
            "pie": "pie",
            "doughnut": "doughnut",
        }.get(ctype, "bar")

        return {
            "title": chart.get("title") or f"{value_label} по {label_col}",
            "type": chart_js_type,
            "index_axis": "y" if ctype == "horizontal_bar" else "x",
            "labels": labels,
            "datasets": [{"label": str(value_label), "data": values}],
        }

    async def timeseries(
        self,
        dataset_id: int,
        date_col: str,
        metrics: List[str],
        *,
        granularity: str = "day",
        agg: str = "sum",
        filters: Optional[List[Dict[str, Any]]] = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._timeseries_blocking,
            dataset_id,
            date_col,
            metrics,
            granularity,
            agg,
            filters,
            limit,
        )

    def _timeseries_blocking(
        self,
        dataset_id: int,
        date_col: str,
        metrics: List[str],
        granularity: str = "day",
        agg: str = "sum",
        filters: Optional[List[Dict[str, Any]]] = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        if not metrics:
            raise ValidationError("At least one metric is required")

        granularity = (granularity or "day").lower()
        if granularity not in {"day", "week", "month"}:
            raise ValidationError("granularity must be day, week or month")

        agg = (agg or "sum").lower()
        if agg not in {"sum", "mean", "min", "max", "count"}:
            raise ValidationError("agg must be sum, mean, min, max or count")

        limit = max(10, min(int(limit or 500), 2000))
        df, source_rows, _ = self._filtered(dataset_id, filters)

        if date_col not in df.columns:
            raise ValidationError(f"Column '{date_col}' not found")

        work = self._with_parsed_dates(df, date_col)
        if work[date_col].dtype not in (pl.Date, pl.Datetime):
            raise ValidationError(f"Column '{date_col}' is not a date/datetime column")

        metric_cols = self._pick_numeric_columns(work, metrics)

        period_expr = self._period_expr(date_col, granularity)
        grouped = (
            work.with_columns(period_expr.alias("_period"))
            .filter(pl.col("_period").is_not_null())
            .group_by("_period")
            .agg(self._ts_agg_exprs(metric_cols, agg))
            .sort("_period")
            .head(limit)
        )

        periods = [_to_py(v) for v in grouped["_period"].to_list()]
        series: Dict[str, List[Any]] = {}
        table_rows: List[Dict[str, Any]] = []

        for mc in metric_cols:
            alias = f"{mc}__{agg}"
            vals = [_to_py(v) for v in grouped[alias].to_list()]
            series[mc] = vals

        for i, period in enumerate(periods):
            row: Dict[str, Any] = {"period": period}
            for mc in metric_cols:
                alias = f"{mc}__{agg}"
                row[mc] = _to_py(grouped[alias][i])
            if i > 0:
                prev = table_rows[i - 1]
                for mc in metric_cols:
                    cur_v = row.get(mc)
                    prev_v = prev.get(mc)
                    if isinstance(cur_v, (int, float)) and isinstance(prev_v, (int, float)) and prev_v:
                        row[f"{mc}__delta_pct"] = round(100.0 * (cur_v - prev_v) / prev_v, 2)
                    else:
                        row[f"{mc}__delta_pct"] = None
            else:
                for mc in metric_cols:
                    row[f"{mc}__delta_pct"] = None
            table_rows.append(row)

        chart_datasets = [
            {"label": mc, "data": series[mc]} for mc in metric_cols
        ]

        return {
            "dataset_id": dataset_id,
            "date_col": date_col,
            "granularity": granularity,
            "agg": agg,
            "metrics": metric_cols,
            "source_rows": source_rows,
            "filtered_rows": df.height,
            "periods": periods,
            "series": series,
            "rows": table_rows,
            "chart": {
                "type": "line",
                "labels": [str(p) for p in periods],
                "datasets": chart_datasets,
                "title": f"Динамика ({agg}) · {granularity}",
            },
        }

    async def pareto(
        self,
        dataset_id: int,
        group_by: List[str],
        metric: str,
        *,
        agg: str = "sum",
        top_n: int = 20,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._pareto_blocking,
            dataset_id,
            group_by,
            metric,
            agg,
            top_n,
            filters,
        )

    def _pareto_blocking(
        self,
        dataset_id: int,
        group_by: List[str],
        metric: str,
        agg: str = "sum",
        top_n: int = 20,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        group_by = [c for c in (group_by or []) if c]
        if not group_by:
            raise ValidationError("At least one group_by column is required")
        if not metric:
            raise ValidationError("metric is required")

        agg = (agg or "sum").lower()
        if agg not in {"sum", "mean", "count"}:
            raise ValidationError("agg must be sum, mean or count")

        top_n = max(5, min(int(top_n or 20), 100))
        df, source_rows, _ = self._filtered(dataset_id, filters)

        for col in [*group_by, metric]:
            if col not in df.columns:
                raise ValidationError(f"Column '{col}' not found")

        if agg == "count":
            value_expr = pl.len().alias("_value")
        elif agg == "mean":
            value_expr = pl.col(metric).mean().alias("_value")
        else:
            value_expr = pl.col(metric).sum().alias("_value")

        full_grouped = (
            df.filter(pl.col(metric).is_not_null() if agg != "count" else pl.lit(True))
            .group_by(group_by)
            .agg(value_expr)
        )
        if full_grouped.height == 0:
            return {
                "dataset_id": dataset_id,
                "group_by": group_by,
                "metric": metric,
                "agg": agg,
                "top_n": top_n,
                "hhi": 0.0,
                "source_rows": source_rows,
                "filtered_rows": df.height,
                "rows": [],
                "chart": None,
                "insights": ["Нет данных для Pareto-анализа."],
            }

        total_all = float(full_grouped["_value"].sum() or 0)
        if total_all > 0:
            hhi = float(
                full_grouped.with_columns((pl.col("_value") / total_all).alias("p"))
                .select((pl.col("p") ** 2).sum())
                .item()
            )
        else:
            hhi = 0.0

        ranked = full_grouped.sort("_value", descending=True).head(top_n)
        rows: List[Dict[str, Any]] = []
        cum_share = 0.0
        for r in ranked.to_dicts():
            val = float(r.get("_value") or 0)
            share = 100.0 * val / total_all if total_all else 0.0
            cum_share += share
            item = {g: _to_py(r.get(g)) for g in group_by}
            item[metric] = _to_py(val)
            item["share_%"] = round(share, 2)
            item["cum_share_%"] = round(cum_share, 2)
            rows.append(item)

        labels = [
            " / ".join(str(item.get(g, "")) for g in group_by) for item in rows
        ]
        chart = {
            "type": "pareto",
            "labels": labels,
            "datasets": [
                {"label": f"{metric} ({agg})", "data": [row[metric] for row in rows]},
                {
                    "label": "Накопленная доля %",
                    "data": [row["cum_share_%"] for row in rows],
                    "chartType": "line",
                },
            ],
            "title": f"Pareto · {metric} ({agg})",
        }

        insights: List[str] = []
        if rows:
            top = rows[0]
            glabel = " / ".join(str(top.get(g, "")) for g in group_by)
            insights.append(
                f"Лидер «{glabel}»: {top[metric]} ({top['share_%']}% от суммы)."
            )
            at80 = next((r for r in rows if r["cum_share_%"] >= 80), None)
            if at80:
                n = rows.index(at80) + 1
                insights.append(
                    f"Правило 80/20: {n} групп(ы) дают ≥80% ({at80['cum_share_%']}%)."
                )
        if hhi >= 0.18:
            insights.append(
                f"Высокая концентрация (HHI={round(hhi, 3)}): доминируют немногие группы."
            )
        elif hhi > 0:
            insights.append(f"Индекс концентрации HHI={round(hhi, 3)}.")

        return {
            "dataset_id": dataset_id,
            "group_by": group_by,
            "metric": metric,
            "agg": agg,
            "top_n": top_n,
            "hhi": round(hhi, 4),
            "source_rows": source_rows,
            "filtered_rows": df.height,
            "rows": rows,
            "chart": chart,
            "insights": insights,
        }

    @staticmethod
    def _period_expr(date_col: str, granularity: str) -> pl.Expr:
        col = pl.col(date_col)
        if granularity == "day":
            return col.dt.date().cast(pl.String)
        if granularity == "week":
            return col.dt.truncate("1w").cast(pl.String)
        return col.dt.truncate("1mo").cast(pl.String)

    @staticmethod
    def _ts_agg_exprs(metric_cols: List[str], agg: str) -> List[pl.Expr]:
        exprs: List[pl.Expr] = []
        for mc in metric_cols:
            c = pl.col(mc)
            if agg == "sum":
                exprs.append(c.sum().alias(f"{mc}__sum"))
            elif agg == "mean":
                exprs.append(c.mean().alias(f"{mc}__mean"))
            elif agg == "min":
                exprs.append(c.min().alias(f"{mc}__min"))
            elif agg == "max":
                exprs.append(c.max().alias(f"{mc}__max"))
            else:
                exprs.append(c.count().alias(f"{mc}__count"))
        return exprs

    async def compare_periods(
        self,
        dataset_id: int,
        date_col: str,
        period_a: Dict[str, str],
        period_b: Dict[str, str],
        metrics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._compare_periods_blocking,
            dataset_id,
            date_col,
            period_a,
            period_b,
            metrics,
        )

    def _compare_periods_blocking(
        self,
        dataset_id: int,
        date_col: str,
        period_a: Dict[str, str],
        period_b: Dict[str, str],
        metrics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        df = self._load(dataset_id)
        if date_col not in df.columns:
            raise ValidationError(f"Column '{date_col}' not found")

        work = self._with_parsed_dates(df, date_col)
        date_series = work[date_col]
        if date_series.dtype not in (pl.Date, pl.Datetime):
            raise ValidationError(f"Column '{date_col}' is not a date/datetime column")

        a_from = _parse_boundary(period_a.get("from") or period_a.get("from_date"))
        a_to = _parse_boundary(period_a.get("to") or period_a.get("to_date"), end_of_day=True)
        b_from = _parse_boundary(period_b.get("from") or period_b.get("from_date"))
        b_to = _parse_boundary(period_b.get("to") or period_b.get("to_date"), end_of_day=True)

        if metrics:
            metric_cols = self._pick_numeric_columns(work, metrics)
        else:
            metric_cols = [
                c for c in work.columns
                if c != date_col and work[c].dtype in NUMERIC_DTYPES
            ]
        if not metric_cols:
            raise ValidationError("No numeric metrics to compare")

        df_a = _filter_period(work, date_col, a_from, a_to)
        df_b = _filter_period(work, date_col, b_from, b_to)
        if df_a.height == 0 or df_b.height == 0:
            raise ValidationError("One or both periods contain no rows")

        comparisons: List[Dict[str, Any]] = []
        for col in metric_cols:
            stats_a = _metric_stats(df_a[col])
            stats_b = _metric_stats(df_b[col])
            comparisons.append(
                {
                    "column": col,
                    "period_a": stats_a,
                    "period_b": stats_b,
                    "delta": _delta(stats_a, stats_b),
                }
            )

        return {
            "dataset_id": dataset_id,
            "date_col": date_col,
            "period_a": {
                "from": str(a_from.date()) if hasattr(a_from, "date") else str(a_from),
                "to": str(a_to.date()) if hasattr(a_to, "date") else str(a_to),
                "row_count": df_a.height,
            },
            "period_b": {
                "from": str(b_from.date()) if hasattr(b_from, "date") else str(b_from),
                "to": str(b_to.date()) if hasattr(b_to, "date") else str(b_to),
                "row_count": df_b.height,
            },
            "metrics": comparisons,
        }

    def _pick_numeric_columns(
        self, df: pl.DataFrame, columns: List[str]
    ) -> List[str]:
        cols = self._pick_columns(df, columns)
        numeric = [c for c in cols if df[c].dtype in NUMERIC_DTYPES]
        if not numeric:
            raise ValidationError("Selected columns are not numeric")
        return numeric

    def _with_parsed_dates(self, df: pl.DataFrame, date_col: str) -> pl.DataFrame:
        series = df[date_col]
        if series.dtype in (pl.Date, pl.Datetime):
            return df
        if series.dtype == pl.Utf8:
            parsed = series.str.to_datetime(strict=False)
        else:
            parsed = series.cast(pl.Datetime, strict=False)
        if parsed.null_count() == series.len():
            parsed = series.str.to_datetime(strict=False)
        return df.with_columns(parsed.alias(date_col))


def _parse_boundary(value: str, end_of_day: bool = False):
    from datetime import datetime as dt

    if not value:
        raise ValidationError("Period boundary is required")
    text = str(value).strip()
    if len(text) <= 10:
        parsed = dt.fromisoformat(text)
        if end_of_day:
            return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed
    return dt.fromisoformat(text.replace("Z", "+00:00"))


def _filter_period(
    df: pl.DataFrame, date_col: str, start, end
) -> pl.DataFrame:
    col = pl.col(date_col)
    if df[date_col].dtype == pl.Date:
        start_val = start.date() if hasattr(start, "date") else start
        end_val = end.date() if hasattr(end, "date") else end
        return df.filter((col >= start_val) & (col <= end_val))
    return df.filter((col >= start) & (col <= end))


def _metric_stats(series: pl.Series) -> Dict[str, Any]:
    numeric = series.cast(pl.Float64, strict=False).drop_nulls()
    if numeric.len() == 0:
        return {"sum": 0.0, "mean": 0.0, "count": 0}
    return {
        "sum": round(float(numeric.sum() or 0.0), 4),
        "mean": round(float(numeric.mean() or 0.0), 4),
        "count": int(numeric.len()),
    }


def _delta(stats_a: Dict[str, Any], stats_b: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in ("sum", "mean", "count"):
        a_val = stats_a.get(key, 0)
        b_val = stats_b.get(key, 0)
        diff = b_val - a_val if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)) else None
        result[key] = round(diff, 4) if diff is not None else None
        if key != "count" and a_val not in (0, None) and diff is not None:
            result[f"{key}_pct"] = round((diff / a_val) * 100, 2)
        elif key != "count":
            result[f"{key}_pct"] = None
    return result
