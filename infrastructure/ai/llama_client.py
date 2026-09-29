from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from core.config import settings
from core.exceptions import AIError
from infrastructure.ai.model_manager import (
    ensure_gguf_model,
    get_llama_cpp_model,
    get_transformers_pipeline,
    resolve_gguf_path,
)
from infrastructure.ai.device_utils import cuda_available, device_info, resolve_llm_device
from infrastructure.ai.model_config import (
    ProfileName,
    profile_with_override,
    resolve_model_profile,
    sql_uses_separate_model,
)

logger = logging.getLogger(__name__)


class LocalLLMClient:
    """
    In-process LLM без внешних серверов:
    1) llama-cpp-python + GGUF (если пакет доступен)
    2) transformers + Hugging Face модель
    """

    def __init__(
        self,
        profile: ProfileName = "main",
        *,
        llama_model_path: Optional[str] = None,
    ) -> None:
        self.profile_name = profile
        self._profile = profile_with_override(profile, llama_model_path=llama_model_path)
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.temperature = settings.LLM_TEMPERATURE
        self._backend: Optional[str] = None
        self._model_name: Optional[str] = None

    def _preferred_backend(self) -> str:
        raw = (settings.LLM_BACKEND or "auto").strip().lower()
        if raw in {"llama_cpp", "llama-cpp", "gguf"}:
            return "llama_cpp"
        if raw in {"transformers", "hf", "huggingface"}:
            return "transformers"
        return "auto"

    def _detect_backend(self) -> str:
        preferred = self._preferred_backend()
        if preferred == "llama_cpp":
            return "llama_cpp"
        if preferred == "transformers":
            return "transformers"

        # auto: CUDA → transformers; CPU → llama_cpp (быстрее для GGUF)
        if cuda_available() and resolve_llm_device() == "cuda":
            try:
                import transformers  # noqa: F401
                import torch  # noqa: F401

                logger.info("CUDA доступна — backend transformers")
                return "transformers"
            except ImportError:
                pass

        try:
            import llama_cpp  # noqa: F401

            return "llama_cpp"
        except ImportError:
            pass
        try:
            import transformers  # noqa: F401
            import torch  # noqa: F401

            logger.info("llama-cpp-python unavailable, using transformers")
            return "transformers"
        except ImportError as e:
            raise AIError(
                "Нет доступного LLM-бэкенда. Установите transformers+torch "
                "или llama-cpp-python (на Windows — с Build Tools)."
            ) from e

    async def ensure_backend(self) -> Dict[str, str]:
        backend = self._detect_backend()
        if backend == "llama_cpp":
            path = await asyncio.to_thread(ensure_gguf_model, self._profile)
            await asyncio.to_thread(get_llama_cpp_model, self._profile)
            self._backend = "llama_cpp"
            self._model_name = path.name
            return {"backend": "llama_cpp", "model": path.name, "profile": self.profile_name}

        await asyncio.to_thread(get_transformers_pipeline, self._profile)
        self._backend = "transformers"
        gguf = resolve_gguf_path(self._profile)
        self._model_name = (
            f"gguf:{gguf.name}"
            if gguf.exists()
            else self._profile.transformers_model_id
        )
        return {
            "backend": "transformers",
            "model": self._model_name,
            "profile": self.profile_name,
        }

    def _repetition_penalty(self) -> float:
        return float(getattr(settings, "LLM_REPETITION_PENALTY", 1.18) or 1.18)

    def _chat_llama_cpp(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        llm = get_llama_cpp_model(self._profile)
        repeat = self._repetition_penalty()
        try:
            result = llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                repeat_penalty=repeat,
            )
        except Exception as e:
            raise AIError(f"llama-cpp generation failed: {e}") from e

        choices = result.get("choices") or []
        if not choices:
            raise AIError("llama-cpp вернул пустой ответ")
        message = choices[0].get("message") or {}
        content = message.get("content") or choices[0].get("text")
        if not content:
            raise AIError("llama-cpp вернул ответ без текста")
        from infrastructure.ai.text_utils import dedupe_llm_output

        return dedupe_llm_output(str(content).strip())

    def _chat_transformers(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        tokenizer, model, torch = get_transformers_pipeline(self._profile)
        try:
            if hasattr(tokenizer, "apply_chat_template"):
                prompt = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            else:
                parts = []
                for m in messages:
                    parts.append(f"{m.get('role', 'user').upper()}: {m.get('content', '')}")
                parts.append("ASSISTANT:")
                prompt = "\n".join(parts)

            inputs = tokenizer(prompt, return_tensors="pt")
            # ограничим длину контекста
            max_input = min(settings.LLAMA_CONTEXT_SIZE, getattr(tokenizer, "model_max_length", 4096) or 4096)
            if inputs["input_ids"].shape[-1] > max_input - max_tokens:
                inputs["input_ids"] = inputs["input_ids"][:, -(max_input - max_tokens) :]
                if "attention_mask" in inputs:
                    inputs["attention_mask"] = inputs["attention_mask"][
                        :, -(max_input - max_tokens) :
                    ]

            device = getattr(model, "device", None)
            if device is None:
                try:
                    device = next(model.parameters()).device
                except StopIteration:
                    device = torch.device(resolve_llm_device())
            inputs = {k: v.to(device) for k, v in inputs.items()}

            use_sample = temperature > 0.25
            gen_kwargs: Dict[str, Any] = {
                "max_new_tokens": max_tokens,
                "do_sample": use_sample,
                "pad_token_id": tokenizer.eos_token_id,
                "eos_token_id": tokenizer.eos_token_id,
                "repetition_penalty": self._repetition_penalty(),
                "no_repeat_ngram_size": 4,
            }
            if use_sample:
                gen_kwargs["temperature"] = max(temperature, 0.01)
                gen_kwargs["top_p"] = 0.88
            else:
                gen_kwargs["temperature"] = 1.0

            with torch.inference_mode():
                output = model.generate(**inputs, **gen_kwargs)

            new_tokens = output[0][inputs["input_ids"].shape[-1] :]
            text = tokenizer.decode(new_tokens, skip_special_tokens=True)
            from infrastructure.ai.text_utils import dedupe_llm_output

            return dedupe_llm_output(text.strip())
        except Exception as e:
            raise AIError(f"transformers generation failed: {e}") from e

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        info = await self.ensure_backend()
        backend = info["backend"]
        n_tokens = self.max_tokens if max_tokens is None else max_tokens
        temp = self.temperature if temperature is None else temperature

        if backend == "llama_cpp":
            return await asyncio.to_thread(
                self._chat_llama_cpp,
                messages,
                max_tokens=n_tokens,
                temperature=temp,
            )

        return await asyncio.to_thread(
            self._chat_transformers,
            messages,
            max_tokens=n_tokens,
            temperature=temp,
        )

    async def generate_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(
            messages, max_tokens=max_tokens, temperature=temperature
        )

    def ensure_backend_sync(self) -> Dict[str, str]:
        """Синхронная инициализация бэкенда (для worker-thread без asyncio.run)."""
        backend = self._detect_backend()
        if backend == "llama_cpp":
            path = ensure_gguf_model(self._profile)
            get_llama_cpp_model(self._profile)
            self._backend = "llama_cpp"
            self._model_name = path.name
            return {"backend": "llama_cpp", "model": path.name, "profile": self.profile_name}

        gguf = resolve_gguf_path(self._profile)
        get_transformers_pipeline(self._profile)
        self._backend = "transformers"
        self._model_name = (
            f"gguf:{gguf.name}"
            if gguf.exists()
            else self._profile.transformers_model_id
        )
        return {
            "backend": "transformers",
            "model": self._model_name,
            "profile": self.profile_name,
        }

    def generate_text_sync(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Синхронная генерация текста в worker-thread."""
        info = self.ensure_backend_sync()
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        n_tokens = self.max_tokens if max_tokens is None else max_tokens
        temp = self.temperature if temperature is None else temperature
        if info["backend"] == "llama_cpp":
            return self._chat_llama_cpp(
                messages, max_tokens=n_tokens, temperature=temp
            )
        return self._chat_transformers(
            messages, max_tokens=n_tokens, temperature=temp
        )

    async def health(self) -> Dict[str, Any]:
        gguf_path = resolve_gguf_path(self._profile)
        gguf_exists = gguf_path.exists()
        backend = self._detect_backend()
        llama_cpp_ok = False
        try:
            import llama_cpp  # noqa: F401

            llama_cpp_ok = True
        except ImportError:
            pass

        transformers_ok = False
        try:
            import transformers  # noqa: F401
            import torch  # noqa: F401

            transformers_ok = True
        except ImportError:
            pass

        ok = (backend == "llama_cpp" and llama_cpp_ok) or (
            backend == "transformers" and transformers_ok
        )
        model = (
            gguf_path.name
            if backend == "llama_cpp"
            else (
                f"gguf:{gguf_path.name}"
                if gguf_exists
                else self._profile.transformers_model_id
            )
        )
        payload: Dict[str, Any] = {
            "ok": ok,
            "backend": backend,
            "model": model,
            "profile": self.profile_name,
            "llama_model_path": self._profile.llama_model_path,
            "transformers_model_id": self._profile.transformers_model_id,
            "device": device_info().get("llm_device"),
            "cuda_available": device_info().get("cuda_available"),
            "cuda_device_name": device_info().get("cuda_device_name"),
            "gguf_cached": gguf_exists,
            "gguf_file": self._profile.llama_gguf_file,
            "llama_cpp_available": llama_cpp_ok,
            "transformers_available": transformers_ok,
            "message": (
                "In-process LLM готов (без внешних серверов)"
                if ok
                else "Установите llama-cpp-python или transformers+torch(+gguf)"
            ),
        }
        if self.profile_name == "main":
            sql_profile = resolve_model_profile("sql")
            payload["sql_model"] = {
                "separate": sql_uses_separate_model(),
                "llama_model_path": sql_profile.llama_model_path,
                "transformers_model_id": sql_profile.transformers_model_id,
                "uses_main_fallback": not sql_uses_separate_model(),
            }
        return payload


LlamaClient = LocalLLMClient
