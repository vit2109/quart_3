"""Переменные окружения до импорта torch/transformers (import first in main.py)."""

from __future__ import annotations

import os

# LLM_DEVICE=cpu или LLM_USE_CUDA=0 — принудительно скрыть GPU
_llm_device = os.environ.get("LLM_DEVICE", "auto").strip().lower()
_use_cuda = os.environ.get("LLM_USE_CUDA", "1").strip().lower()
_force_cpu = _llm_device == "cpu" or _use_cuda in {"0", "false", "no", "off"}

if _force_cpu:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
elif "CUDA_VISIBLE_DEVICES" in os.environ and os.environ["CUDA_VISIBLE_DEVICES"] == "":
    # Пустая строка ломает torch.cuda.device_count() — убираем
    del os.environ["CUDA_VISIBLE_DEVICES"]

if not _force_cpu:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
