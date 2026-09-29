"""Тест генерации отчёта через async API сервиса."""

from __future__ import annotations

import pytest

from application.use_cases.reports.report_service import ReportService
from core.config import settings
from infrastructure.storage import dataset_store


@pytest.fixture
def dataset_id(sample_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    record = dataset_store.save_dataset(
        original_filename="sample.csv",
        content=sample_csv.read_bytes(),
        name="Sample Report",
    )
    return record["id"]


@pytest.mark.asyncio
async def test_report_generate_async(dataset_id):
    record = await ReportService().generate(
        dataset_id,
        "summary",
        group_by=[],
        metrics=[],
        top_n=10,
        chart_types=["bar"],
    )
    assert record["id"]
    assert record["dataset_id"] == dataset_id
    assert record.get("tables")


@pytest.mark.asyncio
async def test_report_with_filters(dataset_id):
    record = await ReportService().generate(
        dataset_id,
        "summary",
        group_by=["region"],
        metrics=["amount"],
        filters=[{"column": "region", "op": "eq", "value": "East"}],
    )
    assert record["filtered_rows"] == 2
    assert record["source_rows"] == 4
    overview = next(t for t in record["tables"] if t["title"] == "Обзор")
    by_key = {r["Показатель"]: r["Значение"] for r in overview["rows"]}
    assert by_key["Строк (после фильтров)"] == 2
    assert by_key["Строк (всего)"] == 4
    assert "region eq East" in str(by_key["Фильтры"])


@pytest.mark.asyncio
async def test_report_numeric_filter(dataset_id):
    record = await ReportService().generate(
        dataset_id,
        "summary",
        filters=[{"column": "amount", "op": "gte", "value": 200}],
    )
    assert record["filtered_rows"] == 2
    stats_table = next(t for t in record["tables"] if t["title"] == "Статистика по колонкам")
    amount_row = next(r for r in stats_table["rows"] if r["Колонка"] == "amount")
    assert amount_row["Мин"] == 200


@pytest.mark.asyncio
async def test_report_between_filter(dataset_id):
    record = await ReportService().generate(
        dataset_id,
        "summary",
        filters=[{"column": "amount", "op": "between", "value": [100, 200]}],
    )
    assert record["filtered_rows"] == 3
    overview = next(t for t in record["tables"] if t["title"] == "Обзор")
    by_key = {r["Показатель"]: r["Значение"] for r in overview["rows"]}
    assert "между 100 и 200" in str(by_key["Фильтры"])
