"""SQL-lite: Polars SQLContext поверх одного или нескольких наборов."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

import polars as pl

from application.use_cases.analysis.analysis_service import _to_py
from core.exceptions import NotFoundError, ValidationError
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import read_dataframe

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)


class SqlQueryService:
    """Безопасный SELECT-only SQL через Polars SQLContext."""

    async def execute(
        self,
        sql: str,
        tables: List[Dict[str, Any]],
        *,
        limit: int = 500,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(self._execute_blocking, sql, tables, limit)

    def _execute_blocking(
        self,
        sql: str,
        tables: List[Dict[str, Any]],
        limit: int,
    ) -> Dict[str, Any]:
        sql = (sql or "").strip()
        if not sql:
            raise ValidationError("SQL query is required")
        if not sql.upper().lstrip().startswith("SELECT"):
            raise ValidationError("Only SELECT queries are allowed")
        if _FORBIDDEN.search(sql):
            raise ValidationError("Forbidden SQL keyword detected")

        if not tables:
            raise ValidationError("At least one table mapping is required")

        limit = max(1, min(int(limit or 500), 2000))
        ctx = pl.SQLContext()
        registered: List[str] = []

        for spec in tables:
            alias = (spec.get("alias") or "").strip()
            dataset_id = int(spec.get("dataset_id") or 0)
            if not alias:
                raise ValidationError("Each table needs an alias")
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", alias):
                raise ValidationError(f"Invalid alias: {alias}")
            if alias in registered:
                raise ValidationError(f"Duplicate alias: {alias}")

            item = dataset_store.get_dataset(dataset_id)
            if not item:
                raise NotFoundError(f"Dataset {dataset_id} not found")
            path = dataset_store.get_dataset_path(dataset_id)
            if not path:
                raise NotFoundError(f"Dataset file for {dataset_id} not found")

            df = read_dataframe(path)
            ctx.register(alias, df)
            registered.append(alias)

        try:
            result = ctx.execute(sql).collect()
        except Exception as exc:
            raise ValidationError(f"SQL execution failed: {exc}") from exc

        if result.height > limit:
            result = result.head(limit)

        rows = [{k: _to_py(v) for k, v in row.items()} for row in result.to_dicts()]
        return {
            "sql": sql,
            "tables": [{"alias": t.get("alias"), "dataset_id": t.get("dataset_id")} for t in tables],
            "columns": list(result.columns),
            "rows": rows,
            "returned_rows": len(rows),
            "total_rows": result.height,
        }
