"""Тесты парсера документов."""

from infrastructure.knowledge.document_parser import chunk_text, parse_file


def test_chunk_text_splits_paragraphs():
    text = "Первый абзац.\n\nВторой абзац с большим количеством текста для проверки."
    chunks = chunk_text(text, base_metadata={"source": "test"})
    assert len(chunks) >= 1
    assert chunks[0]["metadata"]["source"] == "test"


def test_parse_txt_file(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("Строка один\nСтрока два", encoding="utf-8")
    text, meta = parse_file(path)
    assert "Строка один" in text
    assert meta["source_type"] == "text"
