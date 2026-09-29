"""Экспорт отчёта в PDF (ReportLab)."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _safe_text(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _build_table(title: str, columns: List[str], rows: List[Dict[str, Any]], styles) -> List[Any]:
    flow: List[Any] = []
    if title:
        flow.append(Paragraph(_safe_text(title), styles["Heading3"]))
        flow.append(Spacer(1, 0.15 * cm))

    if not columns:
        flow.append(Paragraph("Нет колонок", styles["Normal"]))
        return flow

    header = [_safe_text(c) for c in columns]
    body = [[_safe_text(row.get(c)) for c in columns] for row in rows]
    data = [header] + body

    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    flow.append(table)
    flow.append(Spacer(1, 0.35 * cm))
    return flow



def report_to_pdf(report: Dict[str, Any]) -> bytes:
    """Сформировать PDF-байты из структуры отчёта."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=str(report.get("name") or "Report"),
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportMeta",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=6,
        )
    )

    story: List[Any] = []
    title = report.get("name") or f"Отчёт #{report.get('id', '')}"
    story.append(Paragraph(_safe_text(title), styles["Title"]))
    story.append(Spacer(1, 0.25 * cm))

    meta_parts = [
        f"Набор данных: #{report.get('dataset_id', '—')}",
        f"Тип: {report.get('report_type', '—')}",
        f"Создан: {report.get('created_at', '—')}",
    ]
    story.append(Paragraph(" · ".join(meta_parts), styles["ReportMeta"]))
    story.append(Spacer(1, 0.35 * cm))

    analysis_text = (report.get("analysis_text") or "").strip()
    if analysis_text:
        story.append(Paragraph("AI-анализ", styles["Heading2"]))
        for line in analysis_text.splitlines():
            story.append(Paragraph(_safe_text(line) or "&nbsp;", styles["Normal"]))
        story.append(Spacer(1, 0.35 * cm))

    for table in report.get("tables") or []:
        story.extend(
            _build_table(
                str(table.get("title") or "Таблица"),
                list(table.get("columns") or []),
                list(table.get("rows") or []),
                styles,
            )
        )

    charts = report.get("charts") or []
    if charts:
        story.append(Paragraph("Графики (сводка)", styles["Heading2"]))
        for chart in charts:
            chart_title = chart.get("title") or chart.get("type") or "График"
            labels = chart.get("labels") or []
            datasets = chart.get("datasets") or []
            values = datasets[0].get("data") if datasets else []
            lines = [
                f"{_safe_text(labels[i] if i < len(labels) else i)}: {_safe_text(values[i] if i < len(values) else '—')}"
                for i in range(max(len(labels), len(values)))
            ]
            story.append(Paragraph(_safe_text(chart_title), styles["Heading3"]))
            for line in lines[:50]:
                story.append(Paragraph(line, styles["Normal"]))
            if len(lines) > 50:
                story.append(Paragraph(f"... ещё {len(lines) - 50} значений", styles["ReportMeta"]))
            story.append(Spacer(1, 0.25 * cm))

    insights = report.get("insights") or []
    if insights:
        story.append(Paragraph("Ключевые выводы", styles["Heading2"]))
        for item in insights:
            story.append(Paragraph(f"• {_safe_text(item)}", styles["Normal"]))
        story.append(Spacer(1, 0.25 * cm))

    doc.build(story)
    return buf.getvalue()
