"""Выбор листов Excel при чтении и join."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from application.use_cases.datasets.join_service import DatasetJoinService
from core.config import settings
from infrastructure.storage import dataset_store
from infrastructure.storage.schema_reader import get_excel_sheet_names, read_dataframe


def _write_xlsx(path: Path, sheets: dict[str, list[tuple[object, ...]]]) -> None:
    """Создать минимальную XLSX-книгу без тестовой зависимости от xlsxwriter."""
    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    ]
    workbook_sheets = []
    workbook_rels = []
    sheet_xml: dict[str, str] = {}
    for index, (name, rows) in enumerate(sheets.items(), 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        workbook_sheets.append(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
        workbook_rels.append(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        xml_rows = []
        for row_number, row in enumerate(rows, 1):
            cells = []
            for column_number, value in enumerate(row, 1):
                column = chr(64 + column_number)
                if isinstance(value, (int, float)):
                    cells.append(f'<c r="{column}{row_number}"><v>{value}</v></c>')
                else:
                    cells.append(
                        f'<c r="{column}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
                    )
            xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
        sheet_xml[f"xl/worksheets/sheet{index}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
        )
    content_types.append("</Types>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "".join(content_types))
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(workbook_sheets)
            + "</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(workbook_rels)
            + "</Relationships>",
        )
        for filename, xml in sheet_xml.items():
            archive.writestr(filename, xml)


def test_read_selected_excel_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "book.xlsx"
    _write_xlsx(
        source,
        {
            "Первый": [("key", "value"), (1, "wrong")],
            "Нужный": [("key", "value"), (1, "selected")],
        },
    )
    assert get_excel_sheet_names(source) == ["Первый", "Нужный"]
    assert read_dataframe(source, sheet_name="Нужный")["value"].to_list() == ["selected"]


@pytest.mark.asyncio
async def test_join_uses_independent_excel_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    left_path = tmp_path / "left-source.xlsx"
    right_path = tmp_path / "right-source.xlsx"
    _write_xlsx(left_path, {"Не тот": [("id",), (99,)], "Левый": [("id", "left"), (1, "L")]})
    _write_xlsx(right_path, {"Правый": [("id", "right"), (1, "R")], "Пустой": [("id",), (42,)]})
    left = dataset_store.save_dataset(
        original_filename="left.xlsx", content=left_path.read_bytes(), allow_duplicate=True,
        sheet_names=["Не тот", "Левый"], selected_sheet="Не тот",
    )
    right = dataset_store.save_dataset(
        original_filename="right.xlsx", content=right_path.read_bytes(), allow_duplicate=True,
        sheet_names=["Правый", "Пустой"], selected_sheet="Пустой",
    )

    result = await DatasetJoinService().preview(
        left["id"], right["id"], ["id"], ["id"],
        left_sheet="Левый", right_sheet="Правый",
    )

    assert result["joined_rows"] == 1
    assert result["sample_rows"][0]["left"] == "L"
    assert result["sample_rows"][0]["right"] == "R"
    assert result["left_sheet"] == "Левый"
    assert result["right_sheet"] == "Правый"
