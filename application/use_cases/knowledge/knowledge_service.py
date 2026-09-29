"""Оркестрация базы знаний: индексация, поиск, RAG-ответы, CRUD фрагментов."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import settings
from core.exceptions import DuplicateError, NotFoundError, ValidationError
from core.memory_guard import ensure_min_free_ram
from infrastructure.ai.llama_client import LocalLLMClient
from infrastructure.ai.rag import chroma_client, hybrid_search
from infrastructure.knowledge import chunk_store, document_parser, document_store
from infrastructure.storage import dataset_store

logger = logging.getLogger(__name__)

_index_lock = threading.Lock()

DEFAULT_COLLECTION = "quart_knowledge"

RAG_SYSTEM = """Ты — офлайн AI-ассистент по корпоративной базе знаний.
Отвечай на русском языке, опираясь ТОЛЬКО на предоставленный контекст.
Если информации недостаточно — честно скажи об этом.
Структурируй ответ: краткий вывод, детали, источники (имя документа / фрагмент)."""


class KnowledgeService:
    """Сервис текстовой базы знаний с векторным и гибридным поиском."""

    def __init__(self) -> None:
        self.llm = LocalLLMClient()

    async def ingest_upload(
        self,
        *,
        filename: str,
        content: bytes,
        title: Optional[str] = None,
        description: Optional[str] = None,
        collection: str = DEFAULT_COLLECTION,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._ingest_upload_blocking,
            filename,
            content,
            title,
            description,
            collection,
        )

    async def reindex_document(
        self, document_id: str, *, collection: Optional[str] = None
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._reindex_document_blocking, document_id, collection
        )

    def _reindex_document_blocking(
        self, document_id: str, collection: Optional[str]
    ) -> Dict[str, Any]:
        doc = document_store.get_document(document_id)
        if not doc:
            raise NotFoundError(f"Document {document_id} not found")
        path = document_store.get_document_path(document_id)
        if not path:
            raise NotFoundError(f"Document file for {document_id} not found")
        target_collection = collection or doc.get("collection") or DEFAULT_COLLECTION
        return self._index_document_by_id(document_id, target_collection)

    def index_document_inprocess(
        self, document_id: str, *, collection: Optional[str] = None
    ) -> Dict[str, Any]:
        """Индексация в текущем процессе (вызывается из index_worker)."""
        doc = document_store.get_document(document_id)
        if not doc:
            raise NotFoundError(f"Document {document_id} not found")
        path = document_store.get_document_path(document_id)
        if not path:
            raise NotFoundError(f"Document file for {document_id} not found")
        text, parse_meta = document_parser.parse_file(path)
        target_collection = collection or doc.get("collection") or DEFAULT_COLLECTION
        return self._index_text(
            document=doc,
            text=text,
            parse_meta=parse_meta,
            collection=target_collection,
        )

    def _index_document_by_id(
        self, document_id: str, collection: str
    ) -> Dict[str, Any]:
        # В one-file EXE sys.executable указывает на само приложение,
        # поэтому `exe -m index_worker` недоступен.
        if settings.KNOWLEDGE_USE_SUBPROCESS and not getattr(sys, "frozen", False):
            return self._index_via_subprocess(document_id, collection)
        return self.index_document_inprocess(document_id, collection=collection)

    def _index_via_subprocess(
        self, document_id: str, collection: str
    ) -> Dict[str, Any]:
        if not _index_lock.acquire(blocking=False):
            raise ValidationError(
                "Индексация уже выполняется. Дождитесь завершения текущей задачи."
            )
        try:
            ensure_min_free_ram(
                int(settings.KNOWLEDGE_MIN_FREE_RAM_MB or 0),
                operation="запуска индексации",
            )
            cmd = [
                sys.executable,
                "-m",
                "infrastructure.knowledge.index_worker",
                document_id,
                "--collection",
                collection,
            ]
            timeout = max(60, int(settings.KNOWLEDGE_SUBPROCESS_TIMEOUT or 3600))
            logger.info("Starting index subprocess: %s", " ".join(cmd))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(Path(__file__).resolve().parents[3]),
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                raise ValidationError(
                    err or "Subprocess indexing failed with no error message"
                )
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"Invalid subprocess output: {proc.stdout[:500]}"
                ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                f"Индексация превысила лимит {settings.KNOWLEDGE_SUBPROCESS_TIMEOUT} с"
            ) from exc
        finally:
            _index_lock.release()
            chroma_client.invalidate_client_cache()

    def _ingest_upload_blocking(
        self,
        filename: str,
        content: bytes,
        title: Optional[str],
        description: Optional[str],
        collection: str,
    ) -> Dict[str, Any]:
        suffix = Path(filename).suffix.lower()
        if suffix not in document_parser.SUPPORTED_SUFFIXES:
            raise ValidationError(
                f"Unsupported type {suffix}. Supported: {sorted(document_parser.SUPPORTED_SUFFIXES)}"
            )

        doc = document_store.save_document(
            original_filename=filename,
            content=content,
            title=title,
            description=description,
            source_type=document_parser.detect_source_type(suffix),
            collection=collection,
        )

        path = document_store.get_document_path(doc["id"])
        if not path:
            raise NotFoundError("Saved document file not found")

        text, _parse_meta = document_parser.parse_file(path)
        if not text.strip():
            raise ValidationError(
                "В документе нет текста для индексации. "
                "Для DOCX убедитесь, что файл содержит текст, а не только изображения."
            )

        return self._index_document_by_id(doc["id"], collection)

    async def ingest_dataset(
        self,
        dataset_id: int,
        *,
        title: Optional[str] = None,
        collection: str = DEFAULT_COLLECTION,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._ingest_dataset_blocking, dataset_id, title, collection
        )

    def _ingest_dataset_blocking(
        self,
        dataset_id: int,
        title: Optional[str],
        collection: str,
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        path = dataset_store.get_dataset_path(dataset_id)
        if not path:
            raise NotFoundError(f"Dataset file for {dataset_id} not found")

        text, parse_meta = document_parser.parse_dataset_rows(path)
        pseudo_name = f"dataset_{dataset_id}_{item.get('filename', 'data')}"
        doc = document_store.save_document(
            original_filename=pseudo_name,
            content=text.encode("utf-8"),
            title=title or f"Датасет #{dataset_id}: {item.get('name')}",
            description=f"Импорт из табличного набора #{dataset_id}",
            source_type="dataset",
            collection=collection,
            extra_meta={"dataset_id": dataset_id},
        )
        parse_meta["dataset_id"] = dataset_id
        if not text.strip():
            raise ValidationError("Датасет не содержит текста для индексации")
        return self._index_document_by_id(doc["id"], collection)

    def _index_text(
        self,
        *,
        document: Dict[str, Any],
        text: str,
        parse_meta: Dict[str, Any],
        collection: str,
    ) -> Dict[str, Any]:
        doc_id = document["id"]
        if not _index_lock.acquire(blocking=False):
            raise ValidationError(
                "Индексация уже выполняется. Дождитесь завершения или перезапустите сервер."
            )
        try:
            ensure_min_free_ram(
                int(settings.KNOWLEDGE_MIN_FREE_RAM_MB or 0),
                operation="индексации",
            )
            return self._index_text_locked(
                document=document,
                text=text,
                parse_meta=parse_meta,
                collection=collection,
                doc_id=doc_id,
            )
        finally:
            _index_lock.release()

    def _index_text_locked(
        self,
        *,
        document: Dict[str, Any],
        text: str,
        parse_meta: Dict[str, Any],
        collection: str,
        doc_id: str,
    ) -> Dict[str, Any]:
        # Старый индекс остаётся доступным до полного успеха переиндексации.
        previous_page = chunk_store.list_chunks(document_id=doc_id, limit=1_000_000)
        previous_ids = [item["id"] for item in previous_page.get("items") or []]

        chunk_parts = document_parser.chunk_text(
            text,
            base_metadata={
                "document_id": doc_id,
                "document_title": document.get("title"),
                "filename": document.get("filename"),
                "source_type": document.get("source_type"),
                "collection": collection,
            },
        )

        if not chunk_parts:
            raise ValidationError(
                "В документе нет текста для индексации. "
                "Для DOCX убедитесь, что файл содержит текст, а не только изображения."
            )

        max_chunks = int(settings.KNOWLEDGE_MAX_CHUNKS or 400)
        truncated = False
        if len(chunk_parts) > max_chunks:
            truncated = True
            chunk_parts = chunk_parts[:max_chunks]

        batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE or 2))
        pause_ms = max(0, int(settings.KNOWLEDGE_INDEX_PAUSE_MS or 0))
        now = datetime.now(timezone.utc).isoformat()
        total_indexed = 0
        upserted_ids: List[str] = []

        try:
            for start in range(0, len(chunk_parts), batch_size):
                batch = chunk_parts[start : start + batch_size]
                records: List[Dict[str, Any]] = []
                ids: List[str] = []
                texts: List[str] = []
                metas: List[Dict[str, Any]] = []

                for part in batch:
                    chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                    meta = part["metadata"]
                    record = {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "document_title": document.get("title"),
                        "text": part["text"],
                        "metadata": meta,
                        "char_count": len(part["text"]),
                        "word_count": len(part["text"].split()),
                        "collection": collection,
                        "created_at": now,
                        "updated_at": now,
                    }
                    records.append(record)
                    ids.append(chunk_id)
                    texts.append(part["text"])
                    metas.append(meta)

                chroma_client.upsert_chunks(
                    collection,
                    ids=ids,
                    texts=texts,
                    metadatas=metas,
                    batch_size=batch_size,
                )
                upserted_ids.extend(ids)
                chunk_store.add_chunks(records)
                total_indexed += len(records)
                logger.info(
                    "Indexed batch %s-%s for %s",
                    start + 1,
                    start + len(batch),
                    doc_id,
                )
                del records, ids, texts, metas
                gc.collect()
                if pause_ms > 0:
                    time.sleep(pause_ms / 1000.0)

            extra = dict(parse_meta)
            if truncated:
                extra["chunks_truncated"] = True
                extra["chunks_limit"] = max_chunks
            document_store.update_document(
                doc_id, chunk_count=total_indexed, extra=extra
            )
            if previous_ids:
                try:
                    chroma_client.delete_chunks(collection, previous_ids)
                    chunk_store.delete_chunks(previous_ids)
                except Exception as cleanup_exc:
                    logger.warning(
                        "New index is ready, but old chunks for %s could not be removed: %s",
                        doc_id,
                        cleanup_exc,
                    )
        except Exception as exc:
            if upserted_ids:
                try:
                    chroma_client.delete_chunks(collection, upserted_ids)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Failed to rollback Chroma chunks for %s: %s",
                        doc_id,
                        cleanup_exc,
                    )
                try:
                    chunk_store.delete_chunks(upserted_ids)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Failed to rollback manifest chunks for %s: %s",
                        doc_id,
                        cleanup_exc,
                    )
            logger.exception("Indexing failed for document %s", doc_id)
            msg = str(exc)
            if "chroma" in msg.lower() or "hnsw" in msg.lower() or "pickle" in msg.lower():
                msg = (
                    "Векторная база ChromaDB повреждена. "
                    "Нажмите «Восстановить Chroma» на вкладке «База знаний» "
                    "или вызовите POST /api/v1/knowledge/repair-chroma, "
                    "затем переиндексируйте документ."
                )
            raise ValidationError(msg) from exc

        return {
            "document": document_store.get_document(doc_id),
            "chunks_indexed": total_indexed,
            "collection": collection,
            "parse_meta": parse_meta,
            "truncated": truncated,
            "chunks_limit": max_chunks if truncated else None,
        }

    async def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        top_k: Optional[int] = None,
        document_id: Optional[str] = None,
        collection: str = DEFAULT_COLLECTION,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._search_blocking, query, mode, top_k, document_id, collection
        )

    def _search_blocking(
        self,
        query: str,
        mode: str,
        top_k: Optional[int],
        document_id: Optional[str],
        collection: str,
    ) -> Dict[str, Any]:
        if not query.strip():
            raise ValidationError("Query is empty")

        k = top_k or settings.RAG_TOP_K
        mode = (mode or "hybrid").lower()

        if mode == "vector":
            hits = chroma_client.vector_search(
                collection,
                query,
                n_results=k,
                where={"document_id": document_id} if document_id else None,
            )
            for h in hits:
                h["hybrid_score"] = h.get("vector_score", 0)
                h["keyword_score"] = 0.0
        elif mode == "keyword":
            candidates = chunk_store.all_chunks(collection)
            if document_id:
                candidates = [
                    item for item in candidates if item.get("document_id") == document_id
                ]
            hits = hybrid_search.lexical_search(query, candidates, limit=k)
            for hit in hits:
                hit["vector_score"] = 0.0
                hit["hybrid_score"] = hit["keyword_score"]
        else:
            hits = hybrid_search.hybrid_search(
                collection, query, top_k=k, document_id=document_id
            )

        return {
            "query": query,
            "mode": mode,
            "collection": collection,
            "results": hits,
            "total": len(hits),
        }

    async def ask(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        top_k: Optional[int] = None,
        document_id: Optional[str] = None,
        collection: str = DEFAULT_COLLECTION,
    ) -> Dict[str, Any]:
        timeout = max(int(settings.LLM_TIMEOUT or 900), 300)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._ask_blocking, query, mode, top_k, document_id, collection
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ValidationError(
                f"AI-ответ превысил лимит {timeout} с. Увеличьте LLM_TIMEOUT."
            ) from exc

    def _ask_blocking(
        self,
        query: str,
        mode: str,
        top_k: Optional[int],
        document_id: Optional[str],
        collection: str,
    ) -> Dict[str, Any]:
        search = self._search_blocking(query, mode, top_k, document_id, collection)
        hits = search.get("results") or []
        if not hits:
            return {
                "query": query,
                "mode": mode,
                "answer": "В базе знаний не найдено релевантных фрагментов по вашему запросу.",
                "sources": [],
            }

        context_blocks = []
        sources = []
        for i, hit in enumerate(hits, start=1):
            meta = hit.get("metadata") or {}
            title = meta.get("document_title") or meta.get("filename") or hit["id"]
            context_blocks.append(f"[{i}] ({title})\n{hit.get('text')}")
            sources.append(
                {
                    "rank": i,
                    "chunk_id": hit["id"],
                    "document_title": title,
                    "score": hit.get("hybrid_score", hit.get("vector_score", 0)),
                    "page_number": meta.get("page_number"),
                    "section_title": meta.get("section_title"),
                    "preview": (hit.get("text") or "")[:240],
                }
            )

        prompt = (
            "Контекст из базы знаний:\n\n"
            + "\n\n---\n\n".join(context_blocks)
            + f"\n\nВопрос пользователя:\n{query}\n"
        )

        answer = asyncio.run(
            self.llm.generate_text(
                prompt,
                system=RAG_SYSTEM,
                max_tokens=700,
                temperature=0.3,
            )
        )

        return {
            "query": query,
            "mode": mode,
            "answer": answer,
            "sources": sources,
            "search": search,
        }

    async def list_documents(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(document_store.list_documents)

    async def delete_document(self, document_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._delete_document_blocking, document_id)

    def _delete_document_blocking(self, document_id: str) -> Dict[str, Any]:
        doc = document_store.get_document(document_id)
        if not doc:
            raise NotFoundError(f"Document {document_id} not found")
        collection = doc.get("collection") or DEFAULT_COLLECTION
        chunk_ids = chunk_store.delete_by_document(document_id)
        if chunk_ids:
            chroma_client.delete_chunks(collection, chunk_ids)
        removed = document_store.delete_document(document_id)
        return {"document": removed, "chunks_removed": len(chunk_ids)}

    async def list_chunks(
        self,
        *,
        document_id: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            chunk_store.list_chunks,
            document_id=document_id,
            query=query,
            limit=limit,
            offset=offset,
        )

    async def update_chunk(
        self, chunk_id: str, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._update_chunk_blocking, chunk_id, text, metadata
        )

    def _update_chunk_blocking(
        self, chunk_id: str, text: str, metadata: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        existing = chunk_store.get_chunk(chunk_id)
        if not existing:
            raise NotFoundError(f"Chunk {chunk_id} not found")
        updated = chunk_store.update_chunk(chunk_id, text, metadata)
        collection = existing.get("collection") or DEFAULT_COLLECTION
        chroma_client.upsert_chunks(
            collection,
            ids=[chunk_id],
            texts=[text],
            metadatas=[updated.get("metadata") or {}],
        )
        return updated

    async def delete_chunk(self, chunk_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._delete_chunk_blocking, chunk_id)

    def _delete_chunk_blocking(self, chunk_id: str) -> Dict[str, Any]:
        existing = chunk_store.get_chunk(chunk_id)
        if not existing:
            raise NotFoundError(f"Chunk {chunk_id} not found")
        collection = existing.get("collection") or DEFAULT_COLLECTION
        chroma_client.delete_chunks(collection, [chunk_id])
        removed = chunk_store.delete_chunk(chunk_id)
        doc_id = existing.get("document_id")
        if doc_id:
            remaining = chunk_store.list_chunks(document_id=doc_id, limit=1)
            document_store.update_document(
                doc_id,
                chunk_count=remaining.get("total", 0),
            )
        return removed

    async def stats(self, collection: str = DEFAULT_COLLECTION) -> Dict[str, Any]:
        return await asyncio.to_thread(self._stats_blocking, collection)

    def _stats_blocking(self, collection: str) -> Dict[str, Any]:
        health = chroma_client.check_collection_health(collection)
        if health.get("ok"):
            vector = {
                "collection": collection,
                "vector_count": health.get("vector_count", 0),
            }
        else:
            vector = {
                "collection": collection,
                "vector_count": None,
                "error": health.get("error"),
                "needs_repair": True,
            }
        return {
            "documents": len(document_store.list_documents()),
            "chunks": chunk_store.stats(),
            "vector": vector,
            "embedding_model": settings.EMBEDDING_MODEL,
            "collection": collection,
        }
