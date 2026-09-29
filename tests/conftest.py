"""Fixtures for pytest."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TESTS_DATA = Path(__file__).parent / "data"


@pytest.fixture
def sample_csv() -> Path:
    path = TESTS_DATA / "sample.csv"
    assert path.exists()
    return path


@pytest.fixture(scope="module")
def api_client():
    """HTTP-клиент для интеграционных тестов FastAPI (с lifespan)."""
    from main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers(api_client, tmp_path, monkeypatch):
    """JWT access token аналитика для защищённых эндпоинтов."""
    from core.config import settings
    from infrastructure.storage import user_store

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path / "users"))
    user_store.ensure_default_users()

    resp = api_client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@quart.io", "password": "analyst123"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}

