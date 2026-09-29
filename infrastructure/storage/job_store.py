"""Файловое хранилище фоновых задач (fallback без PostgreSQL)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings

_lock = Lock()


def _root() -> Path:
    root = Path(settings.USER_DATA_DIR) / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _runs_path() -> Path:
    return _root() / "runs.json"


def _schedules_path() -> Path:
    return _root() / "schedules.json"


def _read_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_json(path: Path, items: List[Dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def create_run(job_type: str, payload: Dict[str, Any], scheduled_job_id: Optional[int] = None) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": run_id,
        "scheduled_job_id": scheduled_job_id,
        "job_type": job_type,
        "status": "pending",
        "payload": payload,
        "result": None,
        "error": None,
        "created_at": now,
        "finished_at": None,
    }
    with _lock:
        items = _read_json(_runs_path())
        items.insert(0, record)
        _write_json(_runs_path(), items[:500])
    return record


def update_run(run_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    with _lock:
        items = _read_json(_runs_path())
        for idx, item in enumerate(items):
            if item.get("id") == run_id:
                items[idx] = {**item, **fields}
                _write_json(_runs_path(), items)
                return items[idx]
    return None


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for item in _read_json(_runs_path()):
            if item.get("id") == run_id:
                return item
    return None


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock:
        return _read_json(_runs_path())[:limit]


def create_schedule(
    name: str,
    job_type: str,
    payload: Dict[str, Any],
    cron: str,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    with _lock:
        items = _read_json(_schedules_path())
        next_id = max((int(i.get("id", 0)) for i in items), default=0) + 1
        record = {
            "id": next_id,
            "name": name,
            "job_type": job_type,
            "payload": payload,
            "cron": cron,
            "webhook_url": (webhook_url or "").strip() or None,
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_run_at": None,
        }
        items.append(record)
        _write_json(_schedules_path(), items)
        return record


def list_schedules() -> List[Dict[str, Any]]:
    with _lock:
        return _read_json(_schedules_path())


def get_schedule(schedule_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        for item in _read_json(_schedules_path()):
            if int(item.get("id", 0)) == schedule_id:
                return item
    return None


def update_schedule(schedule_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    with _lock:
        items = _read_json(_schedules_path())
        for idx, item in enumerate(items):
            if int(item.get("id", 0)) == schedule_id:
                items[idx] = {**item, **fields}
                _write_json(_schedules_path(), items)
                return items[idx]
    return None


def delete_schedule(schedule_id: int) -> bool:
    with _lock:
        items = _read_json(_schedules_path())
        new_items = [i for i in items if int(i.get("id", 0)) != schedule_id]
        if len(new_items) == len(items):
            return False
        _write_json(_schedules_path(), new_items)
        return True
