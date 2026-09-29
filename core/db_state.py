"""Флаг доступности PostgreSQL и инициализация схемы."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import Base, engine

logger = logging.getLogger(__name__)

database_available: bool = False


async def init_database() -> bool:
    """Проверить подключение, создать таблицы, синхронизировать метаданные."""
    global database_available
    from infrastructure.persistence import models  # noqa: F401

    if not Base.metadata.tables:
        logger.info("No ORM models registered")
        database_available = False
        return False

    import asyncio

    timeout = max(1, int(getattr(settings, "DATABASE_CONNECT_TIMEOUT", 3) or 3))

    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        database_available = False
        if settings.DEBUG:
            logger.warning(
                "PostgreSQL unavailable (%s). File stores and job_store remain active.",
                exc or "connection timeout",
            )
        else:
            logger.error("PostgreSQL required in production but unavailable: %s", exc)
            raise
        return False

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        database_available = True
        logger.info("PostgreSQL connected, schema ready")
        await _sync_metadata()
        return True
    except Exception as exc:
        database_available = False
        if settings.DEBUG:
            logger.warning(
                "PostgreSQL schema init failed (%s). File stores remain active.",
                exc,
            )
        else:
            logger.error("PostgreSQL schema init failed: %s", exc)
            raise
        return False


async def _sync_metadata() -> None:
    from application.use_cases.metadata.metadata_sync_service import (
        MetadataSyncService,
    )

    try:
        async with AsyncSession(engine) as session:
            stats = await MetadataSyncService(session).sync_all()
            await session.commit()
            logger.info("Metadata sync: %s", stats)
    except Exception as exc:
        logger.warning("Metadata sync skipped: %s", exc)


async def get_session() -> AsyncSession:
    return AsyncSession(engine)
