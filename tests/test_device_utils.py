"""Тесты выбора устройства LLM."""

from infrastructure.ai.device_utils import cuda_available, resolve_llm_device


def test_cuda_available_with_gpu():
    # На машине с GPU в CI может быть False — проверяем только тип
    assert isinstance(cuda_available(), bool)


def test_resolve_llm_device_returns_cpu_or_cuda():
    assert resolve_llm_device() in {"cpu", "cuda"}
