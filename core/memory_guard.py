"""Проверка доступной RAM перед тяжёлыми операциями (без внешних зависимостей)."""

from __future__ import annotations

import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def available_memory_mb() -> Optional[float]:
    """Свободная физическая память в МБ; None если ОС не поддерживается."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None
            return float(stat.ullAvailPhys) / (1024 * 1024)

        # Linux / macOS
        pages = sysconf("SC_AVPHYS_PAGES")
        page_size = sysconf("SC_PAGE_SIZE")
        if pages is None or page_size is None:
            return None
        return float(pages * page_size) / (1024 * 1024)
    except Exception as exc:
        logger.debug("available_memory_mb failed: %s", exc)
        return None


def sysconf(name: str) -> Optional[int]:
    try:
        import os

        return os.sysconf(name)
    except (AttributeError, ValueError, OSError):
        return None


def ensure_min_free_ram(min_mb: int, *, operation: str = "operation") -> None:
    """ValueError если свободной RAM меньше порога."""
    if min_mb <= 0:
        return
    free_mb = available_memory_mb()
    if free_mb is None:
        return
    if free_mb < min_mb:
        raise ValueError(
            f"Недостаточно свободной RAM для {operation}: "
            f"{free_mb:.0f} МБ доступно, требуется ≥ {min_mb} МБ. "
            "Закройте лишние приложения и повторите."
        )
