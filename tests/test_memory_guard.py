"""Тесты memory_guard."""

from core.memory_guard import available_memory_mb


def test_available_memory_mb_returns_positive_or_none():
    free = available_memory_mb()
    if free is not None:
        assert free > 0
