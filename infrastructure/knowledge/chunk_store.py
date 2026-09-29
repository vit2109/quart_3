"""Манифест фрагментов (chunks) для управления и keyword-поиска."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings
from core.exceptions import NotFoundError

logger = logging.getLogger(__name__)
_lock = Lock()


def _manifest_path() -> Path:
    return Path(settings.KNOWLEDGE_DIR) / "chunks_manifest.json"


def _rebuild_from_chroma(collection_name: str = "quart_knowledge") -> List[Dict[str, Any]]:
    """Восстановить manifest из ChromaDB порциями (без загрузки всего в RAM)."""
    try:
        from infrastructure.ai.rag import chroma_client

        collection = chroma_client.get_collection(collection_name)
        total = collection.count()
        if total == 0:
            return []

        page_size = 200
        now = datetime.now(timezone.utc).isoformat()
        items: List[Dict[str, Any]] = []
        offset = 0
        while offset < total:
            raw = collection.get(
                include=["documents", "metadatas"],
                limit=page_size,
                offset=offset,
            )
            ids = raw.get("ids") or []
            if not ids:
                break
            docs = raw.get("documents") or []
            metas = raw.get("metadatas") or []
            for chunk_id, text, meta in zip(ids, docs, metas):
                meta = dict(meta or {})
                text = text or ""
                items.append(
                    {
                        "id": chunk_id,
                        "document_id": meta.get("document_id"),
                        "document_title": meta.get("document_title"),
                        "text": text,
                        "metadata": meta,
                        "char_count": len(text),
                        "word_count": len(text.split()),
                        "collection": meta.get("collection", collection_name),
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            offset += len(ids)
        return items
    except Exception as exc:
        logger.warning("Chroma manifest rebuild failed: %s", exc)
        return []


def _recover_manifest(path: Path) -> List[Dict[str, Any]]:
    """Бэкап повреждённого файла и попытка восстановления."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"chunks_manifest.corrupt.{stamp}.json")
    try:
        shutil.copy2(path, backup)
        logger.warning("Corrupted chunks_manifest backed up to %s", backup.name)
    except OSError as exc:
        logger.warning("Could not backup corrupted manifest: %s", exc)

    items = _rebuild_from_chroma()
    if items:
        _write(items)
        logger.info("Rebuilt chunks_manifest from Chroma (%s chunks)", len(items))
        return items

    logger.warning("Resetting chunks_manifest to empty list")
    _write([])
    return []


def _read() -> List[Dict[str, Any]]:
    path = _manifest_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except UnicodeDecodeError as exc:
        logger.error("chunks_manifest.json corrupted (UTF-8 at byte %s): %s", exc.start, exc)
        return _recover_manifest(path)
    except json.JSONDecodeError as exc:
        logger.error("chunks_manifest.json invalid JSON: %s", exc)
        return _recover_manifest(path)
    except OSError as exc:
        logger.error("chunks_manifest.json read error: %s", exc)
        return []


def _write(items: List[Dict[str, Any]]) -> None:
    Path(settings.KNOWLEDGE_DIR).mkdir(parents=True, exist_ok=True)
    path = _manifest_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def repair_manifest(collection_name: str = "quart_knowledge") -> Dict[str, Any]:
    """Принудительное восстановление manifest (API / admin)."""
    with _lock:
        path = _manifest_path()
        if path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            backup = path.with_name(f"chunks_manifest.manual.{stamp}.json")
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        items = _rebuild_from_chroma(collection_name)
        _write(items)
        return {"chunks_total": len(items), "collection": collection_name}


def all_chunks(collection: Optional[str] = None) -> List[Dict[str, Any]]:
    """Все фрагменты из manifest (для восстановления Chroma)."""
    with _lock:
        items = _read()
    if collection:
        items = [c for c in items if c.get("collection") == collection]
    return items


def list_chunks(
    *,
    document_id: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Список фрагментов с фильтрацией и простым keyword-поиском."""
    with _lock:
        items = _read()

    if document_id:
        items = [c for c in items if c.get("document_id") == document_id]

    if query:
        q = query.lower().strip()
        q_tokens = [t for t in re.findall(r"[\w\d_]+", q, re.UNICODE) if len(t) > 1]
        scored = []
        for c in items:
            text = (c.get("text") or "").lower()
            title = (c.get("document_title") or "").lower()
            meta = c.get("metadata") or {}
            section = str(meta.get("section_title") or "").lower()
            keywords = " ".join(str(k) for k in (meta.get("keywords") or []))
            numbers = " ".join(str(n) for n in (meta.get("numbers") or []))
            haystack = " ".join([text, title, section, keywords, numbers])
            score = haystack.count(q) * 2 + title.count(q) * 3 + section.count(q) * 2
            for tok in q_tokens:
                if tok in haystack:
                    score += 1
            if q in haystack or score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        items = [c for _, c in scored]

    total = len(items)
    page = items[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "items": page}


def get_chunk(chunk_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for item in _read():
            if item.get("id") == chunk_id:
                return item
    return None


def add_chunks(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    with _lock:
        items = _read()
        items.extend(records)
        _write(items)
    return records


def update_chunk(chunk_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with _lock:
        items = _read()
        idx = next((i for i, it in enumerate(items) if it.get("id") == chunk_id), None)
        if idx is None:
            raise NotFoundError(f"Chunk {chunk_id} not found")
        record = dict(items[idx])
        record["text"] = text
        record["char_count"] = len(text)
        record["word_count"] = len(text.split())
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        if metadata:
            record["metadata"] = {**(record.get("metadata") or {}), **metadata}
        items[idx] = record
        _write(items)
        return record


def delete_chunk(chunk_id: str) -> Dict[str, Any]:
    with _lock:
        items = _read()
        idx = next((i for i, it in enumerate(items) if it.get("id") == chunk_id), None)
        if idx is None:
            raise NotFoundError(f"Chunk {chunk_id} not found")
        record = items.pop(idx)
        _write(items)
        return record


def delete_chunks(chunk_ids: List[str]) -> int:
    """Атомарно удалить набор фрагментов по идентификаторам."""
    ids = set(chunk_ids)
    if not ids:
        return 0
    with _lock:
        items = _read()
        remaining = [item for item in items if item.get("id") not in ids]
        removed = len(items) - len(remaining)
        if removed:
            _write(remaining)
        return removed


def delete_by_document(document_id: str) -> List[str]:
    """Удалить все фрагменты документа; вернуть список id."""
    with _lock:
        items = _read()
        removed = [c["id"] for c in items if c.get("document_id") == document_id]
        items = [c for c in items if c.get("document_id") != document_id]
        _write(items)
        return removed


def stats() -> Dict[str, Any]:
    with _lock:
        items = _read()
    docs = {c.get("document_id") for c in items}
    return {
        "chunks_total": len(items),
        "documents_indexed": len(docs),
        "avg_chunk_chars": round(
            sum(c.get("char_count", 0) for c in items) / max(len(items), 1), 1
        ),
    }
