"""Клиент ChromaDB для персистентного векторного хранилища."""

from __future__ import annotations

import logging
import gc
import threading
import time
from typing import Any, Dict, List, Optional

import chromadb

from core.config import settings
from infrastructure.ai.rag.embedding_service import embed_query, embed_texts

logger = logging.getLogger(__name__)

UPSERT_BATCH_SIZE = max(1, int(getattr(settings, "EMBEDDING_BATCH_SIZE", 8) or 8))

_lock = threading.RLock()
_client: Optional[chromadb.PersistentClient] = None
_collections: Dict[str, Any] = {}


def invalidate_client_cache() -> None:
    """Сбросить кэш клиента после записи из другого процесса (index_worker)."""
    global _client, _collections
    with _lock:
        _collections.clear()
        _client = None
    gc.collect()


def _get_client() -> chromadb.PersistentClient:
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        return _client


def get_collection(name: str):
    """Получить или создать коллекцию Chroma."""
    with _lock:
        if name in _collections:
            return _collections[name]
        client = _get_client()
        collection = client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        _collections[name] = collection
        return collection


def _flat_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Chroma принимает только str/int/float/bool в metadata."""
    flat: Dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            flat[str(key)] = value
        else:
            flat[str(key)] = str(value)
    return flat


def reset_collection(collection_name: str) -> Dict[str, Any]:
    """Удалить и пересоздать коллекцию (при повреждении HNSW/pickle)."""
    client = _get_client()
    with _lock:
        try:
            client.delete_collection(collection_name)
        except Exception as exc:
            logger.warning("delete_collection(%s): %s", collection_name, exc)
    invalidate_client_cache()
    collection = get_collection(collection_name)
    count = collection.count()
    logger.info("Reset Chroma collection %s (count=%s)", collection_name, count)
    return {"collection": collection_name, "vector_count": count}


def check_collection_health(collection_name: str) -> Dict[str, Any]:
    """Проверить, что коллекция читается и принимает upsert."""
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            collection = get_collection(collection_name)
            count = collection.count()
            collection.peek(limit=1)
            return {"ok": True, "collection": collection_name, "vector_count": count}
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.info(
                    "Chroma health check failed, refreshing client cache: %s", exc
                )
                invalidate_client_cache()
                continue
    return {
        "ok": False,
        "collection": collection_name,
        "error": str(last_exc) if last_exc else "unknown error",
    }


def rebuild_collection_from_manifest(
    collection_name: str = "quart_knowledge",
    *,
    batch_size: int = UPSERT_BATCH_SIZE,
) -> Dict[str, Any]:
    """Пересоздать Chroma и залить векторы из chunks_manifest.json."""
    from infrastructure.knowledge import chunk_store

    chunks = chunk_store.all_chunks(collection=collection_name)
    reset_collection(collection_name)
    if not chunks:
        return {
            "collection": collection_name,
            "vector_count": 0,
            "reindexed": 0,
            "message": "Коллекция пуста, фрагментов в manifest нет",
        }

    total = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        ids = [c["id"] for c in batch]
        texts = [c.get("text") or "" for c in batch]
        metas = [c.get("metadata") or {} for c in batch]
        upsert_chunks(
            collection_name,
            ids=ids,
            texts=texts,
            metadatas=metas,
            batch_size=batch_size,
        )
        total += len(batch)

    return {
        "collection": collection_name,
        "vector_count": collection_stats(collection_name)["vector_count"],
        "reindexed": total,
    }


def upsert_chunks(
    collection_name: str,
    *,
    ids: List[str],
    texts: List[str],
    metadatas: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = UPSERT_BATCH_SIZE,
) -> None:
    """Добавить или обновить фрагменты с эмбеддингами (пакетами)."""
    if not ids:
        return
    collection = get_collection(collection_name)
    meta_list = metadatas or [{} for _ in ids]
    total = len(ids)
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_ids = ids[start:end]
        batch_texts = texts[start:end]
        batch_metas = meta_list[start:end]
        embeddings = embed_texts(batch_texts)
        try:
            collection.upsert(
                ids=batch_ids,
                documents=batch_texts,
                embeddings=embeddings,
                metadatas=[_flat_metadata(m) for m in batch_metas],
            )
        except chromadb.errors.InternalError as exc:
            raise chromadb.errors.InternalError(
                f"{exc}. "
                "ChromaDB повреждена — выполните POST /api/v1/knowledge/repair-chroma"
            ) from exc
        logger.info(
            "Upserted chunks %s-%s/%s into %s",
            start + 1,
            end,
            total,
            collection_name,
        )
        del embeddings
        gc.collect()
        pause_ms = int(getattr(settings, "KNOWLEDGE_INDEX_PAUSE_MS", 0) or 0)
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)


def delete_chunks(collection_name: str, ids: List[str]) -> None:
    if not ids:
        return
    collection = get_collection(collection_name)
    collection.delete(ids=ids)


def vector_search(
    collection_name: str,
    query: str,
    *,
    n_results: int = 8,
    where: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Семантический поиск по коллекции."""
    collection = get_collection(collection_name)
    if collection.count() == 0:
        return []

    embedding = embed_query(query)
    kwargs: Dict[str, Any] = {
        "query_embeddings": [embedding],
        "n_results": min(n_results, max(collection.count(), 1)),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    raw = collection.query(**kwargs)
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    dists = (raw.get("distances") or [[]])[0]
    ids = (raw.get("ids") or [[]])[0]

    results = []
    for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists):
        vector_score = max(0.0, 1.0 - float(dist or 1.0))
        results.append(
            {
                "id": chunk_id,
                "text": doc,
                "metadata": meta or {},
                "distance": dist,
                "vector_score": round(vector_score, 4),
            }
        )
    return results


def collection_stats(collection_name: str) -> Dict[str, Any]:
    collection = get_collection(collection_name)
    return {"collection": collection_name, "vector_count": collection.count()}
