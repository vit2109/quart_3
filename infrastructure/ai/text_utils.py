"""Постобработка текста LLM: удаление циклических повторов."""

from __future__ import annotations

import re
from typing import List, Set


def _normalize_block(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:240]


def _section_title_key(line: str) -> str:
    """Ключ заголовка без номера секции (1., 2. …)."""
    if not re.match(r"^\s*#", line or ""):
        return ""
    title = re.sub(r"^\s*#+\s*", "", line.strip())
    title = re.sub(r"^\d+\.\s*", "", title)
    title = re.sub(r"\*+", "", title)
    return re.sub(r"\s+", " ", title).strip().lower().strip(".")


def _blocks_similar(a: str, b: str) -> bool:
    na, nb = _normalize_block(a), _normalize_block(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) > 50 and shorter in longer


def dedupe_llm_output(text: str) -> str:
    """
    Обрезать ответ при повторении абзацев, заголовков или секций markdown.
    """
    if not text:
        return text
    body = text.strip()

    seen_titles: Set[str] = set()
    lines_out: List[str] = []
    for line in body.splitlines():
        title_key = _section_title_key(line)
        if title_key:
            if title_key in seen_titles:
                break
            seen_titles.add(title_key)
        lines_out.append(line)
    body = "\n".join(lines_out).strip()

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paragraphs:
        return body

    unique: List[str] = []
    for para in paragraphs:
        if any(_blocks_similar(para, prev) for prev in unique):
            break
        key = _normalize_block(para)
        if key and any(_blocks_similar(para, prev) for prev in unique):
            break
        unique.append(para)

    return "\n\n".join(unique).strip() or body
