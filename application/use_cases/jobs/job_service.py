"""Фоновые задачи и планировщик отчётов/индексации."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from core import db_state
from infrastructure.storage import job_store

logger = logging.getLogger(__name__)

JobHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

_knowledge_job_lock = asyncio.Lock()


class JobService:
    """Постановка и выполнение фоновых задач."""

    _handlers: Dict[str, JobHandler] = {}

    @classmethod
    def register(cls, job_type: str, handler: JobHandler) -> None:
        cls._handlers[job_type] = handler

    async def submit(self, job_type: str, payload: Dict[str, Any], scheduled_job_id: Optional[int] = None) -> Dict[str, Any]:
        if job_type not in self._handlers:
            raise ValueError(f"Unknown job type: {job_type}")
        run = job_store.create_run(job_type, payload, scheduled_job_id)
        asyncio.create_task(self._execute(run["id"], job_type, payload))
        await self._mirror_run_to_pg(run)
        return run

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return job_store.get_run(run_id)

    async def list_runs(self, limit: int = 50) -> list[Dict[str, Any]]:
        return job_store.list_runs(limit)

    async def create_schedule(
        self,
        name: str,
        job_type: str,
        payload: Dict[str, Any],
        cron: str,
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        schedule = job_store.create_schedule(
            name, job_type, payload, cron, webhook_url=webhook_url
        )
        from core.scheduler import register_schedule

        register_schedule(schedule)
        await self._mirror_schedule_to_pg(schedule)
        return schedule

    async def list_schedules(self) -> list[Dict[str, Any]]:
        return job_store.list_schedules()

    async def delete_schedule(self, schedule_id: int) -> bool:
        from core.scheduler import unregister_schedule

        if not job_store.delete_schedule(schedule_id):
            return False
        unregister_schedule(schedule_id)
        return True

    async def toggle_schedule(self, schedule_id: int, enabled: bool) -> Optional[Dict[str, Any]]:
        from core.scheduler import register_schedule, unregister_schedule

        schedule = job_store.update_schedule(schedule_id, enabled=enabled)
        if not schedule:
            return None
        if enabled:
            register_schedule(schedule)
        else:
            unregister_schedule(schedule_id)
        return schedule

    async def _execute(self, run_id: str, job_type: str, payload: Dict[str, Any]) -> None:
        run = job_store.get_run(run_id) or {}
        scheduled_job_id = run.get("scheduled_job_id")
        schedule = (
            job_store.get_schedule(int(scheduled_job_id))
            if scheduled_job_id is not None
            else None
        )
        now = datetime.now(timezone.utc).isoformat()
        job_store.update_run(run_id, status="running")
        try:
            result = await self._handlers[job_type](payload)
            finished = datetime.now(timezone.utc).isoformat()
            job_store.update_run(
                run_id,
                status="completed",
                result=result,
                finished_at=finished,
            )
            logger.info("Job %s completed: %s", run_id, job_type)
            await self._notify_webhook(
                schedule, run_id, job_type, "completed", payload, result=result, error=None
            )
        except Exception as exc:
            finished = datetime.now(timezone.utc).isoformat()
            job_store.update_run(
                run_id,
                status="failed",
                error=str(exc),
                finished_at=finished,
            )
            logger.exception("Job %s failed: %s", run_id, exc)
            await self._notify_webhook(
                schedule, run_id, job_type, "failed", payload, result=None, error=str(exc)
            )

    async def _notify_webhook(
        self,
        schedule: Optional[Dict[str, Any]],
        run_id: str,
        job_type: str,
        status: str,
        payload: Dict[str, Any],
        *,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> None:
        if not schedule or not schedule.get("webhook_url"):
            return
        from core.webhook_notify import send_webhook

        await send_webhook(
            schedule["webhook_url"],
            event="job.finished",
            job_type=job_type,
            run_id=run_id,
            status=status,
            payload=payload,
            result=result,
            error=error,
            schedule_id=schedule.get("id"),
            schedule_name=schedule.get("name"),
        )

    async def _mirror_run_to_pg(self, run: Dict[str, Any]) -> None:
        if not db_state.database_available:
            return
        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from core.database import engine
            from infrastructure.persistence.models import JobRunRecord

            async with AsyncSession(engine) as session:
                record = JobRunRecord(
                    id=run["id"],
                    scheduled_job_id=run.get("scheduled_job_id"),
                    job_type=run["job_type"],
                    status=run["status"],
                    payload=run.get("payload") or {},
                    result=run.get("result"),
                    error=run.get("error"),
                    created_at=datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")),
                    finished_at=None,
                )
                session.add(record)
                await session.commit()
        except Exception as exc:
            logger.debug("PG mirror run skipped: %s", exc)

    async def _mirror_schedule_to_pg(self, schedule: Dict[str, Any]) -> None:
        if not db_state.database_available:
            return
        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from core.database import engine
            from infrastructure.persistence.models import ScheduledJobRecord

            async with AsyncSession(engine) as session:
                record = ScheduledJobRecord(
                    id=schedule["id"],
                    name=schedule["name"],
                    job_type=schedule["job_type"],
                    payload=schedule.get("payload") or {},
                    cron=schedule["cron"],
                    enabled=schedule.get("enabled", True),
                    webhook_url=schedule.get("webhook_url"),
                    last_run_at=schedule.get("last_run_at"),
                    created_at=schedule.get("created_at"),
                )
                session.merge(record)
                await session.commit()
        except Exception as exc:
            logger.debug("PG mirror schedule skipped: %s", exc)


async def _handle_report_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
    from application.use_cases.reports.report_service import ReportService

    record = await ReportService().generate(
        int(payload["dataset_id"]),
        payload.get("report_type", "summary"),
        group_by=payload.get("group_by") or [],
        metrics=payload.get("metrics") or [],
        top_n=int(payload.get("top_n", 10)),
        chart_types=payload.get("chart_types") or ["bar"],
        filters=payload.get("filters") or [],
    )
    return {"report_id": record.get("id"), "name": record.get("name")}


async def _handle_knowledge_ingest(payload: Dict[str, Any]) -> Dict[str, Any]:
    import base64

    from application.use_cases.knowledge.knowledge_service import KnowledgeService

    async with _knowledge_job_lock:
        content = payload.get("content")
        if not content and payload.get("content_b64"):
            content = base64.b64decode(payload["content_b64"])
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise ValueError("content is required for knowledge_ingest")
        result = await KnowledgeService().ingest_upload(
            filename=payload.get("filename") or "document.txt",
            content=content,
            title=payload.get("title"),
            description=payload.get("description"),
            collection=payload.get("collection", "quart_knowledge"),
        )
        return result


async def _handle_knowledge_reindex(payload: Dict[str, Any]) -> Dict[str, Any]:
    from application.use_cases.knowledge.knowledge_service import KnowledgeService

    async with _knowledge_job_lock:
        document_id = payload.get("document_id")
        if not document_id:
            raise ValueError("document_id is required")
        return await KnowledgeService().reindex_document(
            document_id,
            collection=payload.get("collection"),
        )


async def _handle_ai_analyze(payload: Dict[str, Any]) -> Dict[str, Any]:
    from application.use_cases.ai.ai_service import AIService

    dataset_id = int(payload["dataset_id"])
    return await AIService().analyze_dataset(
        dataset_id,
        question=payload.get("question"),
        save_report=bool(payload.get("save_report", True)),
        include_correlations=bool(payload.get("include_correlations", True)),
        sample_rows=int(payload.get("sample_rows") or 12),
        filters=payload.get("filters"),
        group_by=payload.get("group_by"),
        aggregations=payload.get("aggregations"),
        model_path=payload.get("model_path"),
    )


def register_default_handlers() -> None:
    JobService.register("report_generate", _handle_report_generate)
    JobService.register("knowledge_ingest", _handle_knowledge_ingest)
    JobService.register("knowledge_reindex", _handle_knowledge_reindex)
    JobService.register("ai_analyze", _handle_ai_analyze)
