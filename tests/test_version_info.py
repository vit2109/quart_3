"""Тесты метаданных сборки."""

from core.version_info import build_health_payload, get_git_commit


def test_build_health_payload_includes_commit_when_available(monkeypatch):
    monkeypatch.setattr("core.version_info.get_git_commit", lambda short=True: "abc1234")
    data = build_health_payload(
        app_version="0.2.0",
        environment="development",
        debug=True,
        postgresql=False,
    )
    assert data["git_commit"] == "abc1234"
    assert data["version"] == "0.2.0"


def test_get_git_commit_returns_string_or_none():
    commit = get_git_commit()
    assert commit is None or isinstance(commit, str)
