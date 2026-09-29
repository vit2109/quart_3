from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

import polars as pl

from application.use_cases.analysis.analysis_service import (
    NUMERIC_DTYPES,
    AnalysisService,
    _to_py,
)
from application.use_cases.export.export_service import ExportService
from core.exceptions import NotFoundError, ValidationError
from infrastructure.storage import dataset_store, report_store


CHART_TYPES = {
    "bar",
    "horizontal_bar",
    "line",
    "pie",
    "doughnut",
    "histogram",
    "scatter",
    "radar",
}


class ReportService:
    """Генерация отчётов: обзор, статистика, группировка, паттерны, Chart.js specs."""

    def __init__(self) -> None:
        self.analysis = AnalysisService()
        self.export = ExportService()

    async def generate(
        self,
        dataset_id: int,
        report_type: str = "summary",
        *,
        group_by: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        top_n: int = 10,
        chart_types: Optional[List[str]] = None,
        chart_metric: Optional[str] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            lambda: self._generate_blocking(
                dataset_id,
                report_type,
                group_by=group_by,
                metrics=metrics,
                top_n=top_n,
                chart_types=chart_types,
                chart_metric=chart_metric,
                filters=filters,
            )
        )

    def _generate_blocking(
        self,
        dataset_id: int,
        report_type: str = "summary",
        *,
        group_by: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        top_n: int = 10,
        chart_types: Optional[List[str]] = None,
        chart_metric: Optional[str] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")

        report_type = (report_type or "summary").lower()
        if report_type not in {"summary", "full", "executive"}:
            raise ValidationError("report_type must be summary, full or executive")

        top_n = max(3, min(int(top_n or 10), 50))
        group_by = [c for c in (group_by or []) if c]
        metrics = [c for c in (metrics or []) if c]
        chart_types = [c for c in (chart_types or ["bar", "histogram", "pie"]) if c in CHART_TYPES]
        if not chart_types:
            chart_types = ["bar", "histogram"]

        df = self.analysis._load(dataset_id)
        source_rows = df.height
        filter_specs = [f for f in (filters or []) if f.get("column")]
        df = self.export.apply_filters(df, filter_specs)
        filtered_rows = df.height

        self._validate_columns(df, group_by, "group_by")
        self._validate_columns(df, metrics, "metrics")

        numeric_cols = [c for c in df.columns if df[c].dtype in NUMERIC_DTYPES]
        cat_cols = [
            c
            for c in df.columns
            if c not in numeric_cols and df[c].dtype in (pl.String, pl.Categorical, pl.Boolean, pl.Date, pl.Datetime)
        ]

        if not group_by:
            # Автовыбор: первая категориальная / строковая колонка
            if cat_cols:
                group_by = [cat_cols[0]]
            elif df.columns:
                group_by = [df.columns[0]]

        if not metrics:
            metrics = [c for c in numeric_cols if c not in group_by][:6]
        else:
            metrics = [c for c in metrics if c not in group_by]

        stats = self.analysis._statistics_from_df(df, dataset_id)
        tables: List[Dict[str, Any]] = []
        charts: List[Dict[str, Any]] = []
        insights: List[str] = []

        if filter_specs and filtered_rows < source_rows:
            insights.append(
                f"Применено фильтров: {len(filter_specs)}. "
                f"Анализ по {filtered_rows} из {source_rows} строк."
            )

        overview_rows = [
            {"Показатель": "Набор данных", "Значение": item.get("name")},
            {"Показатель": "Файл", "Значение": item.get("filename")},
            {"Показатель": "Строк (всего)", "Значение": source_rows},
            {"Показатель": "Строк (после фильтров)", "Значение": filtered_rows},
            {"Показатель": "Колонок", "Значение": len(stats.get("columns") or [])},
            {"Показатель": "Тип отчёта", "Значение": report_type},
            {"Показатель": "Фильтры", "Значение": self._format_filters(filter_specs)},
            {"Показатель": "Группировка", "Значение": ", ".join(group_by) or "—"},
            {"Показатель": "Метрики", "Значение": ", ".join(metrics) or "—"},
            {"Показатель": "Топ N", "Значение": top_n},
        ]
        tables.append(
            {
                "title": "Обзор",
                "columns": ["Показатель", "Значение"],
                "rows": overview_rows,
            }
        )

        # Базовая статистика
        stats_rows: List[Dict[str, Any]] = []
        for col_name, meta in (stats.get("stats") or {}).items():
            stats_rows.append(
                {
                    "Колонка": col_name,
                    "Тип": meta.get("dtype"),
                    "Всего": meta.get("count"),
                    "Пропуски": meta.get("missing"),
                    "Уникальных": meta.get("unique"),
                    "Среднее": meta.get("mean"),
                    "Мин": meta.get("min"),
                    "Макс": meta.get("max"),
                }
            )
        tables.append(
            {
                "title": "Статистика по колонкам",
                "columns": [
                    "Колонка",
                    "Тип",
                    "Всего",
                    "Пропуски",
                    "Уникальных",
                    "Среднее",
                    "Мин",
                    "Макс",
                ],
                "rows": stats_rows,
            }
        )

        # Группировка + агрегация + топ
        grouped = self._grouped_aggregates(df, group_by, metrics, top_n)
        if grouped["table"]:
            tables.append(grouped["table"])
            insights.extend(grouped.get("insights") or [])

        # Топ по каждой метрике
        for top_table in grouped.get("top_tables") or []:
            tables.append(top_table)

        # Скрытые закономерности
        patterns = self._hidden_patterns(df, group_by, metrics, numeric_cols)
        if patterns["rows"]:
            tables.append(
                {
                    "title": "Скрытые / неочевидные закономерности",
                    "columns": ["Тип", "Описание", "Сила / значение"],
                    "rows": patterns["rows"],
                }
            )
            insights.extend(patterns.get("insights") or [])

        if report_type in {"full", "executive"}:
            corr = self.analysis._correlations_from_df(df, dataset_id, "pearson")
            corr_cols = corr.get("columns") or []
            matrix = corr.get("matrix") or {}
            if corr_cols:
                corr_rows = []
                for left in corr_cols:
                    row = {"Колонка": left}
                    for right in corr_cols:
                        row[right] = (matrix.get(left) or {}).get(right)
                    corr_rows.append(row)
                tables.append(
                    {
                        "title": "Корреляции (Pearson)",
                        "columns": ["Колонка", *corr_cols],
                        "rows": corr_rows,
                    }
                )

        if report_type == "full" and metrics:
            anomalies = self.analysis._detect_anomalies_from_df(
                df, dataset_id, metrics[:5], contamination=0.05
            )
            anomaly_rows = anomalies.get("anomalies") or []
            if anomaly_rows:
                columns = list(anomaly_rows[0].keys())
                tables.append(
                    {
                        "title": f"Аномалии (топ {len(anomaly_rows)})",
                        "columns": columns,
                        "rows": anomaly_rows,
                    }
                )

        # Графики
        metric_for_charts = chart_metric if chart_metric in metrics else (metrics[0] if metrics else None)
        charts = self._build_charts(
            df=df,
            group_by=group_by,
            metrics=metrics,
            chart_types=chart_types,
            chart_metric=metric_for_charts,
            top_n=top_n,
            grouped_rows=grouped.get("rows") or [],
        )

        if insights:
            tables.insert(
                1,
                {
                    "title": "Ключевые выводы",
                    "columns": ["#", "Вывод"],
                    "rows": [
                        {"#": i + 1, "Вывод": text}
                        for i, text in enumerate(insights[:12])
                    ],
                },
            )

        name = f"{item.get('name') or f'Dataset {dataset_id}'} · {report_type}"
        if group_by:
            name += f" · by {', '.join(group_by[:2])}"

        record = report_store.save_report(
            {
                "name": name,
                "dataset_id": dataset_id,
                "dataset_name": item.get("name"),
                "report_type": report_type,
                "group_by": group_by,
                "metrics": metrics,
                "top_n": top_n,
                "chart_types": chart_types,
                "filters": filter_specs,
                "source_rows": source_rows,
                "filtered_rows": filtered_rows,
                "tables": tables,
                "charts": charts,
                "insights": insights,
            }
        )
        return record

    @staticmethod
    def _format_filters(filters: List[Dict[str, Any]]) -> str:
        if not filters:
            return "—"
        parts: List[str] = []
        for spec in filters:
            col = spec.get("column", "")
            op = spec.get("op", "eq")
            val = spec.get("value")
            if op in {"is_null", "not_null"}:
                parts.append(f"{col} {op}")
            elif op == "between" and isinstance(val, (list, tuple)) and len(val) >= 2:
                parts.append(f"{col} между {val[0]} и {val[1]}")
            elif val is not None:
                parts.append(f"{col} {op} {val}")
            else:
                parts.append(f"{col} {op}")
        return "; ".join(parts)

    def _validate_columns(
        self, df: pl.DataFrame, columns: Sequence[str], label: str
    ) -> None:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValidationError(f"Unknown {label} columns: {', '.join(missing)}")

    def _grouped_aggregates(
        self,
        df: pl.DataFrame,
        group_by: List[str],
        metrics: List[str],
        top_n: int,
    ) -> Dict[str, Any]:
        if not group_by:
            return {"table": None, "rows": [], "top_tables": [], "insights": []}

        aggs: List[pl.Expr] = [pl.len().alias("count")]
        for m in metrics:
            aggs.extend(
                [
                    pl.col(m).sum().alias(f"{m}__sum"),
                    pl.col(m).mean().alias(f"{m}__mean"),
                    pl.col(m).min().alias(f"{m}__min"),
                    pl.col(m).max().alias(f"{m}__max"),
                ]
            )

        grouped = (
            df.group_by(group_by)
            .agg(aggs)
            .sort("count", descending=True)
        )
        total_rows = max(df.height, 1)
        rows_raw = grouped.head(max(top_n * 3, 30)).to_dicts()

        display_cols = [*group_by, "count", "share_%"]
        for m in metrics:
            display_cols.extend([f"{m}__sum", f"{m}__mean"])

        rows: List[Dict[str, Any]] = []
        for r in rows_raw[: max(top_n * 2, 20)]:
            item = {k: _to_py(r.get(k)) for k in group_by}
            cnt = int(r.get("count") or 0)
            item["count"] = cnt
            item["share_%"] = round(100.0 * cnt / total_rows, 2)
            for m in metrics:
                item[f"{m}__sum"] = _to_py(r.get(f"{m}__sum"))
                item[f"{m}__mean"] = _to_py(r.get(f"{m}__mean"))
            rows.append(item)

        table = {
            "title": f"Группировка по [{', '.join(group_by)}] (топ {min(len(rows), top_n * 2)})",
            "columns": display_cols,
            "rows": rows[: top_n * 2],
        }

        top_tables: List[Dict[str, Any]] = []
        insights: List[str] = []

        # Концентрация
        if rows:
            top1 = rows[0]
            label = " / ".join(str(top1.get(g, "")) for g in group_by)
            insights.append(
                f"Лидер по числу наблюдений: «{label}» — {top1['count']} строк ({top1['share_%']}%)."
            )
            top3_share = sum(float(r.get("share_%") or 0) for r in rows[:3])
            if top3_share >= 50:
                insights.append(
                    f"Высокая концентрация: топ-3 группы дают {round(top3_share, 1)}% всех строк."
                )

        for m in metrics:
            sort_key = f"{m}__sum"
            ranked = sorted(
                rows_raw,
                key=lambda x: float(x.get(sort_key) or 0),
                reverse=True,
            )[:top_n]
            top_rows = []
            for r in ranked:
                item = {k: _to_py(r.get(k)) for k in group_by}
                item["count"] = _to_py(r.get("count"))
                item[f"{m}__sum"] = _to_py(r.get(f"{m}__sum"))
                item[f"{m}__mean"] = _to_py(r.get(f"{m}__mean"))
                top_rows.append(item)
            if top_rows:
                top_tables.append(
                    {
                        "title": f"Топ-{top_n} по сумме «{m}»",
                        "columns": [*group_by, "count", f"{m}__sum", f"{m}__mean"],
                        "rows": top_rows,
                    }
                )
                leader = top_rows[0]
                glabel = " / ".join(str(leader.get(g, "")) for g in group_by)
                insights.append(
                    f"Топ по сумме «{m}»: «{glabel}» = {_to_py(leader.get(f'{m}__sum'))}."
                )

        return {
            "table": table,
            "rows": rows,
            "top_tables": top_tables,
            "insights": insights,
        }

    def _hidden_patterns(
        self,
        df: pl.DataFrame,
        group_by: List[str],
        metrics: List[str],
        numeric_cols: List[str],
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        insights: List[str] = []

        # Перекос распределений
        for col in (metrics or numeric_cols)[:8]:
            s = df[col].drop_nulls().cast(pl.Float64)
            if s.len() < 10:
                continue
            mean = s.mean()
            median = s.median()
            std = s.std()
            if mean is None or median is None or not std:
                continue
            skew_proxy = (float(mean) - float(median)) / float(std)
            if abs(skew_proxy) >= 0.35:
                direction = "правому хвосту" if skew_proxy > 0 else "левому хвосту"
                desc = (
                    f"«{col}»: среднее ({_to_py(mean)}) заметно отличается от медианы "
                    f"({_to_py(median)}) — асимметрия к {direction}."
                )
                rows.append(
                    {
                        "Тип": "Асимметрия",
                        "Описание": desc,
                        "Сила / значение": round(skew_proxy, 3),
                    }
                )
                insights.append(desc)

        # Сильные корреляции (неочевидные пары) — без numpy
        nums = [c for c in numeric_cols if c in df.columns][:12]
        if len(nums) >= 2:
            work = df.select(nums).drop_nulls()
            if work.height >= 10:
                for i, a in enumerate(nums):
                    sa = work[a].cast(pl.Float64)
                    mean_a = sa.mean()
                    std_a = sa.std()
                    if not std_a:
                        continue
                    for b in nums[i + 1 :]:
                        sb = work[b].cast(pl.Float64)
                        mean_b = sb.mean()
                        std_b = sb.std()
                        if not std_b:
                            continue
                        cov = ((sa - mean_a) * (sb - mean_b)).mean()
                        if cov is None:
                            continue
                        num = float(cov) / (float(std_a) * float(std_b))
                        if abs(num) >= 0.55:
                            desc = f"Сильная связь между «{a}» и «{b}» (r={round(num, 3)})."
                            rows.append(
                                {
                                    "Тип": "Корреляция",
                                    "Описание": desc,
                                    "Сила / значение": round(num, 3),
                                }
                            )
                            if abs(num) >= 0.7:
                                insights.append(desc)

        # Редкие категории в group_by
        if group_by:
            gcol = group_by[0]
            total = df.height or 1
            vc = (
                df.select(gcol)
                .drop_nulls()
                .group_by(gcol)
                .agg(pl.len().alias("n"))
                .sort("n")
            )
            if vc.height >= 5:
                rare = vc.head(3).to_dicts()
                for r in rare:
                    share = 100.0 * int(r["n"]) / total
                    if share <= 2.0:
                        desc = (
                            f"Редкая группа «{r[gcol]}» в «{gcol}»: "
                            f"{r['n']} строк ({round(share, 2)}%) — возможный niche/outlier сегмент."
                        )
                        rows.append(
                            {
                                "Тип": "Редкий сегмент",
                                "Описание": desc,
                                "Сила / значение": round(share, 2),
                            }
                        )
                        insights.append(desc)

            # Индекс концентрации Херфиндаля
            if vc.height >= 2:
                shares = vc.with_columns((pl.col("n") / total).alias("p"))
                hhi = float(shares.select((pl.col("p") ** 2).sum()).item())
                if hhi >= 0.18:
                    desc = (
                        f"Высокая концентрация по «{gcol}» (HHI={round(hhi, 3)}): "
                        "несколько групп доминируют."
                    )
                    rows.append(
                        {
                            "Тип": "Концентрация",
                            "Описание": desc,
                            "Сила / значение": round(hhi, 3),
                        }
                    )
                    insights.append(desc)

        # Пропуски
        for col in df.columns[:20]:
            miss = int(df[col].null_count())
            if miss <= 0:
                continue
            share = 100.0 * miss / max(df.height, 1)
            if share >= 10:
                desc = f"В «{col}» много пропусков: {miss} ({round(share, 1)}%) — риск смещения оценок."
                rows.append(
                    {
                        "Тип": "Качество данных",
                        "Описание": desc,
                        "Сила / значение": round(share, 1),
                    }
                )

        # Сортируем по |силе|
        def _strength(row: Dict[str, Any]) -> float:
            try:
                return abs(float(row.get("Сила / значение") or 0))
            except (TypeError, ValueError):
                return 0.0

        rows = sorted(rows, key=_strength, reverse=True)[:20]
        return {"rows": rows, "insights": insights[:10]}

    def _build_charts(
        self,
        *,
        df: pl.DataFrame,
        group_by: List[str],
        metrics: List[str],
        chart_types: List[str],
        chart_metric: Optional[str],
        top_n: int,
        grouped_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        charts: List[Dict[str, Any]] = []
        gcol = group_by[0] if group_by else None
        metric = chart_metric

        # Данные для категориальных графиков
        labels: List[str] = []
        values: List[float] = []
        if grouped_rows and gcol:
            key = f"{metric}__sum" if metric else "count"
            source = grouped_rows[:top_n]
            for r in source:
                labels.append(str(r.get(gcol, "")))
                try:
                    values.append(float(r.get(key) or 0))
                except (TypeError, ValueError):
                    values.append(0.0)

        for ctype in chart_types:
            if ctype in {"bar", "horizontal_bar", "line", "pie", "doughnut", "radar"}:
                if not labels:
                    continue
                chart_js_type = {
                    "bar": "bar",
                    "horizontal_bar": "bar",
                    "line": "line",
                    "pie": "pie",
                    "doughnut": "doughnut",
                    "radar": "radar",
                }[ctype]
                dataset_label = f"{metric} (sum)" if metric else "count"
                charts.append(
                    {
                        "id": f"{ctype}_{gcol or 'group'}",
                        "title": f"{ctype.replace('_', ' ').title()}: {dataset_label} по «{gcol}»",
                        "type": chart_js_type,
                        "index_axis": "y" if ctype == "horizontal_bar" else "x",
                        "labels": labels,
                        "datasets": [
                            {
                                "label": dataset_label,
                                "data": values,
                            }
                        ],
                        "source_columns": [gcol, metric or "count"],
                    }
                )

            elif ctype == "histogram" and metric and metric in df.columns:
                series = df[metric].drop_nulls().cast(pl.Float64)
                if series.len() == 0:
                    continue
                # Простая гистограмма на 12 бинов
                mn = float(series.min())
                mx = float(series.max())
                if mx == mn:
                    mx = mn + 1.0
                bins = 12
                width = (mx - mn) / bins
                edges = [mn + i * width for i in range(bins + 1)]
                hist_labels = []
                hist_values = []
                for i in range(bins):
                    lo, hi = edges[i], edges[i + 1]
                    if i == bins - 1:
                        cnt = int(((series >= lo) & (series <= hi)).sum())
                    else:
                        cnt = int(((series >= lo) & (series < hi)).sum())
                    hist_labels.append(f"{lo:.2f}–{hi:.2f}")
                    hist_values.append(cnt)
                charts.append(
                    {
                        "id": f"hist_{metric}",
                        "title": f"Гистограмма: {metric}",
                        "type": "bar",
                        "labels": hist_labels,
                        "datasets": [{"label": "Частота", "data": hist_values}],
                        "source_columns": [metric],
                    }
                )

            elif ctype == "scatter" and len(metrics) >= 2:
                x_col, y_col = metrics[0], metrics[1]
                sample = (
                    df.select([x_col, y_col])
                    .drop_nulls()
                    .head(400)
                    .to_dicts()
                )
                points = [
                    {"x": _to_py(r[x_col]), "y": _to_py(r[y_col])}
                    for r in sample
                    if r.get(x_col) is not None and r.get(y_col) is not None
                ]
                if points:
                    charts.append(
                        {
                            "id": f"scatter_{x_col}_{y_col}",
                            "title": f"Scatter: {x_col} vs {y_col}",
                            "type": "scatter",
                            "datasets": [
                                {
                                    "label": f"{x_col} / {y_col}",
                                    "data": points,
                                }
                            ],
                            "source_columns": [x_col, y_col],
                        }
                    )

        return charts
