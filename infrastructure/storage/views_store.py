"""Сохранённые представления (saved views) per dataset."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings

_lock = Lock()


def _views_root() -> Path:
    root = Path(settings.USER_DATA_DIR) / "views"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path(dataset_id: int) -> Path:
    return _views_root() / f"dataset_{dataset_id}.json"


def _read_manifest(dataset_id: int) -> List[Dict[str, Any]]:
    path = _manifest_path(dataset_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_manifest(dataset_id: int, items: List[Dict[str, Any]]) -> None:
    _manifest_path(dataset_id).write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_views(dataset_id: int) -> List[Dict[str, Any]]:
    """Список представлений для набора (pinned первыми)."""
    with _lock:
        items = _read_manifest(dataset_id)
        return sorted(
            [
                {
                    "id": i["id"],
                    "name": i.get("name"),
                    "pinned": bool(i.get("pinned")),
                    "mode": i.get("mode"),
                    "created_at": i.get("created_at"),
                    "updated_at": i.get("updated_at"),
                }
                for i in items
            ],
            key=lambda x: (not x.get("pinned"), x.get("name") or ""),
        )


def get_view(dataset_id: int, view_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        for item in _read_manifest(dataset_id):
            if item.get("id") == view_id:
                return item
    return None


def save_view(dataset_id: int, payload: Dict[str, Any], view_id: Optional[int] = None) -> Dict[str, Any]:
    """Создать или обновить представление."""
    with _lock:
        items = _read_manifest(dataset_id)
        now = datetime.now(timezone.utc).isoformat()
        if view_id is not None:
            for i, item in enumerate(items):
                if item.get("id") == view_id:
                    record = {
                        **item,
                        **payload,
                        "id": view_id,
                        "dataset_id": dataset_id,
                        "updated_at": now,
                    }
                    items[i] = record
                    _write_manifest(dataset_id, items)
                    return record
            raise ValueError(f"View {view_id} not found")

        next_id = max((int(i.get("id", 0)) for i in items), default=0) + 1
        record = {
            **payload,
            "id": next_id,
            "dataset_id": dataset_id,
            "created_at": now,
            "updated_at": now,
        }
        items.append(record)
        _write_manifest(dataset_id, items)
        return record


def delete_view(dataset_id: int, view_id: int) -> bool:
    with _lock:
        items = _read_manifest(dataset_id)
        new_items = [i for i in items if i.get("id") != view_id]
        if len(new_items) == len(items):
            return False
        _write_manifest(dataset_id, new_items)
        return True
