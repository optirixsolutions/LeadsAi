"""Provider-independent LLM types and errors."""

import enum
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class Capability(enum.StrEnum):
    chat = "chat"
    structured_output = "structured_output"
    tool_calling = "tool_calling"
    embeddings = "embeddings"


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelConfig(BaseModel):
    """One callable model. Prices are per million tokens; None means unknown, not free."""

    key: str
    provider: str
    model: str
    capabilities: frozenset[Capability]
    context_tokens: int | None = None
    price_input_per_mtok: float | None = None
    price_output_per_mtok: float | None = None
    timeout_s: float = Field(default=120, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    concurrency: int = Field(default=1, ge=1, le=64)
    # Tried in order on transient failure. Never used to hide a security or validation error.
    fallback: tuple[str, ...] = ()
    source: str | None = None
    # Sent as-is when set. "none" stops thinking models spending the output budget on reasoning.
    reasoning_effort: str | None = None


class ProviderConfig(BaseModel):
    """An OpenAI-compatible endpoint. URLs and secrets come from server config only."""

    key: str
    base_url: str
    api_key_env: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ChatResult:
    text: str
    usage: Usage
    latency_ms: float
    model_key: str
    attempts: int = 1
    # Models that failed before this one answered; empty when the primary succeeded.
    fallback_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    usage: Usage
    latency_ms: float
    model_key: str


@dataclass(frozen=True)
class ModelStatus:
    key: str
    available: bool
    reason: str | None = None


@dataclass(eq=False)
class LLMError(Exception):
    """Base model failure. `category` is recorded in evaluations as the failure category."""

    message: str
    category: str = "error"
    transient: bool = False
    details: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def unavailable(message: str) -> LLMError:
    return LLMError(message, category="unavailable", transient=True)


def timed_out(message: str) -> LLMError:
    return LLMError(message, category="timeout", transient=True)


def not_found(message: str) -> LLMError:
    return LLMError(message, category="model_not_found")


def resources(message: str) -> LLMError:
    """The model cannot run here (not enough memory). Clear error, no silent downgrade."""
    return LLMError(message, category="insufficient_resources")


def unauthorized(message: str) -> LLMError:
    return LLMError(message, category="unauthorized")


def bad_response(message: str) -> LLMError:
    return LLMError(message, category="bad_response")


def schema_invalid(message: str) -> LLMError:
    return LLMError(message, category="schema_invalid")


def truncated(message: str) -> LLMError:
    """The output limit ended generation before a usable answer. Not the same as bad output."""
    return LLMError(message, category="truncated")


def unsupported(message: str) -> LLMError:
    return LLMError(message, category="unsupported")
