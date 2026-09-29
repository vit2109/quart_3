"""REST API базы знаний: загрузка, поиск, RAG, управление векторной БД."""

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from api.deps import AdminDep, AnalystDep, ViewerDep
from application.use_cases.knowledge.knowledge_service import KnowledgeService
from core.config import settings
from core.exceptions import AppException, DuplicateError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class SearchRequest(BaseModel):
    query: str
    mode: str = Field(default="hybrid", description="hybrid | vector | keyword")
    top_k: int = Field(default=8, ge=1, le=30)
    document_id: Optional[str] = None
    collection: str = "quart_knowledge"
    with_llm: bool = Field(
        default=False,
        description="После поиска обработать найденные фрагменты через LLM",
    )


class AskRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    top_k: int = Field(default=6, ge=1, le=20)
    document_id: Optional[str] = None
    collection: str = "quart_knowledge"


class ChunkUpdateRequest(BaseModel):
    text: str
    metadata: Optional[Dict[str, Any]] = None


class DatasetIngestRequest(BaseModel):
    title: Optional[str] = None
    collection: str = "quart_knowledge"


def _svc() -> KnowledgeService:
    return KnowledgeService()


@router.get("/stats")
async def knowledge_stats(_user: ViewerDep, collection: str = Query("quart_knowledge")):
    """Статистика документов, фрагментов и векторной коллекции."""
    data = await _svc().stats(collection)
    return {"status": "success", "data": data}


@router.post("/warmup")
async def warmup_models(_user: AnalystDep):
    """Фоновая подгрузка модели эмбеддингов (не блокирует UI)."""
    import asyncio

    from infrastructure.ai.rag.embedding_service import embed_texts

    async def _run() -> None:
        try:
            await asyncio.to_thread(embed_texts, ["warmup"])
        except Exception as exc:
            logger.warning("Knowledge warmup failed: %s", exc)

    asyncio.create_task(_run())
    return {"status": "success", "message": "Model warmup started in background"}


@router.post("/repair-chroma")
async def repair_chroma(_user: AdminDep, collection: str = Query("quart_knowledge")):
    """Пересоздать повреждённую ChromaDB и восстановить векторы из manifest."""
    from infrastructure.ai.rag import chroma_client

    try:
        data = await asyncio.to_thread(
            chroma_client.rebuild_collection_from_manifest, collection
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "success", "data": data}


@router.post("/refresh-chroma")
async def refresh_chroma_cache(_user: AdminDep, collection: str = Query("quart_knowledge")):
    """Сбросить кэш Chroma после индексации в subprocess и перепроверить."""
    from infrastructure.ai.rag import chroma_client

    await asyncio.to_thread(chroma_client.invalidate_client_cache)
    data = chroma_client.check_collection_health(collection)
    return {"status": "success", "data": data}


@router.get("/chroma-health")
async def chroma_health(_user: ViewerDep, collection: str = Query("quart_knowledge")):
    """Проверка целостности векторной коллекции."""
    from infrastructure.ai.rag import chroma_client

    data = chroma_client.check_collection_health(collection)
    return {"status": "success", "data": data}


@router.post("/repair-manifest")
async def repair_chunks_manifest(_user: AdminDep, collection: str = Query("quart_knowledge")):
    """Восстановить chunks_manifest.json из ChromaDB."""
    from infrastructure.knowledge import chunk_store

    data = chunk_store.repair_manifest(collection)
    return {"status": "success", "data": data}


@router.get("/documents")
async def list_documents(_user: ViewerDep):
    """Список проиндексированных документов."""
    data = await _svc().list_documents()
    return {"status": "success", "data": data}


@router.get("/documents/by-dataset/{dataset_id}")
async def documents_by_dataset(dataset_id: int, _user: ViewerDep):
    """Документы базы знаний, связанные с табличным набором."""
    from infrastructure.knowledge.document_store import list_by_dataset_id

    items = list_by_dataset_id(dataset_id)
    return {"status": "success", "data": items}


@router.post("/documents/upload")
async def upload_document(
    _user: AnalystDep,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    collection: str = Form("quart_knowledge"),
    background: bool = Query(False, description="Индексировать в фоне (для больших файлов)"),
):
    """Загрузить txt/docx/pdf/таблицу, распарсить и проиндексировать."""
    import base64

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    use_background = background or bool(settings.KNOWLEDGE_FORCE_BACKGROUND)
    min_bg = int(settings.KNOWLEDGE_BACKGROUND_MIN_BYTES or 1)
    if len(content) >= min_bg and not use_background:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Файл {len(content) // 1024} КБ — синхронная индексация отключена. "
                "Используйте фоновую индексацию (включена по умолчанию)."
            ),
        )

    if use_background:
        from application.use_cases.jobs.job_service import JobService

        run = await JobService().submit(
            "knowledge_ingest",
            {
                "filename": file.filename or "document.txt",
                "content_b64": base64.b64encode(content).decode("ascii"),
                "title": title,
                "description": description,
                "collection": collection,
            },
        )
        return {
            "status": "success",
            "message": "Document queued for background indexing",
            "data": {"job_id": run["id"], "status": run["status"]},
        }

    try:
        data = await _svc().ingest_upload(
            filename=file.filename or "document.txt",
            content=content,
            title=title,
            description=description,
            collection=collection,
        )
    except DuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": exc.message,
                "details": exc.details,
            },
        ) from exc
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "message": "Document indexed", "data": data}


@router.post("/documents/ingest-dataset/{dataset_id}")
async def ingest_dataset(dataset_id: int, body: DatasetIngestRequest, _user: AnalystDep):
    """Добавить в базу знаний табличный набор из вкладки «Данные»."""
    try:
        data = await _svc().ingest_dataset(
            dataset_id,
            title=body.title,
            collection=body.collection,
        )
    except DuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": exc.message,
                "details": exc.details,
            },
        ) from exc
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "message": "Dataset indexed", "data": data}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, _user: AnalystDep):
    """Удалить документ и все его фрагменты из manifest и Chroma."""
    try:
        data = await _svc().delete_document(document_id)
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}


@router.post("/documents/{document_id}/reindex")
async def reindex_document(document_id: str, _user: AnalystDep):
    """Повторно проиндексировать сохранённый документ (если индексация прервалась)."""
    try:
        data = await _svc().reindex_document(document_id)
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "success",
        "message": "Document reindexed",
        "data": data,
    }


@router.get("/chunks")
async def list_chunks(
    _user: ViewerDep,
    document_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Панель управления: список фрагментов с фильтрацией."""
    data = await _svc().list_chunks(
        document_id=document_id,
        query=q,
        limit=limit,
        offset=offset,
    )
    return {"status": "success", "data": data}


@router.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str, _user: ViewerDep):
    """Получить один фрагмент по ID."""
    from infrastructure.knowledge import chunk_store

    item = chunk_store.get_chunk(chunk_id)
    if not item:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return {"status": "success", "data": item}


@router.put("/chunks/{chunk_id}")
async def update_chunk(chunk_id: str, body: ChunkUpdateRequest, _user: AnalystDep):
    """Редактировать текст фрагмента и переиндексировать embedding."""
    try:
        data = await _svc().update_chunk(chunk_id, body.text, body.metadata)
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}


@router.delete("/chunks/{chunk_id}")
async def delete_chunk(chunk_id: str, _user: AnalystDep):
    """Удалить фрагмент из manifest и Chroma."""
    try:
        data = await _svc().delete_chunk(chunk_id)
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}


@router.post("/search")
async def search_knowledge(body: SearchRequest, _user: ViewerDep):
    """Поиск по базе знаний; при with_llm=true — ответ через офлайн LLM (RAG)."""
    try:
        if body.with_llm:
            data = await _svc().ask(
                body.query,
                mode=body.mode,
                top_k=body.top_k,
                document_id=body.document_id,
                collection=body.collection,
            )
        else:
            data = await _svc().search(
                body.query,
                mode=body.mode,
                top_k=body.top_k,
                document_id=body.document_id,
                collection=body.collection,
            )
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}


@router.post("/ask")
async def ask_knowledge(body: AskRequest, _user: ViewerDep):
    """RAG-ответ офлайн LLM на основе найденных фрагментов."""
    try:
        data = await _svc().ask(
            body.query,
            mode=body.mode,
            top_k=body.top_k,
            document_id=body.document_id,
            collection=body.collection,
        )
    except AppException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": data}
