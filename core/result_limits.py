"""Предупреждения об обрезке больших результатов группировки."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.config import settings


def apply_result_limit_meta(
    payload: Dict[str, Any],
    *,
    mode: str,
    total_rows: int,
    returned_rows: int,
    limit: int,
) -> None:
    """Дополнить ответ флагами truncated / result_warning (in-place)."""
    truncated = total_rows > returned_rows
    if truncated:
        payload["result_truncated"] = True
        payload["result_total_rows"] = total_rows

    threshold = int(getattr(settings, "GROUP_RESULT_WARN_ROWS", 10_000))
    if mode == "grouped" and total_rows >= threshold:
        payload["result_warning"] = (
            f"Группировка дала {total_rows:,} строк — показано {returned_rows:,}. "
            "Уточните фильтры или уменьшите cardinality полей group_by."
        ).replace(",", " ")
