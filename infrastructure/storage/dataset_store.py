"""Файловое хранилище наборов данных.

Манифест ``uploads/manifest.json`` хранит метаданные; сами файлы — в ``uploads/``.
Дубликаты определяются по SHA-256 содержимого файла.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings
from core.exceptions import DuplicateError, NotFoundError

_lock = Lock()


def _upload_root() -> Path:
    """Корневая директория загрузок; создаётся при отсутствии."""
    root = Path(settings.UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path() -> Path:
    """Путь к JSON-манифесту наборов данных."""
    return _upload_root() / "manifest.json"


def _read_manifest() -> List[Dict[str, Any]]:
    """Прочитать манифест; при ошибке или отсутствии — пустой список."""
    path = _manifest_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_manifest(items: List[Dict[str, Any]]) -> None:
    """Сохранить манифест на диск."""
    path = _manifest_path()
    path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_filename(name: str) -> str:
    """Очистить имя файла от небезопасных символов."""
    cleaned = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._")
    return cleaned or "dataset"


def _content_hash(content: bytes) -> str:
    """SHA-256 хеш содержимого файла для проверки дубликатов."""
    return hashlib.sha256(content).hexdigest()


def _ensure_content_hashes(items: List[Dict[str, Any]]) -> bool:
    """Дописать content_hash в старые записи манифеста; True если были изменения."""
    changed = False
    root = _upload_root()
    for item in items:
        if item.get("content_hash"):
            continue
        path = root / item.get("stored_as", "")
        if path.exists():
            item["content_hash"] = _content_hash(path.read_bytes())
            changed = True
    return changed


def find_by_content_hash(content_hash: str) -> Optional[Dict[str, Any]]:
    """Найти набор с таким же хешем содержимого."""
    with _lock:
        items = _read_manifest()
        if _ensure_content_hashes(items):
            _write_manifest(items)
        for item in items:
            if item.get("content_hash") == content_hash:
                return item
    return None


def list_datasets() -> List[Dict[str, Any]]:
    """Список всех наборов данных из манифеста."""
    with _lock:
        return list(_read_manifest())


def get_dataset(dataset_id: int) -> Optional[Dict[str, Any]]:
    """Получить запись набора по ID."""
    with _lock:
        for item in _read_manifest():
            if item.get("id") == dataset_id:
                return item
    return None


def get_dataset_path(dataset_id: int) -> Optional[Path]:
    """Абсолютный путь к файлу набора или None."""
    item = get_dataset(dataset_id)
    if not item:
        return None
    path = _upload_root() / item["stored_as"]
    return path if path.exists() else None


def get_selected_sheet_for_path(path: Path) -> Optional[str]:
    """Найти выбранный лист Excel по физическому пути файла."""
    try:
        stored_as = path.resolve().name
    except OSError:
        stored_as = path.name
    with _lock:
        for item in _read_manifest():
            if item.get("stored_as") == stored_as:
                return item.get("selected_sheet")
    return None


def save_dataset(
    *,
    original_filename: str,
    content: bytes,
    name: Optional[str] = None,
    description: Optional[str] = None,
    content_type: Optional[str] = None,
    allow_duplicate: bool = False,
    sheet_names: Optional[List[str]] = None,
    selected_sheet: Optional[str] = None,
) -> Dict[str, Any]:
    """Сохранить новый набор данных.

    Raises:
        ValueError: превышен лимит размера.
        DuplicateError: файл с таким содержимым уже загружен (409).
    """
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise ValueError(
            f"File exceeds max size of {settings.MAX_UPLOAD_SIZE} bytes"
        )

    digest = _content_hash(content)

    with _lock:
        items = _read_manifest()
        if _ensure_content_hashes(items):
            _write_manifest(items)
        if not allow_duplicate:
            for existing in items:
                if existing.get("content_hash") == digest:
                    raise DuplicateError(
                        "Dataset with identical content already exists",
                        details={
                            "existing_id": existing.get("id"),
                            "existing_name": existing.get("name"),
                            "filename": existing.get("filename"),
                        },
                    )

        next_id = max((int(i.get("id", 0)) for i in items), default=0) + 1

        original = original_filename or "dataset.bin"
        safe = _safe_filename(original)
        stored_name = f"{next_id}_{uuid.uuid4().hex[:8]}_{safe}"
        file_path = _upload_root() / stored_name
        file_path.write_bytes(content)

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": next_id,
            "name": name or Path(original).stem,
            "description": description or "",
            "filename": original,
            "stored_as": stored_name,
            "size": len(content),
            "content_type": content_type,
            "content_hash": digest,
            "created_at": now,
            "updated_at": now,
        }
        if sheet_names:
            record["sheet_names"] = list(sheet_names)
            record["selected_sheet"] = selected_sheet or sheet_names[0]
        items.append(record)
        _write_manifest(items)
        return record


def patch_dataset_meta(dataset_id: int, **extra: Any) -> Dict[str, Any]:
    """Дополнительные поля манифеста (join_meta, source_type и т.д.)."""
    with _lock:
        items = _read_manifest()
        idx = next((i for i, it in enumerate(items) if it.get("id") == dataset_id), None)
        if idx is None:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        record = {**items[idx], **extra}
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        items[idx] = record
        _write_manifest(items)
        return record


def update_dataset(
    dataset_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    content: Optional[bytes] = None,
    original_filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Обновить метаданные и/или заменить файл набора.

    При замене файла проверяется дубликат по хешу (кроме текущей записи).
    """
    with _lock:
        items = _read_manifest()
        idx = next((i for i, it in enumerate(items) if it.get("id") == dataset_id), None)
        if idx is None:
            raise NotFoundError(f"Dataset {dataset_id} not found")

        record = dict(items[idx])
        if name is not None:
            record["name"] = name.strip() or record.get("name")
        if description is not None:
            record["description"] = description

        if content is not None:
            if len(content) > settings.MAX_UPLOAD_SIZE:
                raise ValueError(
                    f"File exceeds max size of {settings.MAX_UPLOAD_SIZE} bytes"
                )
            digest = _content_hash(content)
            for existing in items:
                if (
                    existing.get("id") != dataset_id
                    and existing.get("content_hash") == digest
                ):
                    raise DuplicateError(
                        "Another dataset with identical content already exists",
                        details={
                            "existing_id": existing.get("id"),
                            "existing_name": existing.get("name"),
                        },
                    )

            old_path = _upload_root() / record["stored_as"]
            original = original_filename or record.get("filename") or "dataset.bin"
            safe = _safe_filename(original)
            stored_name = f"{dataset_id}_{uuid.uuid4().hex[:8]}_{safe}"
            new_path = _upload_root() / stored_name
            new_path.write_bytes(content)

            if old_path.exists() and old_path != new_path:
                try:
                    old_path.unlink()
                except OSError:
                    pass

            record["stored_as"] = stored_name
            record["filename"] = original
            record["size"] = len(content)
            record["content_type"] = content_type or record.get("content_type")
            record["content_hash"] = digest

        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        items[idx] = record
        _write_manifest(items)
        if content is not None:
            from infrastructure.storage.schema_reader import invalidate_dataframe_cache

            invalidate_dataframe_cache(new_path)
        return record


def delete_dataset(dataset_id: int) -> Dict[str, Any]:
    """Удалить набор: запись из манифеста и файл с диска."""
    with _lock:
        items = _read_manifest()
        idx = next((i for i, it in enumerate(items) if it.get("id") == dataset_id), None)
        if idx is None:
            raise NotFoundError(f"Dataset {dataset_id} not found")

        record = items.pop(idx)
        file_path = _upload_root() / record.get("stored_as", "")
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
            from infrastructure.storage.schema_reader import invalidate_dataframe_cache

            invalidate_dataframe_cache(file_path)
            from infrastructure.storage import column_values_cache

            column_values_cache.invalidate_dataset(dataset_id)

        _write_manifest(items)
        return record
