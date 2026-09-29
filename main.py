"""Точка входа FastAPI: API аналитики, статика SPA, lifespan и обработка ошибок."""

import os
from pathlib import Path
import sys

# В frozen-сборке конфигурация и runtime-данные находятся рядом с EXE, а не во
# временном каталоге распаковки PyInstaller и не в случайной рабочей директории.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)

import core.env_bootstrap  # noqa: E402,F401 — до torch/transformers

# PyInstaller запускает тот же EXE для изолированной индексации. Обработать этот
# режим до импорта FastAPI, БД и планировщика, чтобы рабочий процесс оставался
# лёгким и не запускал второй HTTP-сервер.
if getattr(sys, "frozen", False) and "--knowledge-index-worker" in sys.argv:
    sys.argv.remove("--knowledge-index-worker")
    from infrastructure.knowledge.index_worker import main as _index_worker_main

    raise SystemExit(_index_worker_main())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import logging

from core.config import settings
from core.logging_config import setup_logging  # <-- Изменено имя модуля
from core.database import engine
from core.exceptions import AppException
from core.db_state import init_database
from core.scheduler import start_scheduler, stop_scheduler
from api.v1.endpoints import auth, datasets, etl, analysis, reports, export_data, knowledge, jobs, metadata

APP_BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = APP_BUNDLE_DIR / "static"

# Настройка логирования
logger = setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения: инициализация БД при старте, dispose при shutdown."""
    logger.info("Starting Data Analytics System...")

    # PostgreSQL: схема + синхронизация manifest
    await init_database()

    from infrastructure.storage import user_store

    user_store.ensure_default_users()

    start_scheduler()

    if settings.CHROMA_STARTUP_CHECK:
        try:
            from infrastructure.ai.rag import chroma_client

            health = chroma_client.check_collection_health("quart_knowledge")
            if not health.get("ok"):
                logger.warning(
                    "ChromaDB повреждена или недоступна: %s. "
                    "Вызовите POST /api/v1/knowledge/repair-chroma",
                    health.get("error"),
                )
        except Exception as exc:
            logger.warning("Chroma health check skipped: %s", exc)

    logger.info("System started successfully")

    yield

    stop_scheduler()

    # Shutdown
    await engine.dispose()
    logger.info("Shutting down Data Analytics System...")

app = FastAPI(
    title=settings.APP_NAME,
    description="Automated analysis of structured and unstructured data with AI",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(datasets.router, prefix="/api/v1")
app.include_router(etl.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(export_data.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(metadata.router, prefix="/api/v1")

# Обработчики исключений
@app.exception_handler(AppException)
async def app_exception_handler(request, exc: AppException):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "message": exc.message,
            "details": exc.details
        }
    )

@app.get("/api")
async def api_info():
    return {
        "message": "СЦ-отчеты API",
        "version": "1.0.0",
        "app_version": "0.1.0",
        "docs": "/docs" if settings.DEBUG else None,
        "redoc": "/redoc" if settings.DEBUG else None,
        "status": "running",
        "ui": "/",
    }

@app.get("/health")
async def health_check():
    from core import db_state
    from core.version_info import build_health_payload

    try:
        from importlib.metadata import version as pkg_version

        app_version = pkg_version("quart-2-01")
    except Exception:
        app_version = "0.1.0"

    return build_health_payload(
        app_version=app_version,
        environment=str(settings.ENVIRONMENT.value),
        debug=settings.DEBUG,
        postgresql=db_state.database_available,
    )

@app.get("/")
async def ui_root():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Директории с runtime-данными: изменения не должны перезапускать uvicorn --reload
_RELOAD_EXCLUDES = [
    "knowledge",
    "knowledge/**",
    "chroma_db",
    "chroma_db/**",
    "uploads",
    "uploads/**",
    "reports",
    "reports/**",
    "data",
    "data/**",
    "models",
    "models/**",
    ".venv",
    ".venv/**",
    "**/*.json",
    "**/*.json.tmp",
]

if __name__ == "__main__":
    import multiprocessing
    import uvicorn

    multiprocessing.freeze_support()
    use_reload = bool(settings.DEBUG and settings.UVICORN_RELOAD)
    if settings.DEBUG and not settings.UVICORN_RELOAD:
        logger.info(
            "Uvicorn reload disabled (UVICORN_RELOAD=false). "
            "Data dirs are excluded when reload is enabled."
        )
    frozen = bool(getattr(sys, "frozen", False))
    uvicorn.run(
        app if frozen else "main:app",
        host="0.0.0.0",
        port=8001,
        reload=use_reload and not frozen,
        reload_excludes=_RELOAD_EXCLUDES if use_reload and not frozen else None,
    )
