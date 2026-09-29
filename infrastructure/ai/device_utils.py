"""Выбор устройства LLM/эмбеддингов: CUDA или CPU."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict

from core.config import settings

logger = logging.getLogger(__name__)


def cuda_available() -> bool:
    """True, если PyTorch видит хотя бы один GPU."""
    try:
        import torch

        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except ImportError:
        return False


def resolve_llm_device() -> str:
    """
    Разрешить устройство для LLM: cuda | cpu.
    LLM_DEVICE: auto | cuda | cpu
    """
    mode = (getattr(settings, "LLM_DEVICE", None) or "auto").strip().lower()
    if mode == "cpu":
        return "cpu"
    if mode == "cuda":
        if not cuda_available():
            logger.warning("LLM_DEVICE=cuda, но GPU недоступен — используется CPU")
            return "cpu"
        return "cuda"
    return "cuda" if cuda_available() else "cpu"


def resolve_embedding_device() -> str:
    """Устройство для sentence-transformers."""
    if not getattr(settings, "EMBEDDING_USE_CUDA", True):
        return "cpu"
    mode = (getattr(settings, "EMBEDDING_DEVICE", None) or "auto").strip().lower()
    if mode == "cpu":
        return "cpu"
    if mode == "cuda":
        return "cuda" if cuda_available() else "cpu"
    return "cuda" if cuda_available() else "cpu"


def torch_dtype_for_device(device: str):
    import torch

    if device == "cuda":
        return torch.float16
    return torch.float32


@lru_cache(maxsize=1)
def device_info() -> Dict[str, Any]:
    """Сводка для health/API."""
    info: Dict[str, Any] = {
        "llm_device": resolve_llm_device(),
        "embedding_device": resolve_embedding_device(),
        "cuda_available": cuda_available(),
        "cuda_device_count": 0,
        "cuda_device_name": None,
    }
    if cuda_available():
        import torch

        info["cuda_device_count"] = int(torch.cuda.device_count())
        try:
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
        except Exception:
            pass
    return info
