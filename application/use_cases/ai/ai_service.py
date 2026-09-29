"""AI-анализ датасетов через локальную LLM с подготовкой сжатого контекста."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import polars as pl

from application.use_cases.analysis.analysis_service import NUMERIC_DTYPES, AnalysisService
from core.config import settings
from core.exceptions import AIError, NotFoundError
from infrastructure.ai.llama_client import LocalLLMClient
from infrastructure.ai.text_utils import dedupe_llm_output
from infrastructure.storage import dataset_store, report_store
from infrastructure.storage.schema_reader import read_dataframe

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — старший аналитик данных. Пиши на русском языке.
Давай практичный анализ: только факты и цифры из контекста, без выдумок.
Структура (каждый раздел — один раз, без повторов):
1) Краткое резюме (3–5 предложений)
2) Ключевые находки (маркированный список)
3) Паттерны и аномалии
4) Риски и ограничения данных
5) Рекомендации (3–5 пунктов)
Запрещено дублировать заголовки и абзацы. После раздела 5 — сразу заверши ответ.
Если данных недостаточно — укажи, чего не хватает."""

# Пороги для ускорения контекста на больших наборах
AI_STATS_ROW_CAP = 3000
AI_CORR_ROW_CAP = 1500
AI_CORR_MAX_COLS = 8


class AIService:
    """Подготовка контекста и генерация текстового AI-отчёта по набору данных."""

    def __init__(self) -> None:
        self.analysis = AnalysisService()

    async def analyze_dataset(
        self,
        dataset_id: int,
        question: Optional[str] = None,
        *,
        save_report: bool = True,
        include_correlations: bool = True,
        sample_rows: int = 12,
        filters: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[List[str]] = None,
        aggregations: Optional[List[Dict[str, Any]]] = None,
        model_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Развёрнутый AI-анализ; тяжёлые операции выполняются в фоновом потоке."""
        timeout = max(int(settings.LLM_TIMEOUT or 300), 300)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._analyze_dataset_blocking,
                    dataset_id,
                    question,
                    save_report,
                    include_correlations,
                    sample_rows,
                    filters,
                    group_by,
                    aggregations,
                    model_path,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise AIError(
                f"AI-анализ превысил лимит {timeout} с. "
                "Попробуйте сузить вопрос или увеличьте LLM_TIMEOUT в .env"
            ) from e

    def _analyze_dataset_blocking(
        self,
        dataset_id: int,
        question: Optional[str],
        save_report: bool,
        include_correlations: bool,
        sample_rows: int,
        filters: Optional[List[Dict[str, Any]]],
        group_by: Optional[List[str]],
        aggregations: Optional[List[Dict[str, Any]]],
        model_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Синхронный пайплайн: контекст → LLM → сохранение отчёта."""
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")

        llm = LocalLLMClient(profile="main", llama_model_path=model_path or None)

        logger.info("AI analyze start: dataset_id=%s model=%s", dataset_id, model_path or "default")
        context = self._build_context_sync(
            dataset_id,
            item,
            include_correlations=include_correlations,
            sample_rows=sample_rows,
            filters=filters,
            group_by=group_by,
            aggregations=aggregations,
        )

        user_question = (question or "").strip() or (
            "Сделай развёрнутый аналитический обзор датасета: что важного видно в данных, "
            "какие закономерности, на что обратить внимание бизнесу/операторам, "
            "какие проверки и срезы стоит провести дальше."
        )

        prompt = (
            f"Контекст данных (JSON):\n{context}\n\n"
            f"Задача аналитика:\n{user_question}\n"
        )

        logger.info("AI analyze: loading LLM backend…")
        backend = llm.ensure_backend_sync()
        max_tokens = int(settings.AI_ANALYZE_MAX_TOKENS or 700)
        logger.info("AI analyze: generating text (max_tokens=%s)…", max_tokens)
        raw_narrative = llm.generate_text_sync(
            prompt,
            system=SYSTEM_PROMPT,
            max_tokens=max_tokens,
            temperature=0.2,
        )
        narrative = dedupe_llm_output(raw_narrative)
        if len(narrative) < len(raw_narrative or "") * 0.85:
            logger.info(
                "AI analyze: dedupe trimmed output %s -> %s chars",
                len(raw_narrative or ""),
                len(narrative),
            )
        logger.info("AI analyze: generation done, chars=%s", len(narrative or ""))

        context_obj = json.loads(context) if context.startswith("{") else {}
        result: Dict[str, Any] = {
            "dataset_id": dataset_id,
            "dataset_name": item.get("name"),
            "question": user_question,
            "model": backend.get("model"),
            "backend": backend.get("backend"),
            "analysis_text": narrative,
            "context_preview": {
                "rows": (context_obj.get("overview") or {}).get("rows"),
                "columns_count": len(context_obj.get("column_stats") or {}),
            },
        }

        if save_report:
            report = report_store.save_report(
                {
                    "name": f"AI-анализ · {item.get('name') or dataset_id}",
                    "dataset_id": dataset_id,
                    "dataset_name": item.get("name"),
                    "report_type": "ai_analysis",
                    "tables": [
                        {
                            "title": "AI-анализ",
                            "columns": ["Раздел", "Содержание"],
                            "rows": [
                                {"Раздел": "Вопрос", "Содержание": user_question},
                                {"Раздел": "Модель", "Содержание": backend.get("model")},
                                {"Раздел": "Backend", "Содержание": backend.get("backend")},
                                {"Раздел": "Текст анализа", "Содержание": narrative},
                            ],
                        }
                    ],
                    "analysis_text": narrative,
                }
            )
            result["report_id"] = report["id"]

        return result

    def _build_context_sync(
        self,
        dataset_id: int,
        item: Dict[str, Any],
        *,
        include_correlations: bool,
        sample_rows: int,
        filters: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[List[str]] = None,
        aggregations: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Собрать JSON-контекст; на больших файлах — выборка и без тяжёлых корреляций."""
        from application.use_cases.export.export_service import ExportService

        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        logger.info("AI context: loading dataframe %s", path.name)
        df = read_dataframe(path)
        source_rows = df.height
        export = ExportService()
        active_filters = [f for f in (filters or []) if f.get("column")]
        filtered = export.apply_filters(df, active_filters) if active_filters else df
        filtered_rows = filtered.height

        total_rows = filtered_rows
        stats_df = filtered.head(AI_STATS_ROW_CAP) if total_rows > AI_STATS_ROW_CAP else filtered

        compact_stats: Dict[str, Any] = {}
        for col in df.columns:
            s = stats_df[col]
            dtype = s.dtype
            entry: Dict[str, Any] = {
                "dtype": str(dtype),
                "count": int(s.len()),
                "missing": int(s.null_count()),
            }
            if dtype in NUMERIC_DTYPES:
                entry.update(
                    {
                        "mean": _safe(s.mean()),
                        "median": _safe(s.median()),
                        "std": _safe(s.std()),
                        "min": _safe(s.min()),
                        "max": _safe(s.max()),
                    }
                )
            elif dtype == pl.String:
                entry["unique"] = int(s.n_unique())
                modes = s.drop_nulls().mode().to_list()[:3]
                entry["most_common"] = [_safe(v) for v in modes]
            else:
                entry["unique"] = int(s.n_unique())
            compact_stats[col] = entry

        n = min(max(3, sample_rows), 6, filtered.height)
        sample: List[Dict[str, Any]] = []
        if n > 0:
            sample = [
                {k: _truncate_cell(v) for k, v in row.items()}
                for row in filtered.head(n).to_dicts()
            ]

        profile_insights = _quick_insights(total_rows, len(df.columns), compact_stats)

        payload: Dict[str, Any] = {
            "overview": {
                "dataset_id": dataset_id,
                "name": item.get("name"),
                "filename": item.get("filename"),
                "rows": total_rows,
                "source_rows": source_rows,
                "filtered_rows": filtered_rows,
                "filters_applied": len(active_filters),
                "columns": list(df.columns),
                "stats_sample_rows": stats_df.height,
            },
            "column_stats": compact_stats,
            "sample_rows": sample,
            "profile_insights": profile_insights,
        }

        if active_filters:
            payload["filters"] = active_filters

        if group_by:
            try:
                grouped = export._apply_grouped(filtered, group_by, aggregations)
                grouped_rows = [
                    {k: _safe(v) for k, v in row.items()}
                    for row in grouped.head(12).to_dicts()
                ]
                payload["grouped_summary"] = {
                    "group_by": group_by,
                    "aggregations": aggregations or [],
                    "top_groups": grouped_rows,
                    "total_groups": grouped.height,
                }
            except Exception as exc:
                logger.warning("AI context: grouped summary skipped: %s", exc)

        numeric_cols = [c for c in df.columns if filtered[c].dtype in NUMERIC_DTYPES]
        use_corr = (
            include_correlations
            and filtered_rows <= AI_CORR_ROW_CAP
            and len(numeric_cols) <= AI_CORR_MAX_COLS
            and len(numeric_cols) >= 2
        )
        if use_corr:
            logger.info("AI context: computing correlations (%s cols)…", len(numeric_cols))
            try:
                corr_cols = numeric_cols[:AI_CORR_MAX_COLS]
                corr_df = filtered.select(corr_cols)
                matrix = self._corr_matrix_from_df(corr_df)
                payload["top_correlations"] = _top_correlations(matrix, limit=10)
            except Exception as exc:
                logger.warning("AI context: correlations skipped: %s", exc)
                payload["top_correlations"] = []
        else:
            payload["top_correlations"] = []
            if include_correlations and filtered_rows > AI_CORR_ROW_CAP:
                payload["notes"] = [
                    f"Корреляции пропущены: срез большой ({filtered_rows} строк). "
                    f"Используйте вкладку «Анализ → Корреляции»."
                ]

        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        max_chars = int(settings.AI_CONTEXT_MAX_CHARS or 8000)
        if len(text) > max_chars:
            text = text[:max_chars] + "…[truncated]"
        return text

    @staticmethod
    def _corr_matrix_from_df(df: pl.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Матрица Пирсона для уже загруженного среза."""
        cols = list(df.columns)
        matrix: Dict[str, Dict[str, Any]] = {c: {} for c in cols}
        for i, a in enumerate(cols):
            for b in cols[i:]:
                try:
                    val = df.select(pl.corr(a, b)).item()
                except Exception:
                    val = None
                matrix[a][b] = _safe(val)
                matrix[b][a] = _safe(val)
        return matrix


def _truncate_cell(value: Any, limit: int = 80) -> Any:
    safe = _safe(value)
    if isinstance(safe, str) and len(safe) > limit:
        return safe[: limit - 1] + "…"
    return safe


def _quick_insights(
    rows: int, cols_count: int, column_stats: Dict[str, Any]
) -> List[str]:
    insights: List[str] = []
    if rows:
        insights.append(f"Строк в срезе: {rows}, колонок: {cols_count}.")
    high_miss = [
        name
        for name, meta in column_stats.items()
        if meta.get("missing", 0) and rows
        and meta["missing"] / max(rows, 1) >= 0.1
    ]
    for name in high_miss[:2]:
        pct = round(100 * column_stats[name]["missing"] / max(rows, 1), 1)
        insights.append(f"Колонка «{name}»: {pct}% пропусков.")
    numeric = sum(1 for m in column_stats.values() if "mean" in m)
    if numeric:
        insights.append(f"Числовых метрик: {numeric}.")
    return insights[:5]


def _safe(value: Any) -> Any:
    """Привести значение к JSON-безопасному виду."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_safe(v) for v in value[:8]]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _top_correlations(
    matrix: Dict[str, Dict[str, Any]], limit: int = 12
) -> List[Dict[str, Any]]:
    """Топ пар с сильной корреляцией для контекста LLM."""
    pairs: List[Dict[str, Any]] = []
    keys = list(matrix.keys())
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            val = matrix.get(a, {}).get(b)
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            if abs(num) >= 0.3:
                pairs.append({"a": a, "b": b, "corr": round(num, 4)})
    pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
    return pairs[:limit]
