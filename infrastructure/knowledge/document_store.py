"""Хранилище исходных документов базы знаний (файлы + manifest)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings
from core.exceptions import DuplicateError, NotFoundError

_lock = Lock()
COLLECTION_DEFAULT = "quart_knowledge"


def _root() -> Path:
    root = Path(settings.KNOWLEDGE_DIR) / "documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path() -> Path:
    return Path(settings.KNOWLEDGE_DIR) / "documents_manifest.json"


def _read_manifest() -> List[Dict[str, Any]]:
    path = _manifest_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_manifest(items: List[Dict[str, Any]]) -> None:
    Path(settings.KNOWLEDGE_DIR).mkdir(parents=True, exist_ok=True)
    _manifest_path().write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def list_documents() -> List[Dict[str, Any]]:
    with _lock:
        return list(_read_manifest())


def list_by_dataset_id(dataset_id: int) -> List[Dict[str, Any]]:
    """Документы базы знаний, импортированные из набора данных."""
    ds_id = int(dataset_id)
    with _lock:
        return [
            item
            for item in _read_manifest()
            if int((item.get("extra") or {}).get("dataset_id") or 0) == ds_id
        ]


def get_document(document_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for item in _read_manifest():
            if item.get("id") == document_id:
                return item
    return None


def find_by_content_hash(content_hash: str) -> Optional[Dict[str, Any]]:
    """Найти документ по SHA-256 содержимого."""
    with _lock:
        for item in _read_manifest():
            if item.get("content_hash") == content_hash:
                return item
    return None


def get_document_path(document_id: str) -> Optional[Path]:
    item = get_document(document_id)
    if not item:
        return None
    path = _root() / item.get("stored_as", "")
    return path if path.exists() else None


def save_document(
    *,
    original_filename: str,
    content: bytes,
    title: Optional[str] = None,
    description: Optional[str] = None,
    source_type: str = "text",
    collection: str = COLLECTION_DEFAULT,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Сохранить документ; при совпадении хеша — DuplicateError."""
    digest = _content_hash(content)
    with _lock:
        items = _read_manifest()
        for idx, existing in enumerate(items):
            if existing.get("content_hash") != digest:
                continue
            if existing.get("chunk_count", 0) > 0:
                raise DuplicateError(
                    "Документ с таким содержимым уже проиндексирован",
                    details={
                        "existing_id": existing.get("id"),
                        "title": existing.get("title"),
                        "chunk_count": existing.get("chunk_count", 0),
                    },
                )
            record = dict(existing)
            if title:
                record["title"] = title
            if description is not None:
                record["description"] = description or ""
            if extra_meta:
                record["extra"] = {**(record.get("extra") or {}), **extra_meta}
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            items[idx] = record
            _write_manifest(items)
            return record

        next_id = f"doc_{uuid.uuid4().hex[:10]}"
        safe_name = original_filename.replace(" ", "_")
        stored = f"{next_id}_{safe_name}"
        (_root() / stored).write_bytes(content)
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": next_id,
            "title": title or Path(original_filename).stem,
            "description": description or "",
            "filename": original_filename,
            "stored_as": stored,
            "size": len(content),
            "content_hash": digest,
            "source_type": source_type,
            "collection": collection,
            "chunk_count": 0,
            "created_at": now,
            "updated_at": now,
            "extra": extra_meta or {},
        }
        items.append(record)
        _write_manifest(items)
        return record


def update_document(document_id: str, **fields: Any) -> Dict[str, Any]:
    with _lock:
        items = _read_manifest()
        idx = next((i for i, it in enumerate(items) if it.get("id") == document_id), None)
        if idx is None:
            raise NotFoundError(f"Document {document_id} not found")
        record = dict(items[idx])
        for key in ("title", "description", "chunk_count", "extra"):
            if key in fields and fields[key] is not None:
                record[key] = fields[key]
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        items[idx] = record
        _write_manifest(items)
        return record


def delete_document(document_id: str) -> Dict[str, Any]:
    with _lock:
        items = _read_manifest()
        idx = next((i for i, it in enumerate(items) if it.get("id") == document_id), None)
        if idx is None:
            raise NotFoundError(f"Document {document_id} not found")
        record = items.pop(idx)
        path = _root() / record.get("stored_as", "")
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        _write_manifest(items)
        return record
