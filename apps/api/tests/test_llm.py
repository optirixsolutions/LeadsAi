"""Model layer against real endpoints. There are no stubs: failures are real failures.

Tests marked `needs_ollama` call a real local model and skip when Ollama is not running
(as in CI, where no GPU or model is available).
"""

import os
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from app.agents.evaluation import tasks
from app.agents.llm import Capability, LLMError, ModelConfig, ModelRegistry, Usage, estimate_cost

MODEL = os.environ.get("SALESIQ_TEST_MODEL", "qwen2.5-7b")


def _closed_port() -> int:
    """A port with nothing listening: connecting fails for real."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _registry(tmp_path: Path, **overrides: Any) -> ModelRegistry:
    """Registry with one dead endpoint plus the real Ollama endpoint."""
    config = {
        "providers": {
            "dead": {"base_url": f"http://127.0.0.1:{_closed_port()}/v1"},
            "ollama": {"base_url": "http://127.0.0.1:11434/v1"},
            "needs_key": {
                "base_url": "http://127.0.0.1:1/v1",
                "api_key_env": "SALESIQ_TEST_ABSENT_KEY",
            },
        },
        "models": {
            "dead-model": {
                "provider": "dead",
                "model": "x",
                "capabilities": ["chat", "structured_output"],
                "max_retries": 1,
                "timeout_s": 2,
                **overrides,
            },
            "real": {
                "provider": "ollama",
                "model": "qwen2.5:latest",
                "capabilities": ["chat", "structured_output"],
            },
            "missing": {
                "provider": "ollama",
                "model": "no-such-model:latest",
                "capabilities": ["chat", "structured_output"],
            },
            "embed-only": {"provider": "ollama", "model": "x", "capabilities": ["embeddings"]},
            "keyed": {"provider": "needs_key", "model": "x", "capabilities": ["chat"]},
        },
    }
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return ModelRegistry(path)


def _ollama_up() -> bool:
    try:
        return any(s.key == MODEL and s.available for s in ModelRegistry().status())
    except Exception:
        return False


needs_ollama = pytest.mark.skipif(not _ollama_up(), reason=f"Ollama model {MODEL} is not running")


def test_shipped_registry_is_valid_and_has_no_mock_or_cloud_models() -> None:
    registry = ModelRegistry()
    for key, model in registry.models.items():
        assert "mock" not in key and "mock" not in model.model
        assert not model.model.endswith("-cloud"), "remote models must not pose as local"
    for route, key in registry.routes.items():
        assert key in registry.models, route
    assert Capability.embeddings in registry.model(registry.routes["embeddings"]).capabilities


def test_unknown_fallback_is_rejected_at_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown models"):
        _registry(tmp_path, fallback=["nope"])


def test_dead_endpoint_retries_then_reports_unavailable(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(LLMError) as info:
        registry.chat("dead-model", [{"role": "user", "content": "hi"}])
    # A closed port refuses on Linux; Windows retries until the connect timeout.
    assert info.value.category in ("unavailable", "timeout") and info.value.transient
    assert info.value.details["attempts"] == "2", "one retry after the first attempt"


def test_missing_credentials_are_a_clear_error_and_make_no_request(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(LLMError) as info:
        registry.chat("keyed", [{"role": "user", "content": "hi"}])
    assert info.value.category == "unauthorized"
    assert "SALESIQ_TEST_ABSENT_KEY" in str(info.value)


def test_capability_is_checked_before_calling(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(LLMError) as info:
        registry.chat("embed-only", [{"role": "user", "content": "hi"}])
    assert info.value.category == "unsupported"
    with pytest.raises(LLMError) as info:
        registry.embed("real", ["hi"])
    assert info.value.category == "unsupported"


def test_status_reports_dead_and_keyless_providers(tmp_path: Path) -> None:
    status = {s.key: s for s in _registry(tmp_path).status()}
    assert not status["dead-model"].available
    assert not status["keyed"].available and "not set" in str(status["keyed"].reason)


def test_cost_estimate_never_pretends_unknown_is_free() -> None:
    priced = ModelConfig(
        key="a",
        provider="p",
        model="m",
        capabilities=frozenset(),
        price_input_per_mtok=1.0,
        price_output_per_mtok=2.0,
    )
    unpriced = ModelConfig(key="b", provider="p", model="m", capabilities=frozenset())
    assert estimate_cost(priced, Usage(1_000_000, 500_000)) == 2.0
    assert estimate_cost(unpriced, Usage(10, 10)) is None
    assert estimate_cost(priced, Usage(None, 10)) is None


# --- real model calls -------------------------------------------------------------------


class _Fact(BaseModel):
    city: str


@needs_ollama
def test_real_structured_output_validates_against_schema() -> None:
    registry = ModelRegistry()
    parsed, result = registry.structured(
        MODEL,
        [{"role": "user", "content": "Acme is headquartered in Leeds. What city?"}],
        _Fact,
        max_tokens=60,
    )
    assert parsed.city.lower() == "leeds"
    assert result.usage.output_tokens and result.latency_ms > 0
    assert result.fallback_from == ()


@needs_ollama
def test_output_limit_is_reported_as_truncation_not_bad_json() -> None:
    with pytest.raises(LLMError) as info:
        ModelRegistry().structured(
            MODEL,
            [{"role": "user", "content": "Acme is headquartered in Leeds. What city?"}],
            _Fact,
            max_tokens=2,
        )
    assert info.value.category == "truncated"
    assert not info.value.transient, "the same limit would cut off a retry too"


@needs_ollama
def test_missing_model_gives_clear_error(tmp_path: Path) -> None:
    with pytest.raises(LLMError) as info:
        _registry(tmp_path).chat("missing", [{"role": "user", "content": "hi"}])
    assert info.value.category == "model_not_found"
    assert "no-such-model" in str(info.value)


@needs_ollama
def test_fallback_is_used_and_reported_not_hidden(tmp_path: Path) -> None:
    registry = _registry(tmp_path, fallback=["real"], max_retries=0)
    result = registry.chat("dead-model", [{"role": "user", "content": "Say OK."}], max_tokens=10)
    assert result.model_key == "real"
    assert result.fallback_from == ("dead-model",), "callers must see the substitution"


@needs_ollama
def test_real_extraction_ignores_distractor_company() -> None:
    record = {
        "structured": {"company": "Brantwick Cloud"},
        "note": (
            "Brantwick Cloud has a team of 140. "
            "A larger rival, Velor Networks, has over 31000 staff."
        ),
    }
    parsed, _ = ModelRegistry().structured(
        MODEL, tasks.extraction_messages(record), tasks.ExtractionOut, max_tokens=200
    )
    assert parsed.employee_count == 140
    assert parsed.funding_stage is None, "facts that are not stated must stay null"
