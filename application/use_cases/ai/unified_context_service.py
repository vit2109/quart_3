"""Сквозной контекст: табличные данные + база знаний в одном AI-ответе."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from application.use_cases.ai.ai_service import AIService
from application.use_cases.ai.nl_query_service import NLQueryService
from application.use_cases.knowledge.knowledge_service import KnowledgeService
from core.config import settings
from core.exceptions import AIError, NotFoundError
from infrastructure.ai.llama_client import LocalLLMClient
from infrastructure.storage import dataset_store

logger = logging.getLogger(__name__)

UNIFIED_SYSTEM = """Ты — аналитик с доступом к табличным данным и базе знаний организации.
Отвечай на русском, опираясь только на предоставленный контекст.
Структура ответа:
1) Краткий ответ
2) Факты из таблицы (если есть)
3) Факты из базы знаний (если есть)
4) Выводы и рекомендации
Если контекста недостаточно — скажи прямо."""


class UnifiedContextService:
    """Объединённый RAG + табличный NL/статистика."""

    def __init__(self) -> None:
        self.llm = LocalLLMClient()
        self.ai = AIService()
        self.knowledge = KnowledgeService()
        self.nl = NLQueryService()

    async def ask(
        self,
        dataset_id: int,
        question: str,
        *,
        knowledge_top_k: int = 5,
        include_table_query: bool = True,
        include_knowledge: bool = True,
        save_report: bool = False,
    ) -> Dict[str, Any]:
        timeout = max(int(settings.LLM_TIMEOUT or 900), 300)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._ask_blocking,
                    dataset_id,
                    question,
                    knowledge_top_k,
                    include_table_query,
                    include_knowledge,
                    save_report,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise AIError(f"Unified ask exceeded {timeout}s") from exc

    def _ask_blocking(
        self,
        dataset_id: int,
        question: str,
        knowledge_top_k: int,
        include_table_query: bool,
        include_knowledge: bool,
        save_report: bool,
    ) -> Dict[str, Any]:
        item = dataset_store.get_dataset(dataset_id)
        if not item:
            raise NotFoundError(f"Dataset {dataset_id} not found")

        question = (question or "").strip()
        if not question:
            raise ValueError("question is required")

        knowledge_hits: List[Dict[str, Any]] = []
        knowledge_block = ""
        if include_knowledge:
            search = self.knowledge._search_blocking(
                question, "hybrid", knowledge_top_k, None, "quart_knowledge"
            )
            knowledge_hits = search.get("results") or []
            if knowledge_hits:
                blocks = []
                for i, hit in enumerate(knowledge_hits, 1):
                    meta = hit.get("metadata") or {}
                    title = meta.get("document_title") or meta.get("filename") or hit.get("id")
                    blocks.append(f"[K{i}] {title}\n{(hit.get('text') or '')[:1200]}")
                knowledge_block = "База знаний:\n" + "\n\n".join(blocks)

        table_block = ""
        nl_result: Optional[Dict[str, Any]] = None
        if include_table_query:
            try:
                nl_result = asyncio.run(self.nl.query(dataset_id, question))
                rows = nl_result.get("rows") or []
                cols = nl_result.get("columns") or []
                table_block = (
                    f"Табличный запрос (NL→Polars): {nl_result.get('explanation') or '—'}\n"
                    f"Колонки: {', '.join(cols)}\n"
                    f"Строк: {len(rows)}\n"
                    f"Пример: {json.dumps(rows[:8], ensure_ascii=False, default=str)}"
                )
            except Exception as exc:
                logger.debug("NL query in unified ask skipped: %s", exc)
                ctx_json = self.ai._build_context_sync(
                    dataset_id, item, include_correlations=False, sample_rows=5
                )
                table_block = f"Сводка по таблице (JSON):\n{ctx_json[:6000]}"

        prompt = (
            f"Набор данных: {item.get('name')} (#{dataset_id})\n\n"
            f"{table_block}\n\n{knowledge_block}\n\n"
            f"Вопрос пользователя:\n{question}\n"
        )

        answer = asyncio.run(
            self.llm.generate_text(
                prompt,
                system=UNIFIED_SYSTEM,
                max_tokens=900,
                temperature=0.35,
            )
        )

        result: Dict[str, Any] = {
            "dataset_id": dataset_id,
            "question": question,
            "answer": answer,
            "knowledge_sources": [
                {
                    "chunk_id": h.get("id"),
                    "document_title": (h.get("metadata") or {}).get("document_title"),
                    "preview": (h.get("text") or "")[:200],
                }
                for h in knowledge_hits
            ],
            "table_query": nl_result,
            "include_knowledge": include_knowledge,
            "include_table_query": include_table_query,
        }

        if save_report:
            from infrastructure.storage import report_store

            record = report_store.save_report(
                {
                    "name": f"Unified: {question[:60]}",
                    "dataset_id": dataset_id,
                    "report_type": "unified",
                    "analysis_text": answer,
                    "tables": [],
                    "charts": [],
                    "insights": [],
                }
            )
            result["report_id"] = record.get("id")

        return result
