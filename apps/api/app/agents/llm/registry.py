"""Model registry and router: capability checks, retries, concurrency limits, fallback, cost."""

import os
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.agents.llm.client import OpenAICompatibleClient
from app.agents.llm.types import (
    Capability,
    ChatMessage,
    ChatResult,
    EmbeddingResult,
    LLMError,
    ModelConfig,
    ModelStatus,
    ProviderConfig,
    Usage,
    not_found,
    schema_invalid,
    unsupported,
)

DEFAULT_CONFIG = Path(__file__).with_name("models.yaml")
_BASE_URL_ENV = {"ollama": "SALESIQ_OLLAMA_BASE_URL", "huggingface": "SALESIQ_HF_BASE_URL"}
T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


def estimate_cost(model: ModelConfig, usage: Usage) -> float | None:
    """Estimated USD, or None when the price or the token counts are unknown."""
    p_in, p_out = model.price_input_per_mtok, model.price_output_per_mtok
    if p_in is None or p_out is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    return (usage.input_tokens * p_in + usage.output_tokens * p_out) / 1_000_000


class ModelRegistry:
    def __init__(self, config_path: Path = DEFAULT_CONFIG) -> None:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.providers = {
            k: ProviderConfig(
                key=k,
                base_url=os.environ.get(_BASE_URL_ENV.get(k, ""), v["base_url"]),
                api_key_env=v.get("api_key_env"),
            )
            for k, v in raw["providers"].items()
        }
        self.models = {k: ModelConfig(key=k, **v) for k, v in raw["models"].items()}
        self.routes: dict[str, str] = raw.get("routes", {})
        for m in self.models.values():
            if m.provider not in self.providers:
                raise ValueError(f"Model '{m.key}' uses unknown provider '{m.provider}'")
            missing = [f for f in m.fallback if f not in self.models]
            if missing:
                raise ValueError(f"Model '{m.key}' falls back to unknown models: {missing}")
        self._clients = {k: OpenAICompatibleClient(p) for k, p in self.providers.items()}
        self._limits = {
            k: threading.BoundedSemaphore(m.concurrency) for k, m in self.models.items()
        }

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

    def model(self, key: str) -> ModelConfig:
        try:
            return self.models[key]
        except KeyError as exc:
            raise not_found(f"Unknown model key '{key}'") from exc

    def status(self) -> list[ModelStatus]:
        """Report what can actually run right now, by asking each provider."""
        served: dict[str, set[str] | str] = {}
        for key, client in self._clients.items():
            if not client.has_credentials:
                served[key] = f"{client.config.api_key_env} is not set"
                continue
            try:
                served[key] = client.list_models()
            except LLMError as exc:
                served[key] = exc.message
        out = []
        for m in self.models.values():
            s = served[m.provider]
            if isinstance(s, str):
                out.append(ModelStatus(m.key, False, s))
            elif m.model not in s:
                out.append(ModelStatus(m.key, False, f"'{m.model}' is not on {m.provider}"))
            else:
                out.append(ModelStatus(m.key, True))
        return out

    # --- calls ---------------------------------------------------------------------------

    def _with_retries(self, m: ModelConfig, call: Callable[[], R]) -> tuple[R, int]:
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._limits[m.key]:
                    return call(), attempts
            except LLMError as exc:
                if not exc.transient or attempts > m.max_retries:
                    exc.details["attempts"] = str(attempts)
                    raise
                time.sleep(min(2 ** (attempts - 1), 8))

    def chat(
        self,
        key: str,
        messages: list[ChatMessage],
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ChatResult:
        """Call a model, falling back only on transient failures, and report what happened."""
        primary = self.model(key)
        needed = Capability.structured_output if schema else Capability.chat
        failed: list[str] = []
        last: LLMError | None = None
        for candidate in (key, *primary.fallback):
            m = self.model(candidate)
            if needed not in m.capabilities:
                last = unsupported(f"Model '{m.key}' does not support {needed.value}")
                continue
            call = partial(
                self._clients[m.provider].chat,
                m.model,
                messages,
                json_schema=schema.model_json_schema() if schema else None,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=m.timeout_s,
                reasoning_effort=m.reasoning_effort,
            )
            try:
                (text, usage, latency), attempts = self._with_retries(m, call)
            except LLMError as exc:
                last = exc
                if not exc.transient and exc.category not in ("model_not_found", "unauthorized"):
                    raise
                failed.append(m.key)
                continue
            return ChatResult(text, usage, latency, m.key, attempts, tuple(failed))
        assert last is not None
        raise last

    def structured(
        self,
        key: str,
        messages: list[ChatMessage],
        schema: type[T],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> tuple[T, ChatResult]:
        """Schema-validated output. Invalid output is an error, never a guess."""
        result = self.chat(
            key, messages, schema=schema, temperature=temperature, max_tokens=max_tokens
        )
        try:
            return schema.model_validate_json(result.text), result
        except ValidationError as exc:
            error = schema_invalid(f"Model '{result.model_key}' output failed validation")
            error.details["errors"] = str(exc.error_count())
            error.details["raw"] = result.text[:2000]
            raise error from exc

    def embed(self, key: str, inputs: list[str]) -> EmbeddingResult:
        m = self.model(key)
        if Capability.embeddings not in m.capabilities:
            raise unsupported(f"Model '{m.key}' does not support embeddings")
        call = partial(self._clients[m.provider].embed, m.model, inputs, timeout=m.timeout_s)
        (vectors, usage, latency), _ = self._with_retries(m, call)
        return EmbeddingResult(vectors, usage, latency, m.key)
