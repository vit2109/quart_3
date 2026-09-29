"""REST-эндпоинты интерактивного просмотра и выгрузки данных."""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.deps import AnalystDep, ViewerDep
from application.use_cases.export.export_service import AGG_FUNCS, FILTER_OPS, ExportService
from core.exceptions import AppException

router = APIRouter(prefix="/export", tags=["export"])


class FilterSpec(BaseModel):
    """Один фильтр по колонке."""

    column: str
    op: str = "eq"
    value: Optional[Any] = None


class AggregationSpec(BaseModel):
    """Агрегация для группированного режима."""

    column: str
    agg: str = "sum"
    alias: Optional[str] = None


class ExportQueryRequest(BaseModel):
    """Параметры запроса: фильтры, группировка, сортировка, пагинация."""

    mode: str = Field(default="raw", description="raw — строки; grouped — группировка")
    filters: List[FilterSpec] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    aggregations: List[AggregationSpec] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    sort_by: Optional[str] = None
    sort_dir: str = "asc"
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


def _service() -> ExportService:
    return ExportService()


@router.get("/meta")
async def export_meta(_user: ViewerDep):
    """Справочник доступных операторов фильтрации и агрегации."""
    return {
        "status": "success",
        "data": {
            "filter_ops": sorted(FILTER_OPS),
            "aggregations": sorted(AGG_FUNCS),
            "modes": ["raw", "grouped"],
        },
    }


@router.get("/column-values/{dataset_id}")
async def column_values(
    dataset_id: int,
    _user: ViewerDep,
    column: str = Query(..., min_length=1),
    q: str = Query(""),
    limit: int = Query(30, ge=1, le=100),
):
    """Уникальные значения колонки для автодополнения фильтров."""
    try:
        result = await asyncio.to_thread(
            _service().get_column_values,
            dataset_id,
            column,
            q,
            limit,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/query/{dataset_id}")
async def query_dataset(dataset_id: int, body: ExportQueryRequest, _user: AnalystDep):
    """Просмотр данных с фильтрами, группировкой и агрегацией."""
    try:
        result = await asyncio.to_thread(
            _service().query,
            dataset_id,
            mode=body.mode,
            filters=[f.model_dump() for f in body.filters],
            group_by=body.group_by,
            aggregations=[a.model_dump() for a in body.aggregations],
            columns=body.columns,
            sort_by=body.sort_by,
            sort_dir=body.sort_dir,
            limit=body.limit,
            offset=body.offset,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/download/{dataset_id}")
async def download_dataset(
    dataset_id: int,
    body: ExportQueryRequest,
    _user: AnalystDep,
    format: str = Query("csv", pattern="^(csv|json|xlsx)$"),
):
    """Выгрузить результат запроса в файл CSV, JSON или XLSX."""
    try:
        content, media_type, filename = await asyncio.to_thread(
            _service().export_bytes,
            dataset_id,
            file_format=format,
            mode=body.mode,
            filters=[f.model_dump() for f in body.filters],
            group_by=body.group_by,
            aggregations=[a.model_dump() for a in body.aggregations],
            columns=body.columns,
            sort_by=body.sort_by,
            sort_dir=body.sort_dir,
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
