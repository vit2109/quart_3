"""Файловое хранилище сгенерированных отчётов (manifest.json + JSON-записи)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings

_lock = Lock()


def _report_root() -> Path:
    """Корневая директория отчётов."""
    root = Path(settings.REPORT_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path() -> Path:
    """Путь к манифесту отчётов."""
    return _report_root() / "manifest.json"


def _read_manifest() -> List[Dict[str, Any]]:
    """Прочитать манифест отчётов."""
    path = _manifest_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_manifest(items: List[Dict[str, Any]]) -> None:
    """Сохранить манифест отчётов."""
    _manifest_path().write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_reports() -> List[Dict[str, Any]]:
    """Список отчётов без тяжёлых полей (tables, charts)."""
    with _lock:
        items = _read_manifest()
        return [
            {
                "id": i["id"],
                "name": i.get("name"),
                "dataset_id": i.get("dataset_id"),
                "report_type": i.get("report_type"),
                "created_at": i.get("created_at"),
                "tables_count": len(i.get("tables") or []),
            }
            for i in items
        ]


def get_report(report_id: int) -> Optional[Dict[str, Any]]:
    """Полный отчёт по ID (таблицы, графики, insights)."""
    with _lock:
        for item in _read_manifest():
            if item.get("id") == report_id:
                return item
    return None


def save_report(record: Dict[str, Any]) -> Dict[str, Any]:
    """Сохранить новый отчёт; присваивает id и created_at."""
    with _lock:
        items = _read_manifest()
        next_id = max((int(i.get("id", 0)) for i in items), default=0) + 1
        record = {
            **record,
            "id": next_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        items.append(record)
        _write_manifest(items)
        return record


def delete_report(report_id: int) -> bool:
    """Удалить отчёт по ID. Возвращает False, если не найден."""
    with _lock:
        items = _read_manifest()
        kept = [i for i in items if int(i.get("id", 0)) != int(report_id)]
        if len(kept) == len(items):
            return False
        _write_manifest(kept)
        return True


def clear_reports() -> int:
    """Удалить все отчёты. Возвращает число удалённых записей."""
    with _lock:
        items = _read_manifest()
        count = len(items)
        if count:
            _write_manifest([])
        return count
