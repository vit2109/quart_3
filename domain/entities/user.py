"""Доменная модель пользователя и роли доступа."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from enum import Enum


class UserRole(str, Enum):
    """Роли пользователей системы аналитики."""

    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class User(BaseModel):
    """Пользователь с email, паролем и ролью для RBAC."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    email: EmailStr
    username: str
    hashed_password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.VIEWER
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

