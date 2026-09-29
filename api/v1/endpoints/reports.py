"""REST-эндпоинты генерации, просмотра и экспорта отчётов."""

import csv
import io
import json
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from api.v1.endpoints.export_data import FilterSpec

from api.deps import AnalystDep, ViewerDep
from application.use_cases.reports.report_service import CHART_TYPES, ReportService
from application.use_cases.reports.pdf_export import report_to_pdf
from core.exceptions import AppException
from infrastructure.storage import report_store

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportGenerateRequest(BaseModel):
    """Тело запроса на генерацию отчёта."""

    dataset_id: int
    report_type: str = "summary"
    group_by: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=3, le=50)
    chart_types: List[str] = Field(
        default_factory=lambda: ["bar", "histogram", "pie"]
    )
    chart_metric: Optional[str] = None
    filters: List[FilterSpec] = Field(default_factory=list)


def _report_to_html(report: dict) -> str:
    """Сформировать автономный HTML-документ из отчёта."""
    title = report.get("name") or f"Отчёт #{report.get('id', '')}"
    parts = [
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#1a1a2e}",
        "h1,h2{color:#0f766e}table{border-collapse:collapse;width:100%;margin:1rem 0}",
        "th,td{border:1px solid #ddd;padding:0.5rem;text-align:left}",
        "th{background:#f0fdfa}.meta{color:#64748b;font-size:0.9rem}",
        "article{white-space:pre-wrap;line-height:1.5}",
        "</style></head><body>",
        f"<h1>{title}</h1>",
        f"<p class='meta'>Набор #{report.get('dataset_id')} · "
        f"{report.get('report_type', '')} · {report.get('created_at', '')}</p>",
    ]

    if report.get("analysis_text"):
        parts.append(f"<h2>AI-анализ</h2><article>{report['analysis_text']}</article>")

    for table in report.get("tables") or []:
        parts.append(f"<h2>{table.get('title', 'Таблица')}</h2>")
        cols = table.get("columns") or []
        rows = table.get("rows") or []
        if not cols:
            continue
        parts.append("<table><thead><tr>")
        parts.extend(f"<th>{c}</th>" for c in cols)
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            for c in cols:
                val = row.get(c, "")
                parts.append(f"<td>{val if val is not None else '—'}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")

    insights = report.get("insights") or []
    if insights:
        parts.append("<h2>Ключевые выводы</h2><ul>")
        parts.extend(f"<li>{i}</li>" for i in insights)
        parts.append("</ul>")

    parts.append("</body></html>")
    return "".join(parts)


def _report_tables_to_csv(report: dict) -> str:
    """Экспорт всех таблиц отчёта в один CSV с разделителями секций."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    for table in report.get("tables") or []:
        writer.writerow([f"=== {table.get('title', 'Таблица')} ==="])
        cols = table.get("columns") or []
        if cols:
            writer.writerow(cols)
            for row in table.get("rows") or []:
                writer.writerow([row.get(c, "") for c in cols])
        writer.writerow([])
    return buf.getvalue()


@router.get("/")
async def list_reports(_user: ViewerDep):
    """Список сохранённых отчётов (облегчённый, без таблиц и графиков)."""
    return {"status": "success", "data": report_store.list_reports()}


@router.delete("/")
async def clear_all_reports(_user: AnalystDep):
    """Удалить всю историю отчётов."""
    deleted = report_store.clear_reports()
    return {
        "status": "success",
        "message": "Report history cleared",
        "data": {"deleted": deleted},
    }


@router.get("/chart-types")
async def list_chart_types(_user: ViewerDep):
    """Доступные типы графиков для отчёта."""
    return {
        "status": "success",
        "data": sorted(CHART_TYPES),
    }


@router.get("/{report_id}/export")
async def export_report(
    report_id: int,
    _user: ViewerDep,
    format: str = Query("json", pattern="^(json|html|csv|pdf)$"),
):
    """Экспорт отчёта в файл: json, html, csv или pdf."""
    item = report_store.get_report(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report not found")

    filename_base = f"report_{report_id}_{item.get('report_type', 'export')}"

    if format == "json":
        content = json.dumps(item, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.json"'
            },
        )
    if format == "html":
        return HTMLResponse(
            content=_report_to_html(item),
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.html"'
            },
        )
    if format == "pdf":
        pdf_bytes = report_to_pdf(item)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.pdf"'
            },
        )
    return Response(
        content=_report_tables_to_csv(item),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.csv"'
        },
    )


@router.get("/{report_id}")
async def get_report(report_id: int, _user: ViewerDep):
    """Получить полный отчёт по ID (таблицы, графики, выводы)."""
    item = report_store.get_report(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "success", "data": item}


@router.delete("/{report_id}")
async def delete_report(report_id: int, _user: AnalystDep):
    """Удалить один отчёт из истории."""
    if not report_store.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "success", "message": "Report deleted", "data": {"id": report_id}}


@router.post("/generate")
async def generate_report(body: ReportGenerateRequest, _user: AnalystDep):
    """Генерация отчёта с группировкой, топами и графиками."""
    try:
        record = await ReportService().generate(
            body.dataset_id,
            body.report_type,
            group_by=body.group_by,
            metrics=body.metrics,
            top_n=body.top_n,
            chart_types=body.chart_types,
            chart_metric=body.chart_metric,
            filters=[f.model_dump() for f in body.filters],
        )
        return {
            "status": "success",
            "message": "Report generated",
            "data": record,
        }
    except AppException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
