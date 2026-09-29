"""Экспорт отчёта в PDF с Unicode-шрифтами и векторными диаграммами."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Circle, Drawing, Line
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_REGULAR = "QuartUnicode"
FONT_BOLD = "QuartUnicodeBold"
PALETTE = [
    colors.HexColor("#0f766e"),
    colors.HexColor("#2563eb"),
    colors.HexColor("#d97706"),
    colors.HexColor("#7c3aed"),
    colors.HexColor("#dc2626"),
    colors.HexColor("#0891b2"),
    colors.HexColor("#4d7c0f"),
    colors.HexColor("#be185d"),
]


def _font_candidates() -> List[Tuple[Path, Path]]:
    return [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        ),
    ]


def _register_unicode_fonts() -> Tuple[str, str]:
    """Зарегистрировать TTF с кириллицей и гарантировать его встраивание."""
    if FONT_REGULAR in pdfmetrics.getRegisteredFontNames():
        return FONT_REGULAR, FONT_BOLD
    for regular, bold in _font_candidates():
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(regular)))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))
            pdfmetrics.registerFontFamily(
                "QuartUnicodeFamily",
                normal=FONT_REGULAR,
                bold=FONT_BOLD,
                italic=FONT_REGULAR,
                boldItalic=FONT_BOLD,
            )
            return FONT_REGULAR, FONT_BOLD
    raise RuntimeError(
        "Unicode-шрифт для PDF не найден. Установите fonts-dejavu-core "
        "(Linux/Docker) или Arial (Windows)."
    )


def _safe_text(value: Any) -> str:
    if value is None:
        return "—"
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _configure_styles(regular: str, bold: str):
    styles = getSampleStyleSheet()
    for name in ("Normal", "BodyText"):
        styles[name].fontName = regular
        styles[name].leading = 13
    for name in ("Title", "Heading1", "Heading2", "Heading3", "Heading4"):
        styles[name].fontName = bold
    styles.add(
        ParagraphStyle(
            name="ReportMeta",
            parent=styles["Normal"],
            fontName=regular,
            fontSize=9,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["Normal"],
            fontName=bold,
            fontSize=7.5,
            leading=9,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["Normal"],
            fontName=regular,
            fontSize=7.5,
            leading=9,
        )
    )
    return styles


def _build_table(
    title: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
    styles,
    bold_font: str,
) -> List[Any]:
    flow: List[Any] = []
    if title:
        flow.append(Paragraph(_safe_text(title), styles["Heading3"]))
        flow.append(Spacer(1, 0.15 * cm))
    if not columns:
        flow.append(Paragraph("Нет колонок", styles["Normal"]))
        return flow

    header = [Paragraph(_safe_text(column), styles["TableHeader"]) for column in columns]
    body = [
        [Paragraph(_safe_text(row.get(column)), styles["TableCell"]) for column in columns]
        for row in rows
    ]
    available_width = A4[0] - 3 * cm
    column_width = available_width / max(len(columns), 1)
    table = Table(
        [header] + body,
        colWidths=[column_width] * len(columns),
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.extend([table, Spacer(1, 0.35 * cm)])
    return flow


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _short_labels(labels: Sequence[Any], count: int) -> List[str]:
    result = []
    for label in labels[:count]:
        text = str(label)
        result.append(text if len(text) <= 18 else text[:17] + "…")
    return result


def _chart_drawing(chart_spec: Dict[str, Any], regular: str) -> Drawing | None:
    chart_type = str(chart_spec.get("type") or "bar").lower()
    datasets = chart_spec.get("datasets") or []
    if not datasets:
        return None
    raw_data = datasets[0].get("data") or []
    drawing = Drawing(500, 245)

    if chart_type == "scatter":
        points = [point for point in raw_data[:80] if isinstance(point, dict)]
        if not points:
            return None
        xs = [_number(point.get("x")) for point in points]
        ys = [_number(point.get("y")) for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x, span_y = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
        drawing.add(Line(48, 35, 475, 35, strokeColor=colors.HexColor("#94a3b8")))
        drawing.add(Line(48, 35, 48, 220, strokeColor=colors.HexColor("#94a3b8")))
        for x_value, y_value in zip(xs, ys):
            x = 48 + 415 * (x_value - min_x) / span_x
            y = 35 + 175 * (y_value - min_y) / span_y
            drawing.add(Circle(x, y, 2.5, fillColor=PALETTE[0], strokeColor=None))
        return drawing

    labels = chart_spec.get("labels") or list(range(len(raw_data)))
    values = [_number(value) for value in raw_data[:12]]
    labels = _short_labels(labels, len(values))
    if not values:
        return None

    if chart_type in {"pie", "doughnut"}:
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = 35, 25, 190, 190
        pie.data = [max(value, 0) for value in values]
        pie.labels = labels
        pie.slices.fontName = regular
        pie.slices.fontSize = 7
        pie.sideLabels = True
        for index in range(len(values)):
            pie.slices[index].fillColor = PALETTE[index % len(PALETTE)]
        drawing.add(pie)
        return drawing

    if chart_type == "line":
        chart = HorizontalLineChart()
        chart.x, chart.y, chart.width, chart.height = 55, 45, 415, 165
        chart.data = [values]
        chart.categoryAxis.categoryNames = labels
        chart.lines[0].strokeColor = PALETTE[0]
        chart.lines[0].strokeWidth = 2
    elif chart_spec.get("index_axis") == "y":
        chart = HorizontalBarChart()
        chart.x, chart.y, chart.width, chart.height = 95, 35, 370, 180
        chart.data = [values]
        chart.categoryAxis.categoryNames = labels
        chart.bars[0].fillColor = PALETTE[0]
    else:
        chart = VerticalBarChart()
        chart.x, chart.y, chart.width, chart.height = 55, 45, 415, 165
        chart.data = [values]
        chart.categoryAxis.categoryNames = labels
        chart.bars[0].fillColor = PALETTE[0]

    chart.categoryAxis.labels.fontName = regular
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 30 if len(labels) > 6 else 0
    chart.valueAxis.labels.fontName = regular
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = min(0, min(values))
    drawing.add(chart)
    return drawing


def report_to_pdf(report: Dict[str, Any]) -> bytes:
    """Сформировать PDF-байты из структуры отчёта."""
    regular, bold = _register_unicode_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=str(report.get("name") or "Отчёт"),
    )
    styles = _configure_styles(regular, bold)
    story: List[Any] = []

    title = report.get("name") or f"Отчёт #{report.get('id', '')}"
    story.extend([Paragraph(_safe_text(title), styles["Title"]), Spacer(1, 0.25 * cm)])
    meta_parts = [
        f"Набор данных: #{report.get('dataset_id', '—')}",
        f"Тип: {report.get('report_type', '—')}",
        f"Создан: {report.get('created_at', '—')}",
    ]
    story.extend(
        [Paragraph(" · ".join(meta_parts), styles["ReportMeta"]), Spacer(1, 0.35 * cm)]
    )

    analysis_text = (report.get("analysis_text") or "").strip()
    if analysis_text:
        story.append(Paragraph("AI-анализ", styles["Heading2"]))
        for line in analysis_text.splitlines():
            story.append(Paragraph(_safe_text(line) or "&nbsp;", styles["Normal"]))
        story.append(Spacer(1, 0.35 * cm))

    for table_spec in report.get("tables") or []:
        story.extend(
            _build_table(
                str(table_spec.get("title") or "Таблица"),
                list(table_spec.get("columns") or []),
                list(table_spec.get("rows") or []),
                styles,
                bold,
            )
        )

    charts = report.get("charts") or []
    if charts:
        story.append(Paragraph("Диаграммы", styles["Heading2"]))
        for chart_spec in charts:
            chart_title = chart_spec.get("title") or chart_spec.get("type") or "Диаграмма"
            drawing = _chart_drawing(chart_spec, regular)
            if drawing is None:
                continue
            story.append(
                KeepTogether(
                    [
                        Paragraph(_safe_text(chart_title), styles["Heading3"]),
                        Spacer(1, 0.1 * cm),
                        drawing,
                        Spacer(1, 0.3 * cm),
                    ]
                )
            )

    insights = report.get("insights") or []
    if insights:
        story.append(Paragraph("Ключевые выводы", styles["Heading2"]))
        for item in insights:
            story.append(Paragraph(f"• {_safe_text(item)}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()
