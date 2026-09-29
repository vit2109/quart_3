"""Тесты PDF-экспорта отчётов."""

from application.use_cases.reports.pdf_export import report_to_pdf
from pypdf import PdfReader
from io import BytesIO


def test_report_to_pdf_minimal():
    report = {
        "id": 1,
        "name": "Test Report",
        "dataset_id": 2,
        "report_type": "summary",
        "created_at": "2026-01-01",
        "analysis_text": "Line one\nLine two",
        "tables": [
            {
                "title": "Metrics",
                "columns": ["region", "value"],
                "rows": [
                    {"region": "North", "value": 100},
                    {"region": "South", "value": 200},
                ],
            }
        ],
        "insights": ["Insight A", "Insight B"],
    }
    pdf = report_to_pdf(report)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"


def test_report_to_pdf_supports_cyrillic_and_charts():
    report = {
        "id": 2,
        "name": "Отчёт по регионам",
        "dataset_id": 7,
        "report_type": "summary",
        "created_at": "2026-09-29",
        "tables": [
            {
                "title": "Показатели",
                "columns": ["Регион", "Значение"],
                "rows": [
                    {"Регион": "Москва", "Значение": 120},
                    {"Регион": "Казань", "Значение": 85},
                ],
            }
        ],
        "charts": [
            {
                "title": "Значения по регионам",
                "type": "bar",
                "labels": ["Москва", "Казань"],
                "datasets": [{"label": "Значение", "data": [120, 85]}],
            }
        ],
        "insights": ["Максимальное значение у Москвы"],
    }

    pdf = report_to_pdf(report)
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Отчёт по регионам" in text
    assert "Москва" in text
    assert "Значения по регионам" in text
    assert len(pdf) > 20_000
