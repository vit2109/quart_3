"""Файловое хранилище пользователей (JSON-манифест)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from core.config import settings
from core.exceptions import DuplicateError, NotFoundError
from core.security import SecurityService
from domain.entities.user import User, UserRole

_lock = Lock()


def _users_root() -> Path:
    root = Path(settings.USER_DATA_DIR) / "users"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path() -> Path:
    return _users_root() / "manifest.json"


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
    path = _manifest_path()
    path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _next_id(items: List[Dict[str, Any]]) -> int:
    if not items:
        return 1
    return max(int(i.get("id", 0)) for i in items) + 1


def _to_user(record: Dict[str, Any]) -> User:
    role_value = record.get("role", UserRole.VIEWER.value)
    try:
        role = UserRole(role_value)
    except ValueError:
        role = UserRole.VIEWER
    return User(
        id=int(record["id"]),
        email=record["email"],
        username=record.get("username") or record["email"],
        hashed_password=record["hashed_password"],
        full_name=record.get("full_name"),
        role=role,
        is_active=bool(record.get("is_active", True)),
        created_at=record.get("created_at") or datetime.now(timezone.utc),
        updated_at=record.get("updated_at"),
        last_login=record.get("last_login"),
    )


def _user_to_dict(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "hashed_password": user.hashed_password,
        "full_name": user.full_name,
        "role": user.role.value,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def ensure_default_users() -> None:
    """Создать учётные записи по умолчанию, если манифест пуст."""
    with _lock:
        items = _read_manifest()
        if items:
            return
        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            {
                "id": 1,
                "email": "admin@quart.io",
                "username": "admin",
                "hashed_password": SecurityService.get_password_hash("admin123"),
                "full_name": "Administrator",
                "role": UserRole.ADMIN.value,
                "is_active": True,
                "created_at": now,
                "updated_at": None,
                "last_login": None,
            },
            {
                "id": 2,
                "email": "analyst@quart.io",
                "username": "analyst",
                "hashed_password": SecurityService.get_password_hash("analyst123"),
                "full_name": "Analyst",
                "role": UserRole.ANALYST.value,
                "is_active": True,
                "created_at": now,
                "updated_at": None,
                "last_login": None,
            },
        ]
        _write_manifest(defaults)


def get_by_email(email: str) -> Optional[User]:
    key = email.strip().lower()
    with _lock:
        for record in _read_manifest():
            if str(record.get("email", "")).lower() == key:
                return _to_user(record)
    return None


def get_by_id(user_id: int) -> Optional[User]:
    with _lock:
        for record in _read_manifest():
            if int(record.get("id", 0)) == user_id:
                return _to_user(record)
    return None


def create_user(user: User) -> User:
    with _lock:
        items = _read_manifest()
        key = user.email.strip().lower()
        if any(str(i.get("email", "")).lower() == key for i in items):
            raise DuplicateError("Email already registered")
        user_id = _next_id(items)
        now = datetime.now(timezone.utc)
        user.id = user_id
        user.created_at = now
        record = _user_to_dict(user)
        items.append(record)
        _write_manifest(items)
        return _to_user(record)


def update_user(user: User) -> User:
    if user.id is None:
        raise NotFoundError("User id is required")
    with _lock:
        items = _read_manifest()
        for idx, record in enumerate(items):
            if int(record.get("id", 0)) == user.id:
                user.updated_at = datetime.now(timezone.utc)
                items[idx] = _user_to_dict(user)
                _write_manifest(items)
                return _to_user(items[idx])
    raise NotFoundError(f"User {user.id} not found")


def list_users() -> List[User]:
    with _lock:
        return [_to_user(r) for r in _read_manifest()]
