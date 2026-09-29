"""Тесты job_store."""

from infrastructure.storage import job_store


def test_create_and_get_run(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path))
    run = job_store.create_run("report_generate", {"dataset_id": 1})
    assert run["id"]
    assert run["status"] == "pending"
    fetched = job_store.get_run(run["id"])
    assert fetched["job_type"] == "report_generate"


def test_create_schedule(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path))
    schedule = job_store.create_schedule(
        "Daily report",
        "report_generate",
        {"dataset_id": 1},
        "0 8 * * *",
    )
    assert schedule["id"] >= 1
    items = job_store.list_schedules()
    assert any(s["id"] == schedule["id"] for s in items)


def test_delete_schedule(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "USER_DATA_DIR", str(tmp_path))
    schedule = job_store.create_schedule("x", "report_generate", {}, "0 9 * * *")
    assert job_store.delete_schedule(schedule["id"]) is True
    assert job_store.list_schedules() == []
