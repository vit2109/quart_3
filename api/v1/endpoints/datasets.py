"""REST-эндпоинты для управления наборами данных."""

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.deps import AnalystDep, ViewerDep
from core.config import settings
from core.exceptions import AppException, DuplicateError, NotFoundError
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import get_columns

router = APIRouter(prefix="/datasets", tags=["datasets"])


class JoinPreviewRequest(BaseModel):
    left_id: int
    right_id: int
    left_on: List[str] = Field(default_factory=list)
    right_on: List[str] = Field(default_factory=list)
    how: str = "inner"
    sample: int = Field(default=20, ge=1, le=200)


class JoinSaveRequest(JoinPreviewRequest):
    name: Optional[str] = None


@router.post("/join/preview")
async def preview_join(body: JoinPreviewRequest, _user: AnalystDep):
    """Preview join без сохранения."""
    from application.use_cases.datasets.join_service import DatasetJoinService
    from core.exceptions import AppException

    try:
        data = await DatasetJoinService().preview(
            body.left_id,
            body.right_id,
            body.left_on,
            body.right_on,
            how=body.how,
            limit=body.sample,
        )
        return {"status": "success", "data": data}
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/join")
async def join_datasets(body: JoinSaveRequest, _user: AnalystDep):
    """Join двух наборов и сохранить результат как новый dataset."""
    from application.use_cases.datasets.join_service import DatasetJoinService
    from core.exceptions import AppException

    try:
        data = await DatasetJoinService().join_and_save(
            body.left_id,
            body.right_id,
            body.left_on,
            body.right_on,
            how=body.how,
            name=body.name,
        )
        return {"status": "success", "data": data}
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/upload")
async def upload_dataset(
    _user: AnalystDep,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
):
    """Загрузка нового набора данных.

    Если файл с идентичным содержимым уже есть в системе — возвращает 409.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.MAX_UPLOAD_SIZE} bytes)",
        )

    try:
        record = dataset_store.save_dataset(
            original_filename=file.filename or "dataset.bin",
            content=content,
            name=name,
            description=description,
            content_type=file.content_type,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.message, headers=None) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "status": "success",
        "message": "Dataset uploaded",
        "data": record,
    }


@router.get("/")
async def list_datasets(_user: ViewerDep):
    """Список всех наборов данных."""
    return {"status": "success", "data": dataset_store.list_datasets()}


@router.get("/{dataset_id}/knowledge-links")
async def get_dataset_knowledge_links(dataset_id: int, _user: ViewerDep):
    """Связанные документы базы знаний для набора данных."""
    from infrastructure.knowledge.document_store import list_by_dataset_id

    item = dataset_store.get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    docs = list_by_dataset_id(dataset_id)
    return {"status": "success", "data": {"dataset_id": dataset_id, "documents": docs}}


@router.get("/{dataset_id}/profile")
async def get_dataset_profile(
    dataset_id: int,
    _user: ViewerDep,
    sample: int = 50,
):
    """Паспорт набора: sample строк, профиль колонок, инсайты."""
    import asyncio

    from application.use_cases.datasets.dataset_profile_service import (
        DatasetProfileService,
    )
    from core.exceptions import AppException

    try:
        profile = await DatasetProfileService().get_profile(dataset_id, sample)
        return {"status": "success", "data": profile}
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class SavedViewPayload(BaseModel):
    """Сохранённое представление: фильтры, группировка, режим."""

    name: str
    pinned: bool = False
    mode: str = "summary"
    filters: List[dict] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    aggregations: List[dict] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    report_type: str = "summary"
    top_n: int = 10
    chart_types: List[str] = Field(default_factory=list)
    chart_metric: Optional[str] = None
    pareto_metric: Optional[str] = None
    pareto_agg: str = "sum"
    date_col: Optional[str] = None
    period_days: Optional[int] = None
    export_format: str = "csv"
    sort_by: Optional[str] = None
    sort_dir: str = "asc"
    limit: int = 200


@router.get("/{dataset_id}/views")
async def list_saved_views(dataset_id: int, _user: ViewerDep):
    """Список сохранённых представлений для набора."""
    item = dataset_store.get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    from infrastructure.storage import views_store

    return {"status": "success", "data": views_store.list_views(dataset_id)}


@router.get("/{dataset_id}/views/{view_id}")
async def get_saved_view(dataset_id: int, view_id: int, _user: ViewerDep):
    from infrastructure.storage import views_store

    view = views_store.get_view(dataset_id, view_id)
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    return {"status": "success", "data": view}


@router.post("/{dataset_id}/views")
async def create_saved_view(dataset_id: int, body: SavedViewPayload, _user: AnalystDep):
    item = dataset_store.get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    from infrastructure.storage import views_store

    try:
        record = views_store.save_view(dataset_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"status": "success", "data": record}


@router.put("/{dataset_id}/views/{view_id}")
async def update_saved_view(dataset_id: int, view_id: int, body: SavedViewPayload, _user: AnalystDep):
    from infrastructure.storage import views_store

    try:
        record = views_store.save_view(dataset_id, body.model_dump(), view_id=view_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"status": "success", "data": record}


@router.delete("/{dataset_id}/views/{view_id}")
async def delete_saved_view(dataset_id: int, view_id: int, _user: AnalystDep):
    from infrastructure.storage import views_store

    if not views_store.delete_view(dataset_id, view_id):
        raise HTTPException(status_code=404, detail="View not found")
    return {"status": "success", "message": "View deleted"}


@router.get("/{dataset_id}/columns")
async def get_dataset_columns(dataset_id: int, _user: ViewerDep):
    """Список колонок датасета с типами (number/string/datetime)."""
    import asyncio

    item = dataset_store.get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")

    path = dataset_store.get_dataset_path(dataset_id)
    if not path:
        raise HTTPException(status_code=404, detail="Dataset file not found")

    try:
        columns = await asyncio.to_thread(get_columns, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read columns: {e}",
        ) from e

    return {
        "status": "success",
        "data": {
            "dataset_id": dataset_id,
            "name": item.get("name"),
            "filename": item.get("filename"),
            "columns": columns,
        },
    }


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: int, _user: ViewerDep):
    """Получить метаданные набора по ID."""
    item = dataset_store.get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"status": "success", "data": item}


@router.put("/{dataset_id}")
async def update_dataset(
    dataset_id: int,
    _user: AnalystDep,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """Обновить название, описание и/или заменить файл набора."""
    content: Optional[bytes] = None
    original_filename: Optional[str] = None
    content_type: Optional[str] = None

    if file is not None:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {settings.MAX_UPLOAD_SIZE} bytes)",
            )
        original_filename = file.filename
        content_type = file.content_type

    if name is None and description is None and content is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        record = dataset_store.update_dataset(
            dataset_id,
            name=name,
            description=description,
            content=content,
            original_filename=original_filename,
            content_type=content_type,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.message) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "status": "success",
        "message": "Dataset updated",
        "data": record,
    }


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: int, _user: AnalystDep):
    """Удалить набор данных и связанный файл."""
    try:
        record = dataset_store.delete_dataset(dataset_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message) from e

    return {
        "status": "success",
        "message": "Dataset deleted",
        "data": record,
    }
