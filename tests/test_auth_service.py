"""Тесты auth (user_store + AuthService)."""

from __future__ import annotations

import pytest

from application.use_cases.auth.auth_service import AuthService
from core.config import settings
from core.exceptions import AuthenticationError, ValidationError
from domain.entities.user import User, UserRole
from infrastructure.persistence.file_user_repository import FileUserRepository
from infrastructure.storage import user_store


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path))
    user_store.ensure_default_users()
    return AuthService(FileUserRepository())


@pytest.mark.asyncio
async def test_login_default_analyst(auth_env):
    user, access, refresh = await auth_env.authenticate(
        "analyst@quart.io", "analyst123"
    )
    assert user.role == UserRole.ANALYST
    assert access
    assert refresh


@pytest.mark.asyncio
async def test_login_invalid_password(auth_env):
    with pytest.raises(AuthenticationError):
        await auth_env.authenticate("analyst@quart.io", "wrong")


@pytest.mark.asyncio
async def test_register_new_user(auth_env, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path / "reg"))
    svc = AuthService(FileUserRepository())
    user = await svc.register(
        "new@example.com", "newbie", "secret12", full_name="New User"
    )
    assert user.email == "new@example.com"
    assert user.role == UserRole.ADMIN

    user2 = await svc.register("viewer@example.com", "viewer", "secret12")
    assert user2.role == UserRole.VIEWER


@pytest.mark.asyncio
async def test_register_duplicate_email(auth_env):
    with pytest.raises(ValidationError):
        await auth_env.register("analyst@quart.io", "dup", "secret12")
