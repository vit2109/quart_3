"""Профили LLM: основная модель и модель для SQL/NL-запросов."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from core.config import settings

ProfileName = Literal["main", "sql"]


@dataclass(frozen=True)
class ModelProfileConfig:
    name: str
    llama_model_path: Optional[str]
    transformers_model_id: str
    llama_gguf_file: str
    llama_hf_repo: str
    llama_models_dir: str

    @property
    def cache_key(self) -> str:
        if self.llama_model_path:
            return f"gguf:{self.llama_model_path}"
        return f"hf:{self.transformers_model_id}"


def resolve_model_profile(name: ProfileName = "main") -> ModelProfileConfig:
    """Настройки модели для профиля; для SQL — fallback на основную модель."""
    if name == "sql":
        llama_path = settings.SQL_LLAMA_MODEL_PATH or settings.LLAMA_MODEL_PATH
        tf_id = settings.SQL_TRANSFORMERS_MODEL_ID or settings.TRANSFORMERS_MODEL_ID
    else:
        llama_path = settings.LLAMA_MODEL_PATH
        tf_id = settings.TRANSFORMERS_MODEL_ID

    return ModelProfileConfig(
        name=name,
        llama_model_path=llama_path,
        transformers_model_id=tf_id,
        llama_gguf_file=settings.LLAMA_GGUF_FILE,
        llama_hf_repo=settings.LLAMA_HF_REPO,
        llama_models_dir=settings.LLAMA_MODELS_DIR,
    )


def sql_uses_separate_model() -> bool:
    """True, если для SQL задана модель, отличная от основной."""
    if not settings.SQL_LLAMA_MODEL_PATH and not settings.SQL_TRANSFORMERS_MODEL_ID:
        return False
    main = resolve_model_profile("main")
    sql = resolve_model_profile("sql")
    return main.cache_key != sql.cache_key


def profile_with_override(
    name: ProfileName = "main",
    *,
    llama_model_path: Optional[str] = None,
) -> ModelProfileConfig:
    """Профиль с переопределением пути к GGUF (выбор модели из UI)."""
    base = resolve_model_profile(name)
    if not llama_model_path:
        return base
    from dataclasses import replace

    return replace(base, llama_model_path=llama_model_path)
