"""Тесты JWT и хеширования паролей."""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.config import settings
from core.security import SecurityService
from domain.entities.user import UserRole


def test_password_hash_roundtrip():
    hashed = SecurityService.get_password_hash("secret123")
    assert SecurityService.verify_password("secret123", hashed)
    assert not SecurityService.verify_password("wrong", hashed)


def test_access_token_decode():
    token = SecurityService.create_access_token(
        {"sub": "user@example.com", "role": UserRole.ANALYST.value},
        expires_delta=timedelta(minutes=5),
    )
    payload = SecurityService.decode_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["role"] == UserRole.ANALYST.value


def test_invalid_token_returns_empty():
    assert SecurityService.decode_token("not-a-jwt") == {}


def test_refresh_token_has_type():
    token = SecurityService.create_refresh_token({"sub": "u@x.com"})
    payload = SecurityService.decode_token(token)
    assert payload.get("type") == "refresh"
    assert payload["sub"] == "u@x.com"
