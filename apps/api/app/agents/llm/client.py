"""HTTP client for OpenAI-compatible endpoints: Ollama, Hugging Face router, vLLM, and others."""

import os
import re
import time
from typing import Any

import httpx

from app.agents.llm.types import (
    ChatMessage,
    ProviderConfig,
    Usage,
    bad_response,
    not_found,
    resources,
    timed_out,
    truncated,
    unauthorized,
    unavailable,
)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_MEMORY_HINTS = ("more system memory", "out of memory", "unable to allocate", "failed to allocate")


class OpenAICompatibleClient:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        headers = {}
        if config.api_key_env and (key := os.environ.get(config.api_key_env)):
            headers["authorization"] = f"Bearer {key}"
        self.has_credentials = bool(headers) or config.api_key_env is None
        self._http = httpx.Client(base_url=config.base_url.rstrip("/") + "/", headers=headers)

    def close(self) -> None:
        self._http.close()

    def _post(
        self, path: str, body: dict[str, Any], *, model: str, timeout: float
    ) -> dict[str, Any]:
        if not self.has_credentials:
            raise unauthorized(f"{self.config.api_key_env} is not set for '{self.config.key}'")
        try:
            r = self._http.post(path, json=body, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise timed_out(f"{self.config.key}: no response within {timeout:g}s") from exc
        except httpx.TransportError as exc:
            raise unavailable(
                f"{self.config.key}: could not connect ({type(exc).__name__})"
            ) from exc
        return self._parse(r, model)

    def _parse(self, r: httpx.Response, model: str) -> dict[str, Any]:
        if r.is_success:
            try:
                data: dict[str, Any] = r.json()
            except ValueError as exc:
                raise bad_response(f"{self.config.key}: response was not JSON") from exc
            return data
        detail = r.text[:300]
        lowered = detail.lower()
        if any(hint in lowered for hint in _MEMORY_HINTS):
            raise resources(f"Model '{model}' does not fit in available memory: {detail}")
        if r.status_code == 404:
            raise not_found(f"Model '{model}' is not available on '{self.config.key}': {detail}")
        if r.status_code in (401, 403):
            raise unauthorized(f"{self.config.key} rejected the credentials ({r.status_code})")
        if r.status_code in (408, 429) or r.status_code >= 500:
            raise unavailable(f"{self.config.key} returned {r.status_code}: {detail}")
        raise bad_response(f"{self.config.key} returned {r.status_code}: {detail}")

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        seed: int | None = 7,
        timeout: float = 120,
        reasoning_effort: str | None = None,
    ) -> tuple[str, Usage, float]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            body["seed"] = seed
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": json_schema},
            }
        start = time.perf_counter()
        data = self._post("chat/completions", body, model=model, timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            choice = data["choices"][0]
            text = _THINK.sub("", choice["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise bad_response(f"{self.config.key}: response had no message content") from exc
        # Cut-off JSON can never validate, and empty text means the budget went on reasoning.
        if choice.get("finish_reason") == "length" and (json_schema is not None or not text):
            error = truncated(f"'{model}' reached the {max_tokens} token limit before finishing")
            error.details["raw"] = text[:2000]
            raise error
        return text, _usage(data), latency_ms

    def embed(
        self, model: str, inputs: list[str], *, timeout: float = 120
    ) -> tuple[list[list[float]], Usage, float]:
        start = time.perf_counter()
        data = self._post(
            "embeddings", {"model": model, "input": inputs}, model=model, timeout=timeout
        )
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            ordered = sorted(data["data"], key=lambda d: d["index"])
            vectors = [d["embedding"] for d in ordered]
        except (KeyError, TypeError) as exc:
            raise bad_response(f"{self.config.key}: response had no embeddings") from exc
        if len(vectors) != len(inputs):
            raise bad_response(f"{self.config.key}: expected {len(inputs)} embeddings")
        return vectors, _usage(data), latency_ms

    def list_models(self, *, timeout: float = 5) -> set[str]:
        try:
            r = self._http.get("models", timeout=timeout)
        except httpx.TimeoutException as exc:
            raise timed_out(f"{self.config.key}: no response within {timeout:g}s") from exc
        except httpx.TransportError as exc:
            raise unavailable(
                f"{self.config.key}: could not connect ({type(exc).__name__})"
            ) from exc
        data = self._parse(r, "*")
        return {str(m.get("id")) for m in data.get("data", [])}


def _usage(data: dict[str, Any]) -> Usage:
    usage = data.get("usage") or {}
    return Usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
