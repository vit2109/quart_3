"""HTTP webhook-уведомления по завершению фоновых задач."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def send_webhook(
    url: str,
    *,
    event: str,
    job_type: str,
    run_id: str,
    status: str,
    payload: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    schedule_id: Optional[int] = None,
    schedule_name: Optional[str] = None,
) -> bool:
    """POST JSON на webhook URL; True при HTTP 2xx."""
    if not url or not str(url).strip().startswith(("http://", "https://")):
        return False

    body = {
        "event": event,
        "job_type": job_type,
        "run_id": run_id,
        "status": status,
        "schedule_id": schedule_id,
        "schedule_name": schedule_name,
        "payload": payload or {},
        "result": result,
        "error": error,
    }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(str(url).strip(), json=body)
            if resp.status_code >= 400:
                logger.warning("Webhook %s returned %s", url, resp.status_code)
                return False
            return True
    except Exception as exc:
        logger.warning("Webhook notify failed for %s: %s", url, exc)
        return False
