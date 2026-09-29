"""Тесты PDF-экспорта отчётов."""

from application.use_cases.reports.pdf_export import report_to_pdf


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
