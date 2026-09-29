"""Тесты лексического и гибридного ранжирования базы знаний."""

from infrastructure.ai.rag import hybrid_search


def _item(chunk_id, text, *, title="Документ", document_id="doc-1"):
    return {"id": chunk_id, "document_id": document_id, "document_title": title,
            "text": text, "metadata": {"document_id": document_id, "document_title": title}}


def test_lexical_search_prefers_exact_phrase_and_title():
    items = [
        _item("body", "Порядок подготовки: ежемесячный отчет"),
        _item("title", "Краткое описание", title="Ежемесячный отчет"),
        _item("noise", "Отчет содержит общую информацию без указания периода"),
    ]
    ranked = hybrid_search.lexical_search("ежемесячный отчет", items, limit=3)
    assert [item["id"] for item in ranked[:2]] == ["title", "body"]
    assert ranked[0]["keyword_score"] > ranked[-1]["keyword_score"]


def test_hybrid_search_filters_lexical_candidates_by_document(monkeypatch):
    items = [
        _item("wanted", "регламент обработки обращений", document_id="doc-1"),
        _item("other", "регламент обработки обращений", document_id="doc-2"),
    ]
    monkeypatch.setattr(hybrid_search.chunk_store, "all_chunks", lambda collection: items)
    monkeypatch.setattr(hybrid_search.chroma_client, "vector_search", lambda *args, **kwargs: [])
    ranked = hybrid_search.hybrid_search(
        "quart_knowledge", "регламент обработки", top_k=5, document_id="doc-1"
    )
    assert [item["id"] for item in ranked] == ["wanted"]
    assert ranked[0]["match"]["keyword_rank"] == 1
