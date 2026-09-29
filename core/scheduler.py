"""APScheduler: cron-задачи для отчётов и индексации."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from application.use_cases.jobs.job_service import JobService
from infrastructure.storage import job_store

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_job_service = JobService()


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def register_schedule(schedule: Dict[str, Any]) -> None:
    if not schedule.get("enabled", True):
        return
    scheduler = get_scheduler()
    job_id = f"schedule_{schedule['id']}"

    try:
        trigger = _parse_cron(schedule["cron"])
    except Exception as exc:
        logger.warning("Invalid cron for schedule %s: %s", schedule.get("id"), exc)
        return

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        _run_scheduled,
        trigger=trigger,
        id=job_id,
        kwargs={
            "schedule_id": schedule["id"],
            "job_type": schedule["job_type"],
            "payload": schedule.get("payload") or {},
        },
        replace_existing=True,
    )
    logger.info("Registered schedule %s (%s)", schedule.get("name"), schedule.get("cron"))


def unregister_schedule(schedule_id: int) -> None:
    scheduler = get_scheduler()
    job_id = f"schedule_{schedule_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unregistered schedule %s", schedule_id)


def _parse_cron(cron: str) -> CronTrigger:
    parts = cron.strip().split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
    if len(parts) == 6:
        second, minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            second=second,
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
    raise ValueError(f"Unsupported cron format: {cron}")


async def _run_scheduled(schedule_id: int, job_type: str, payload: Dict[str, Any]) -> None:
    logger.info("Running scheduled job %s type=%s", schedule_id, job_type)
    await _job_service.submit(job_type, payload, scheduled_job_id=schedule_id)
    job_store.update_schedule(
        schedule_id,
        last_run_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    )


def start_scheduler() -> None:
    from application.use_cases.jobs.job_service import register_default_handlers

    register_default_handlers()
    scheduler = get_scheduler()
    for schedule in job_store.list_schedules():
        register_schedule(schedule)
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started")


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
