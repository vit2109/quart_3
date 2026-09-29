"""REST-эндпоинты ETL: очистка, preview и оценка качества данных."""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import AnalystDep, ViewerDep
from application.use_cases.etl.etl_service import ETLService, MISSING_STRATEGIES
from core.exceptions import AppException, DuplicateError

router = APIRouter(prefix="/etl", tags=["etl"])


class ETLConfig(BaseModel):
    dataset_id: int
    clean_missing: bool = True
    missing_strategy: Literal[
        "drop",
        "fill_zero",
        "fill_mean",
        "fill_median",
        "fill_unknown",
        "forward_fill",
    ] = "drop"
    remove_duplicates: bool = True
    normalize_strings: bool = True
    remove_outliers: bool = False


@router.post("/process/{dataset_id}")
async def run_etl(dataset_id: int, config: ETLConfig, _user: AnalystDep):
    """Очистить набор и сохранить результат как новый датасет."""
    if config.dataset_id != dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id mismatch")
    try:
        data = await ETLService().process(dataset_id, config.model_dump())
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "success",
        "message": "ETL process completed",
        "data": data,
    }


@router.post("/preview/{dataset_id}")
async def preview_etl(dataset_id: int, config: ETLConfig, _user: AnalystDep):
    """Preview: строки до/после и примеры изменённых ячеек без сохранения."""
    if config.dataset_id != dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id mismatch")
    try:
        data = await ETLService().preview(dataset_id, config.model_dump())
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}


@router.get("/quality/{dataset_id}")
async def check_quality(dataset_id: int, _user: ViewerDep):
    """Метрики качества: полнота, уникальность, список проблем."""
    try:
        data = await ETLService().quality(dataset_id)
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}
