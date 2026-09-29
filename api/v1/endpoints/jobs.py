"""REST API фоновых задач и расписаний."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from application.use_cases.jobs.job_service import JobService
from core.exceptions import AppException
from core.security import require_role
from domain.entities.user import User, UserRole

router = APIRouter(prefix="/jobs", tags=["jobs"])

_service = JobService()


class SubmitJobRequest(BaseModel):
    job_type: str = Field(description="report_generate | knowledge_ingest | knowledge_reindex | ai_analyze")
    payload: Dict[str, Any] = Field(default_factory=dict)


class CreateScheduleRequest(BaseModel):
    name: str
    job_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    cron: str = Field(description="Cron: 'min hour day month dow' или с секундами")
    webhook_url: Optional[str] = Field(
        default=None,
        description="URL для POST-уведомления по завершении задачи (JSON)",
    )


@router.get("/runs")
async def list_job_runs(
    limit: int = 50,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Список последних фоновых задач."""
    data = await _service.list_runs(limit)
    return {"status": "success", "data": data}


@router.get("/runs/{run_id}")
async def get_job_run(
    run_id: str,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Статус фоновой задачи."""
    run = await _service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Job run not found")
    return {"status": "success", "data": run}


@router.post("/submit")
async def submit_job(
    body: SubmitJobRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Поставить задачу в очередь (отчёт, индексация, переиндексация)."""
    try:
        run = await _service.submit(body.job_type, body.payload)
        return {"status": "success", "data": run}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AppException:
        raise


@router.get("/schedules")
async def list_schedules(
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Список cron-расписаний."""
    data = await _service.list_schedules()
    return {"status": "success", "data": data}


@router.post("/schedules")
async def create_schedule(
    body: CreateScheduleRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Создать cron-расписание (например ежедневный отчёт)."""
    try:
        schedule = await _service.create_schedule(
            body.name, body.job_type, body.payload, body.cron, webhook_url=body.webhook_url
        )
        return {"status": "success", "data": schedule}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class PatchScheduleRequest(BaseModel):
    enabled: Optional[bool] = None


@router.patch("/schedules/{schedule_id}")
async def patch_schedule(
    schedule_id: int,
    body: PatchScheduleRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Включить/выключить расписание."""
    if body.enabled is None:
        raise HTTPException(status_code=400, detail="enabled is required")
    schedule = await _service.toggle_schedule(schedule_id, body.enabled)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success", "data": schedule}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Удалить cron-расписание."""
    if not await _service.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success", "message": "Schedule deleted"}
