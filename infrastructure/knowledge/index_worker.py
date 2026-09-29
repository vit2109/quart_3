"""Изолированный процесс индексации — защита основного сервера от OOM/reboot."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a knowledge document by id")
    parser.add_argument("document_id", help="Document id in knowledge store")
    parser.add_argument(
        "--collection",
        default="quart_knowledge",
        help="Chroma collection name",
    )
    args = parser.parse_args()

    import core.env_bootstrap  # noqa: F401 — до torch/transformers

    from core.config import settings
    from core.memory_guard import ensure_min_free_ram
    from application.use_cases.knowledge.knowledge_service import KnowledgeService

    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, logging.INFO))

    try:
        ensure_min_free_ram(
            int(settings.KNOWLEDGE_MIN_FREE_RAM_MB or 0),
            operation="индексации документа",
        )
        svc = KnowledgeService()
        result = svc.index_document_inprocess(
            args.document_id,
            collection=args.collection,
        )
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
