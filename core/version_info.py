"""Метаданные сборки для /health и диагностики."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional


@lru_cache(maxsize=1)
def get_git_commit(short: bool = True) -> Optional[str]:
    """Короткий hash HEAD или None вне git / при ошибке."""
    try:
        root = Path(__file__).resolve().parent.parent
        args = ["git", "rev-parse", "--short", "HEAD"] if short else ["git", "rev-parse", "HEAD"]
        out = subprocess.check_output(
            args,
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return out.decode("utf-8", errors="replace").strip() or None
    except Exception:
        return None


def build_health_payload(
    *,
    app_version: str,
    environment: str,
    debug: bool,
    postgresql: bool,
) -> Dict[str, Any]:
    commit = get_git_commit()
    payload: Dict[str, Any] = {
        "status": "healthy",
        "version": app_version,
        "environment": environment,
        "debug": debug,
        "postgresql": postgresql,
        "api_prefix": "/api/v1",
    }
    if commit:
        payload["git_commit"] = commit
    return payload
