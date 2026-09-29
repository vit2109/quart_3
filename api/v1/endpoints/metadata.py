"""Метаданные из PostgreSQL (если доступен)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core import db_state
from core.security import require_role
from domain.entities.user import User, UserRole

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.get("/datasets")
async def list_datasets_meta(
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Список наборов из PostgreSQL (зеркало manifest)."""
    if not db_state.database_available:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL unavailable — use /datasets endpoint",
        )
    from sqlalchemy.ext.asyncio import AsyncSession
    from core.database import engine
    from application.use_cases.metadata.metadata_sync_service import MetadataSyncService

    async with AsyncSession(engine) as session:
        data = await MetadataSyncService(session).list_datasets_meta()
    return {"status": "success", "data": data}


@router.post("/sync")
async def sync_metadata(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Принудительная синхронизация JSON manifest → PostgreSQL."""
    if not db_state.database_available:
        raise HTTPException(status_code=503, detail="PostgreSQL unavailable")
    from sqlalchemy.ext.asyncio import AsyncSession
    from core.database import engine
    from application.use_cases.metadata.metadata_sync_service import MetadataSyncService

    async with AsyncSession(engine) as session:
        stats = await MetadataSyncService(session).sync_all()
        await session.commit()
    return {"status": "success", "data": stats}
