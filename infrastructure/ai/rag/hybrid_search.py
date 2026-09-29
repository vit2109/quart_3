"""Гибридный поиск: семантический поиск, BM25 и устойчивое объединение рангов."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from infrastructure.ai.rag import chroma_client
from infrastructure.knowledge import chunk_store

TOKEN_RE = re.compile(r"[\w\d_]+", re.UNICODE)


def _tokens(text: str) -> List[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text or "") if len(token) > 1]


def _searchable_text(item: Dict[str, Any]) -> str:
    meta = item.get("metadata") or {}
    fields = [item.get("document_title"), meta.get("document_title"), meta.get("filename"),
              meta.get("section_title"), item.get("text")]
    for key in ("keywords", "numbers"):
        value = meta.get(key)
        if isinstance(value, list):
            fields.extend(str(part) for part in value)
    return " ".join(str(value) for value in fields if value)


def lexical_search(query: str, items: Sequence[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
    """Ранжировать фрагменты BM25 с бонусами за точную фразу и заголовок."""
    query_tokens = _tokens(query)
    if not query_tokens or not items:
        return []
    documents = [_tokens(_searchable_text(item)) for item in items]
    avg_length = sum(map(len, documents)) / max(len(documents), 1)
    document_frequency = Counter()
    for tokens in documents:
        document_frequency.update(set(tokens))
    query_phrase = " ".join(query_tokens)
    ranked: List[Dict[str, Any]] = []
    for item, tokens in zip(items, documents):
        frequencies = Counter(tokens)
        score = 0.0
        for token in set(query_tokens):
            frequency = frequencies[token]
            if not frequency:
                continue
            frequency_docs = document_frequency[token]
            inverse_frequency = math.log(1 + (len(items) - frequency_docs + 0.5) / (frequency_docs + 0.5))
            length_norm = frequency + 1.5 * (0.25 + 0.75 * len(tokens) / max(avg_length, 1))
            score += inverse_frequency * (frequency * 2.5) / length_norm
        searchable = _searchable_text(item).casefold()
        meta = item.get("metadata") or {}
        title = " ".join(str(value) for value in
                         (item.get("document_title"), meta.get("document_title"), meta.get("section_title"))
                         if value).casefold()
        if query_phrase and query_phrase in searchable:
            score += 1.5
        if query_phrase and query_phrase in title:
            score += 2.0
        if score > 0:
            result = dict(item)
            result["keyword_score"] = round(score, 6)
            ranked.append(result)
    ranked.sort(key=lambda item: (-item["keyword_score"], item.get("id", "")))
    return ranked[:limit]


def keyword_score(query: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
    """Совместимый helper для оценки одного фрагмента."""
    ranked = lexical_search(query, [{"id": "item", "text": text, "metadata": metadata or {}}], limit=1)
    return ranked[0]["keyword_score"] if ranked else 0.0


def hybrid_search(collection_name: str, query: str, *, top_k: int = 8, alpha: float = 0.65,
                  document_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Объединить vector и BM25 результаты через weighted reciprocal-rank fusion."""
    candidate_count = max(top_k * 4, 20)
    where = {"document_id": document_id} if document_id else None
    vector_hits = chroma_client.vector_search(collection_name, query, n_results=candidate_count, where=where)
    lexical_candidates = chunk_store.all_chunks(collection_name)
    if document_id:
        lexical_candidates = [item for item in lexical_candidates if item.get("document_id") == document_id]
    keyword_hits = lexical_search(query, lexical_candidates, limit=candidate_count)
    merged: Dict[str, Dict[str, Any]] = {}
    vector_rank: Dict[str, int] = {}
    keyword_rank: Dict[str, int] = {}
    for rank, hit in enumerate(vector_hits, 1):
        chunk_id = hit["id"]
        vector_rank[chunk_id] = rank
        merged[chunk_id] = {"id": chunk_id, "text": hit.get("text") or "",
                            "metadata": hit.get("metadata") or {},
                            "vector_score": hit.get("vector_score", 0.0), "keyword_score": 0.0}
    for rank, hit in enumerate(keyword_hits, 1):
        chunk_id = hit["id"]
        keyword_rank[chunk_id] = rank
        current = merged.setdefault(chunk_id, {"id": chunk_id, "text": hit.get("text") or "",
                                               "metadata": hit.get("metadata") or {},
                                               "vector_score": 0.0, "keyword_score": 0.0})
        current["keyword_score"] = hit["keyword_score"]
    rrf_constant = 60
    for chunk_id, item in merged.items():
        score = 0.0
        if chunk_id in vector_rank:
            score += alpha / (rrf_constant + vector_rank[chunk_id])
        if chunk_id in keyword_rank:
            score += (1 - alpha) / (rrf_constant + keyword_rank[chunk_id])
        item["hybrid_score"] = round(score, 6)
        item["match"] = {"vector_rank": vector_rank.get(chunk_id), "keyword_rank": keyword_rank.get(chunk_id)}
    return sorted(merged.values(), key=lambda item: (-item["hybrid_score"], item["id"]))[:top_k]
