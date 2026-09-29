"""Интеграционные тесты HTTP API (FastAPI TestClient)."""

from __future__ import annotations


def test_health_endpoint(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "postgresql" in data


def test_api_info(api_client):
    resp = api_client.get("/api")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["version"] == "1.0.0"


def test_ui_root_serves_html(api_client):
    resp = api_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_auth_login_success(api_client, tmp_path, monkeypatch):
    from core.config import settings
    from infrastructure.storage import user_store

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path / "login_users"))
    user_store.ensure_default_users()

    resp = api_client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@quart.io", "password": "analyst123"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "success"
    assert payload["data"]["access_token"]
    assert payload["data"]["user"]["role"] == "analyst"


def test_auth_login_invalid_password(api_client, tmp_path, monkeypatch):
    from core.config import settings
    from infrastructure.storage import user_store

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path / "bad_login"))
    user_store.ensure_default_users()

    resp = api_client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@quart.io", "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_datasets_list_requires_auth_or_debug(api_client):
    resp = api_client.get("/api/v1/datasets/")
    # В DEBUG без токена — demo analyst (200); иначе 401
    assert resp.status_code in (200, 401)


def test_ai_models_list_endpoint(api_client, auth_headers):
    resp = api_client.get("/api/v1/analysis/ai/models", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


def test_ai_health_with_token(api_client, auth_headers):
    resp = api_client.get("/api/v1/analysis/ai/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]
    assert "backend" in data
    assert "sql_model" in data
