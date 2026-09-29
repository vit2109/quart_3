"""Синхронизация файловых manifest → PostgreSQL."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models import (
    DatasetRecord,
    ReportRecord,
    SavedViewRecord,
    ScheduledJobRecord,
    UserRecord,
)
from infrastructure.storage import dataset_store, job_store, report_store, user_store


class MetadataSyncService:
    """Зеркалирование JSON-манifest в PostgreSQL для запросов и админки."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def sync_all(self) -> Dict[str, int]:
        return {
            "users": await self.sync_users(),
            "datasets": await self.sync_datasets(),
            "reports": await self.sync_reports(),
            "schedules": await self.sync_schedules(),
            "saved_views": await self.sync_saved_views(),
        }

    async def sync_users(self) -> int:
        count = 0
        for user in user_store.list_users():
            if user.id is None:
                continue
            existing = await self.session.get(UserRecord, user.id)
            record = existing or UserRecord(id=user.id)
            record.email = user.email
            record.username = user.username
            record.hashed_password = user.hashed_password
            record.full_name = user.full_name
            record.role = user.role.value
            record.is_active = user.is_active
            record.created_at = user.created_at
            record.updated_at = user.updated_at
            record.last_login = user.last_login
            self.session.add(record)
            count += 1
        return count

    async def sync_datasets(self) -> int:
        count = 0
        for item in dataset_store.list_datasets():
            ds_id = int(item.get("id", 0))
            if not ds_id:
                continue
            existing = await self.session.get(DatasetRecord, ds_id)
            record = existing or DatasetRecord(id=ds_id)
            record.name = item.get("name") or f"Dataset {ds_id}"
            record.filename = item.get("filename")
            record.stored_as = item.get("stored_as")
            record.content_hash = item.get("content_hash")
            record.description = item.get("description")
            record.row_count = item.get("row_count")
            record.created_at = item.get("created_at")
            record.extra = {
                k: v
                for k, v in item.items()
                if k
                not in {
                    "id",
                    "name",
                    "filename",
                    "stored_as",
                    "content_hash",
                    "description",
                    "row_count",
                    "created_at",
                }
            }
            self.session.add(record)
            count += 1
        return count

    async def sync_reports(self) -> int:
        count = 0
        for item in report_store.list_reports():
            report_id = int(item.get("id", 0))
            if not report_id:
                continue
            full = report_store.get_report(report_id) or item
            existing = await self.session.get(ReportRecord, report_id)
            record = existing or ReportRecord(id=report_id)
            record.name = full.get("name")
            record.dataset_id = full.get("dataset_id")
            record.report_type = full.get("report_type")
            record.created_at = full.get("created_at")
            record.payload_path = str(report_id)
            self.session.add(record)
            count += 1
        return count

    async def sync_schedules(self) -> int:
        count = 0
        for item in job_store.list_schedules():
            sid = int(item.get("id", 0))
            if not sid:
                continue
            existing = await self.session.get(ScheduledJobRecord, sid)
            record = existing or ScheduledJobRecord(id=sid)
            record.name = item.get("name") or f"Schedule {sid}"
            record.job_type = item.get("job_type") or "report_generate"
            record.payload = item.get("payload") or {}
            record.cron = item.get("cron") or "0 8 * * *"
            record.enabled = bool(item.get("enabled", True))
            record.webhook_url = item.get("webhook_url")
            record.last_run_at = item.get("last_run_at")
            record.created_at = item.get("created_at")
            self.session.add(record)
            count += 1
        return count

    async def sync_saved_views(self) -> int:
        from infrastructure.storage import views_store

        count = 0
        for ds in dataset_store.list_datasets():
            ds_id = int(ds.get("id", 0))
            if not ds_id:
                continue
            for view in views_store.list_views(ds_id):
                full = views_store.get_view(ds_id, int(view["id"]))
                if not full:
                    continue
                view_id = int(full["id"])
                existing = await self.session.scalar(
                    select(SavedViewRecord).where(
                        SavedViewRecord.dataset_id == ds_id,
                        SavedViewRecord.view_id == view_id,
                    )
                )
                record = existing or SavedViewRecord(dataset_id=ds_id, view_id=view_id)
                record.name = full.get("name") or f"View {view_id}"
                record.pinned = bool(full.get("pinned"))
                record.mode = full.get("mode")
                record.config = {
                    k: v
                    for k, v in full.items()
                    if k
                    not in {"id", "dataset_id", "name", "pinned", "mode", "created_at", "updated_at"}
                }
                record.created_at = full.get("created_at")
                record.updated_at = full.get("updated_at")
                self.session.add(record)
                count += 1
        return count

    async def list_datasets_meta(self) -> list[Dict[str, Any]]:
        rows = await self.session.scalars(select(DatasetRecord).order_by(DatasetRecord.id))
        return [
            {
                "id": r.id,
                "name": r.name,
                "filename": r.filename,
                "row_count": r.row_count,
                "created_at": r.created_at,
            }
            for r in rows
        ]
