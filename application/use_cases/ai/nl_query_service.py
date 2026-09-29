"""NL-запросы к табличным данным через безопасный Polars DSL."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import polars as pl
from pydantic import BaseModel, Field, field_validator

from application.use_cases.analysis.analysis_service import NUMERIC_DTYPES
from core.config import settings
from core.exceptions import AIError, NotFoundError, ValidationError
from infrastructure.ai.llama_client import LocalLLMClient
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import read_dataframe

logger = logging.getLogger(__name__)

ALLOWED_FILTER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"}
ALLOWED_AGGS = {"sum", "mean", "min", "max", "count", "n_unique"}

NL_SYSTEM = """Ты переводишь вопрос аналитика в JSON-план запроса к таблице.
Отвечай ТОЛЬКО валидным JSON без markdown и комментариев.
Схема:
{
  "filters": [{"column": "имя", "op": "eq|ne|gt|gte|lt|lte|contains|in", "value": ...}],
  "group_by": ["col"],
  "aggregations": [{"column": "col", "agg": "sum|mean|min|max|count|n_unique", "alias": "имя"}],
  "columns": ["col1", "col2"],
  "sort_by": "col или alias",
  "sort_dir": "asc|desc",
  "limit": 50,
  "explanation": "кратко на русском что делает запрос"
}
Используй только существующие колонки. limit <= 200."""


class FilterSpec(BaseModel):
    column: str
    op: str = "eq"
    value: Any = None

    @field_validator("op")
    @classmethod
    def validate_op(cls, v: str) -> str:
        if v not in ALLOWED_FILTER_OPS:
            raise ValueError(f"Unsupported filter op: {v}")
        return v


class AggSpec(BaseModel):
    column: str
    agg: str = "sum"
    alias: Optional[str] = None

    @field_validator("agg")
    @classmethod
    def validate_agg(cls, v: str) -> str:
        if v not in ALLOWED_AGGS:
            raise ValueError(f"Unsupported agg: {v}")
        return v


class NLQueryPlan(BaseModel):
    filters: List[FilterSpec] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    aggregations: List[AggSpec] = Field(default_factory=list)
    columns: Optional[List[str]] = None
    sort_by: Optional[str] = None
    sort_dir: str = "desc"
    limit: int = Field(default=50, ge=1, le=200)
    explanation: Optional[str] = None


class NLQueryService:
    """NL → JSON plan → Polars → результат."""

    def __init__(self) -> None:
        self.llm = LocalLLMClient(profile="sql")

    async def query(
        self,
        dataset_id: int,
        question: str,
        *,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        timeout = max(int(settings.LLM_TIMEOUT or 120), 120)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._query_blocking,
                    dataset_id,
                    question,
                    user_email,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise AIError("NL-запрос превысил лимит времени") from e

    def _query_blocking(
        self,
        dataset_id: int,
        question: str,
        user_email: Optional[str],
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        df = read_dataframe(path)
        schema = {
            "columns": [
                {"name": c, "dtype": str(df[c].dtype)}
                for c in df.columns
            ],
            "rows": df.height,
        }

        plan = self._build_plan(question, schema)
        result_df = self._execute_plan(df, plan)
        preview = result_df.head(plan.limit).to_dicts()
        preview = [{k: _to_py(v) for k, v in row.items()} for row in preview]

        response = {
            "dataset_id": dataset_id,
            "question": question,
            "plan": plan.model_dump(),
            "explanation": plan.explanation,
            "row_count": result_df.height,
            "columns": list(result_df.columns),
            "rows": preview,
        }

        asyncio.run(self._log_query(dataset_id, question, plan, response, user_email))
        return response

    def _build_plan(self, question: str, schema: Dict[str, Any]) -> NLQueryPlan:
        prompt = (
            f"Схема таблицы:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Вопрос:\n{question.strip()}\n"
        )
        raw = self.llm.generate_text_sync(
            prompt,
            system=NL_SYSTEM,
            max_tokens=600,
            temperature=0.1,
        )
        data = _extract_json(raw)
        try:
            plan = NLQueryPlan.model_validate(data)
        except Exception as exc:
            raise ValidationError(f"LLM returned invalid plan: {exc}") from exc
        return plan

    def _execute_plan(self, df: pl.DataFrame, plan: NLQueryPlan) -> pl.DataFrame:
        work = df
        col_names = set(work.columns)

        for flt in plan.filters:
            if flt.column not in col_names:
                raise ValidationError(f"Unknown filter column: {flt.column}")
            work = _apply_filter(work, flt)

        if plan.aggregations or plan.group_by:
            for col in plan.group_by:
                if col not in col_names:
                    raise ValidationError(f"Unknown group_by column: {col}")
            exprs = []
            for agg in plan.aggregations:
                if agg.column not in col_names:
                    raise ValidationError(f"Unknown agg column: {agg.column}")
                alias = agg.alias or f"{agg.agg}_{agg.column}"
                exprs.append(_agg_expr(agg.column, agg.agg).alias(alias))
            if plan.group_by:
                work = work.group_by(plan.group_by).agg(exprs or pl.len().alias("count"))
            elif exprs:
                work = work.select(exprs)
        elif plan.columns:
            missing = [c for c in plan.columns if c not in col_names]
            if missing:
                raise ValidationError(f"Unknown columns: {', '.join(missing)}")
            work = work.select(plan.columns)

        if plan.sort_by and plan.sort_by in work.columns:
            work = work.sort(plan.sort_by, descending=plan.sort_dir.lower() == "desc")

        return work.head(plan.limit)

    async def _log_query(
        self,
        dataset_id: int,
        question: str,
        plan: NLQueryPlan,
        response: Dict[str, Any],
        user_email: Optional[str],
    ) -> None:
        preview = {
            "row_count": response.get("row_count"),
            "columns": response.get("columns"),
            "sample_rows": (response.get("rows") or [])[:5],
        }
        from core import db_state

        if not db_state.database_available:
            return
        try:
            from datetime import datetime
            from sqlalchemy.ext.asyncio import AsyncSession
            from core.database import engine
            from infrastructure.persistence.models import NLQueryRecord

            async with AsyncSession(engine) as session:
                session.add(
                    NLQueryRecord(
                        dataset_id=dataset_id,
                        user_email=user_email,
                        question=question,
                        plan=plan.model_dump(),
                        result_preview=preview,
                        created_at=datetime.utcnow(),
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.debug("NL query log skipped: %s", exc)


def _apply_filter(df: pl.DataFrame, flt: FilterSpec) -> pl.DataFrame:
    col = pl.col(flt.column)
    op = flt.op
    val = flt.value
    if op == "eq":
        return df.filter(col == val)
    if op == "ne":
        return df.filter(col != val)
    if op == "gt":
        return df.filter(col > val)
    if op == "gte":
        return df.filter(col >= val)
    if op == "lt":
        return df.filter(col < val)
    if op == "lte":
        return df.filter(col <= val)
    if op == "contains":
        return df.filter(col.cast(pl.Utf8).str.contains(str(val), literal=True))
    if op == "in":
        values = val if isinstance(val, list) else [val]
        return df.filter(col.is_in(values))
    return df


def _agg_expr(column: str, agg: str):
    c = pl.col(column)
    if agg == "sum":
        return c.sum()
    if agg == "mean":
        return c.mean()
    if agg == "min":
        return c.min()
    if agg == "max":
        return c.max()
    if agg == "count":
        return c.count()
    if agg == "n_unique":
        return c.n_unique()
    return c.sum()


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValidationError("LLM did not return JSON plan")
    return json.loads(match.group(0))


def _to_py(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)
