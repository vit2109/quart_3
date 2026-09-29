from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.config import settings
from core.exceptions import AIError
from infrastructure.ai.device_utils import (
    cuda_available,
    resolve_llm_device,
    torch_dtype_for_device,
)
from infrastructure.ai.model_config import ModelProfileConfig, resolve_model_profile

logger = logging.getLogger(__name__)


def models_dir(profile: Optional[ModelProfileConfig] = None) -> Path:
    cfg = profile or resolve_model_profile("main")
    path = Path(cfg.llama_models_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_gguf_path(profile: Optional[ModelProfileConfig] = None) -> Path:
    """Путь к GGUF: из llama_model_path профиля или models/<default>."""
    cfg = profile or resolve_model_profile("main")
    if cfg.llama_model_path:
        configured = Path(cfg.llama_model_path)
        if configured.exists():
            return configured.resolve()
        alt = Path.cwd() / configured
        if alt.exists():
            return alt.resolve()
    return (models_dir(cfg) / cfg.llama_gguf_file).resolve()


def list_local_models() -> list[dict]:
    """Сканирует каталог models/ и возвращает доступные GGUF-модели."""
    cfg = resolve_model_profile("main")
    root = models_dir(cfg)
    seen: set[str] = set()
    items: list[dict] = []

    default_path = resolve_gguf_path(cfg)
    if default_path.exists() and default_path.stat().st_size > 1_000:
        key = str(default_path.resolve())
        seen.add(key)
        items.append(
            {
                "id": key,
                "name": default_path.name,
                "path": key,
                "type": "gguf",
                "size_mb": round(default_path.stat().st_size / 1e6, 1),
                "is_default": True,
                "source": "env",
            }
        )

    for gguf in sorted(root.rglob("*.gguf")):
        try:
            if not gguf.is_file() or gguf.stat().st_size < 1_000_000:
                continue
        except OSError:
            continue
        key = str(gguf.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            rel = gguf.relative_to(root)
            label = str(rel).replace("\\", "/")
        except ValueError:
            label = gguf.name
        items.append(
            {
                "id": key,
                "name": gguf.name,
                "label": label,
                "path": key,
                "type": "gguf",
                "size_mb": round(gguf.stat().st_size / 1e6, 1),
                "is_default": False,
                "source": "local",
            }
        )

    return items


def ensure_gguf_model(profile: Optional[ModelProfileConfig] = None) -> Path:
    """Скачивает GGUF с Hugging Face, если файла нет локально."""
    cfg = profile or resolve_model_profile("main")
    target = resolve_gguf_path(cfg)
    if target.exists() and target.stat().st_size > 1_000_000:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    repo = cfg.llama_hf_repo
    filename = cfg.llama_gguf_file
    logger.info("Downloading GGUF %s/%s -> %s", repo, filename, target)

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise AIError(
            "Для скачивания GGUF нужен huggingface-hub. Выполните: uv add huggingface-hub"
        ) from e

    try:
        downloaded = hf_hub_download(
            repo_id=repo,
            filename=filename,
            local_dir=str(models_dir(cfg)),
        )
        downloaded_path = Path(downloaded)
        if downloaded_path.resolve() != target.resolve() and not target.exists():
            target.write_bytes(downloaded_path.read_bytes())
        if not target.exists():
            candidate = models_dir(cfg) / filename
            if candidate.exists():
                return candidate.resolve()
            raise FileNotFoundError(str(downloaded_path))
        logger.info("GGUF ready: %s (%.1f MB)", target, target.stat().st_size / 1e6)
        return target.resolve()
    except Exception as e:
        raise AIError(f"Не удалось скачать GGUF-модель ({repo}/{filename}): {e}") from e


def ensure_transformers_model(profile: Optional[ModelProfileConfig] = None) -> str:
    """
    Гарантирует наличие модели Hugging Face для transformers.
    Возвращает model_id (кэш HF скачает веса при первой загрузке).
    """
    cfg = profile or resolve_model_profile("main")
    model_id = cfg.transformers_model_id
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return model_id

    try:
        local_dir = models_dir(cfg) / "hf" / model_id.replace("/", "__")
        if local_dir.exists() and any(local_dir.rglob("*.safetensors")):
            return str(local_dir)
        logger.info("Downloading transformers model %s ...", model_id)
        path = snapshot_download(
            repo_id=model_id,
            local_dir=str(local_dir),
            ignore_patterns=["*.gguf", "*.bin.index.json"],
        )
        return path
    except Exception as e:
        logger.warning("snapshot_download failed (%s), will rely on HF cache", e)
        return model_id


_llama_lock = threading.Lock()
_llama_instances: Dict[str, object] = {}
_llama_paths: Dict[str, str] = {}

_tf_lock = threading.Lock()
_tf_models: Dict[str, object] = {}
_tf_tokenizers: Dict[str, object] = {}
_tf_model_ids: Dict[str, str] = {}


def _profile_key(profile: Optional[ModelProfileConfig] = None) -> ModelProfileConfig:
    return profile or resolve_model_profile("main")


def get_llama_cpp_model(profile: Optional[ModelProfileConfig] = None):
    """Ленивая загрузка GGUF через llama-cpp-python (in-process)."""
    cfg = _profile_key(profile)
    cache_key = cfg.cache_key
    try:
        from llama_cpp import Llama
    except ImportError as e:
        raise AIError(
            "Пакет llama-cpp-python не установлен или не собран. "
            "На Windows нужен Visual Studio Build Tools, либо используйте backend=transformers. "
            f"Детали: {e}"
        ) from e

    gguf = ensure_gguf_model(cfg)
    path = str(gguf.resolve())
    with _llama_lock:
        if cache_key in _llama_instances and _llama_paths.get(cache_key) == path:
            return _llama_instances[cache_key]
        n_ctx = settings.LLAMA_CONTEXT_SIZE
        n_threads = settings.LLAMA_N_THREADS or 4
        llama_kwargs: dict = {
            "model_path": path,
            "n_ctx": n_ctx,
            "n_threads": n_threads,
            "verbose": False,
        }
        if cuda_available() and int(getattr(settings, "LLAMA_N_GPU_LAYERS", 0) or 0) != 0:
            n_gpu = int(settings.LLAMA_N_GPU_LAYERS)
            llama_kwargs["n_gpu_layers"] = n_gpu
            logger.info(
                "Loading llama-cpp model [%s] %s (ctx=%s, threads=%s, n_gpu_layers=%s)",
                cfg.name,
                path,
                n_ctx,
                n_threads,
                n_gpu,
            )
        else:
            logger.info(
                "Loading llama-cpp model [%s] %s (ctx=%s, threads=%s, CPU)",
                cfg.name,
                path,
                n_ctx,
                n_threads,
            )
        instance = Llama(**llama_kwargs)
        _llama_instances[cache_key] = instance
        _llama_paths[cache_key] = path
        return instance


def _load_transformers_from_gguf(
    torch,
    AutoTokenizer,
    AutoModelForCausalLM,
    profile: ModelProfileConfig,
) -> Tuple[object, object, str]:
    """Загрузка локального GGUF через transformers (без llama-cpp и без HF-сервера)."""
    try:
        import gguf  # noqa: F401
    except ImportError as e:
        raise AIError("Для GGUF через transformers нужен пакет gguf: uv add gguf") from e

    gguf_path = ensure_gguf_model(profile)
    model_dir = str(gguf_path.parent)
    filename = gguf_path.name
    device = resolve_llm_device()
    dtype = torch_dtype_for_device(device)
    logger.info(
        "Loading transformers from local GGUF [%s]: %s (%s, %s)",
        profile.name,
        gguf_path,
        device,
        dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir,
        gguf_file=filename,
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        gguf_file=filename,
        dtype=dtype,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model = model.to(device)
    model.eval()
    return tokenizer, model, f"gguf:{filename}"


def _load_transformers_from_hf(
    torch,
    AutoTokenizer,
    AutoModelForCausalLM,
    profile: ModelProfileConfig,
) -> Tuple[object, object, str]:
    """Загрузка Hugging Face safetensors/bin модели."""
    model_ref = ensure_transformers_model(profile)
    device = resolve_llm_device()
    dtype = torch_dtype_for_device(device)
    logger.info(
        "Loading transformers model [%s]: %s (%s, %s)",
        profile.name,
        model_ref,
        device,
        dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_ref, trust_remote_code=True)
    load_kwargs = {
        "dtype": dtype,
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
    }
    try:
        if device == "cuda":
            model = AutoModelForCausalLM.from_pretrained(
                model_ref,
                device_map="auto",
                **load_kwargs,
            )
        else:
            model = AutoModelForCausalLM.from_pretrained(model_ref, **load_kwargs)
            model = model.to("cpu")
    except Exception:
        model = AutoModelForCausalLM.from_pretrained(model_ref, **load_kwargs)
        model = model.to(device)
    model.eval()
    return tokenizer, model, model_ref


def get_transformers_pipeline(profile: Optional[ModelProfileConfig] = None):
    """Ленивая загрузка модели через transformers (in-process)."""
    cfg = _profile_key(profile)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:
        raise AIError(
            "Нужны пакеты transformers и torch. Выполните: uv add transformers torch"
        ) from e

    prefer_gguf = resolve_gguf_path(cfg).exists() or bool(cfg.llama_model_path)
    cache_key = cfg.cache_key

    with _tf_lock:
        if (
            cache_key in _tf_models
            and cache_key in _tf_tokenizers
            and _tf_model_ids.get(cache_key)
        ):
            return _tf_tokenizers[cache_key], _tf_models[cache_key], torch

        errors: list[str] = []
        if prefer_gguf:
            try:
                tokenizer, model, _ = _load_transformers_from_gguf(
                    torch, AutoTokenizer, AutoModelForCausalLM, cfg
                )
                _tf_tokenizers[cache_key] = tokenizer
                _tf_models[cache_key] = model
                _tf_model_ids[cache_key] = cache_key
                return tokenizer, model, torch
            except Exception as e:
                logger.warning("GGUF via transformers failed [%s]: %s", cfg.name, e)
                errors.append(f"gguf: {e}")

        try:
            tokenizer, model, model_ref = _load_transformers_from_hf(
                torch, AutoTokenizer, AutoModelForCausalLM, cfg
            )
            _tf_tokenizers[cache_key] = tokenizer
            _tf_models[cache_key] = model
            _tf_model_ids[cache_key] = model_ref
            return tokenizer, model, torch
        except Exception as e:
            errors.append(f"hf: {e}")
            raise AIError(
                f"Не удалось загрузить модель transformers [{cfg.name}]. "
                + "; ".join(errors)
            ) from e
