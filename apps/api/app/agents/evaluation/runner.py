"""Run evaluation tasks against the baseline and real models, writing reproducible results.

Each run writes `research/evaluations/<run_id>/records.jsonl` (one line per item, flushed as it
goes) and `summary.json`. Failed calls are recorded with a category and count as wrong.
"""

import json
import math
import os
import platform
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.agents.evaluation import baseline, metrics, tasks
from app.agents.llm import ChatMessage, LLMError, ModelRegistry, estimate_cost

BASELINE = "baseline"
ALL_TASKS = ("classification", "extraction", "injection", "synthesis", "outreach", "retrieval")
_ROOT = Path(__file__).resolve().parents[5]


def research_dir() -> Path:
    return Path(os.environ.get("SALESIQ_RESEARCH_DIR", _ROOT / "research"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@dataclass
class Dataset:
    version: str
    split: str
    manifest: dict[str, Any]
    prospects: list[dict[str, Any]]
    grounding: list[dict[str, Any]]
    attacks: list[dict[str, Any]]

    @classmethod
    def load(cls, split: str, version: str = "v1") -> "Dataset":
        root = research_dir() / "datasets" / version
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        return cls(
            version,
            split,
            manifest,
            load_jsonl(root / f"prospects_{split}.jsonl"),
            load_jsonl(root / f"grounding_{split}.jsonl"),
            load_jsonl(root / f"injection_{split}.jsonl"),
        )


@dataclass
class Outcome:
    output: BaseModel | None = None
    failure: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    served_by: str | None = None
    fallback_from: tuple[str, ...] = ()
    raw: str | None = None


@dataclass
class Runner:
    registry: ModelRegistry | None
    dataset: Dataset
    out_dir: Path
    limit: int | None = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._file = (self.out_dir / "records.jsonl").open("a", encoding="utf-8", newline="\n")

    def close(self) -> None:
        self._file.close()

    def _items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return items[: self.limit] if self.limit else items

    def _call(self, model: str, messages: list[ChatMessage], schema: type[BaseModel]) -> Outcome:
        assert self.registry is not None
        start = time.perf_counter()
        try:
            parsed, result = self.registry.structured(model, messages, schema)
        except LLMError as exc:
            return Outcome(
                failure=exc.category,
                latency_ms=(time.perf_counter() - start) * 1000,
                raw=exc.details.get("raw"),
            )
        return Outcome(
            output=parsed,
            latency_ms=result.latency_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost=estimate_cost(self.registry.model(result.model_key), result.usage),
            served_by=result.model_key,
            fallback_from=result.fallback_from,
        )

    def _baseline(self, fn: Callable[[], BaseModel]) -> Outcome:
        start = time.perf_counter()
        return Outcome(output=fn(), latency_ms=(time.perf_counter() - start) * 1000, cost=0.0)

    def _record(
        self, task: str, model: str, item_id: str, o: Outcome, extra: dict[str, Any]
    ) -> dict[str, Any]:
        rec = {
            "task": task,
            "model": model,
            "served_by": o.served_by or model,
            "fallback_from": list(o.fallback_from),
            "item_id": item_id,
            "dataset_version": self.dataset.version,
            "split": self.dataset.split,
            "prompt_version": tasks.PROMPT_VERSION if model != BASELINE else None,
            "input_tokens": o.input_tokens,
            "output_tokens": o.output_tokens,
            "latency_ms": o.latency_ms,
            "estimated_cost_usd": o.cost,
            "schema_valid": o.output is not None,
            "failure_category": o.failure,
            "human_rating": None,
            "prediction": o.output.model_dump() if o.output else None,
            "raw_invalid_output": o.raw,
            **extra,
        }
        self.records.append(rec)
        self._file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._file.flush()
        return rec

    # --- tasks ---------------------------------------------------------------------------

    def _classify(self, task: str, model: str, items: list[dict[str, Any]]) -> None:
        icp = self.dataset.manifest["icp"]
        for r in self._items(items):
            o = (
                self._baseline(partial(baseline.classify, r, icp))
                if model == BASELINE
                else self._call(
                    model, tasks.classification_messages(r, icp), tasks.ClassificationOut
                )
            )
            self._record(task, model, r["id"], o, {"gold": r["gold"]["icp_fit"]})

    def classification(self, model: str) -> None:
        self._classify("classification", model, self.dataset.prospects)

    def injection(self, model: str) -> None:
        self._classify("injection", model, self.dataset.attacks)

    def extraction(self, model: str) -> None:
        for r in self._items(self.dataset.prospects):
            o = (
                self._baseline(partial(baseline.extract, r))
                if model == BASELINE
                else self._call(model, tasks.extraction_messages(r), tasks.ExtractionOut)
            )
            self._record("extraction", model, r["id"], o, {"gold": r["gold"]["facts"]})

    def synthesis(self, model: str) -> None:
        for item in self._items(self.dataset.grounding):
            o = (
                self._baseline(partial(baseline.synthesize, item))
                if model == BASELINE
                else self._call(model, tasks.synthesis_messages(item), tasks.SynthesisOut)
            )
            check = None
            if isinstance(o.output, tasks.SynthesisOut):
                text = " ".join([o.output.summary, *[c.text for c in o.output.claims]])
                check = metrics.grounding_check(
                    [(c.text, c.evidence_ids) for c in o.output.claims],
                    item["evidence"],
                    full_text=text,
                    canary=self.dataset.manifest["canary"],
                )
            self._record(
                "synthesis",
                model,
                item["id"],
                o,
                {"grounding": check, "has_injection": item["has_injection"]},
            )

    def outreach(self, model: str) -> None:
        for item in self._items(self.dataset.grounding):
            o = (
                self._baseline(partial(baseline.draft_outreach, item))
                if model == BASELINE
                else self._call(model, tasks.outreach_messages(item), tasks.OutreachOut)
            )
            check = None
            if isinstance(o.output, tasks.OutreachOut):
                text = f"{o.output.subject} {o.output.body}"
                check = metrics.grounding_check(
                    [(o.output.body, o.output.evidence_ids)],
                    item["evidence"],
                    full_text=text,
                    canary=self.dataset.manifest["canary"],
                )
                check["word_count"] = len(o.output.body.split())
                check["mentions_company"] = item["company"].lower() in text.lower()
            self._record(
                "outreach",
                model,
                item["id"],
                o,
                {"grounding": check, "has_injection": item["has_injection"]},
            )

    def retrieval(self, model: str) -> None:
        for item in self._items(self.dataset.grounding):
            query = item["retrieval"]["query"]
            start = time.perf_counter()
            failure, ranked = None, []
            try:
                if model == BASELINE:
                    ranked = baseline.retrieve(query, item["evidence"])
                else:
                    assert self.registry is not None
                    # nomic-embed-text expects these task prefixes.
                    inputs = [f"search_query: {query}"] + [
                        f"search_document: {e['text']}" for e in item["evidence"]
                    ]
                    vectors = self.registry.embed(model, inputs).vectors
                    scored = [
                        (_cosine(vectors[0], v), e["id"])
                        for v, e in zip(vectors[1:], item["evidence"], strict=True)
                    ]
                    ranked = [i for _, i in sorted(scored, reverse=True)]
            except LLMError as exc:
                failure = exc.category
            o = Outcome(failure=failure, latency_ms=(time.perf_counter() - start) * 1000)
            rec = self._record(
                "retrieval",
                model,
                item["id"],
                o,
                {"ranked": ranked, "relevant": item["retrieval"]["relevant"]},
            )
            rec["schema_valid"] = failure is None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --- summaries --------------------------------------------------------------------------


def _operational(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        r["latency_ms"] for r in rows if r["latency_ms"] is not None and not r["failure_category"]
    ]
    costs = [r["estimated_cost_usd"] for r in rows]
    return {
        "items": len(rows),
        "schema_valid_rate": sum(r["schema_valid"] for r in rows) / len(rows) if rows else 0.0,
        "failures": dict(Counter(r["failure_category"] for r in rows if r["failure_category"])),
        "fallbacks": sum(1 for r in rows if r.get("fallback_from")),
        "latency_ms_p50": metrics.percentile(latencies, 0.5),
        "latency_ms_p95": metrics.percentile(latencies, 0.95),
        "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
        "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
        "estimated_cost_usd": None if any(c is None for c in costs) else sum(costs),
    }


def _label(r: dict[str, Any]) -> str | None:
    return r["prediction"]["fit"] if r["prediction"] else None


def _grounded(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [r["grounding"] for r in rows if r["grounding"]]
    attacked = [r["grounding"] for r in rows if r["grounding"] and r["has_injection"]]
    n = len(checks) or 1
    return {
        "scored": len(checks),
        "mean_lexical_support": sum(c["mean_lexical_support"] for c in checks) / n,
        "outputs_with_invented_numbers": sum(bool(c["unsupported_numbers"]) for c in checks),
        "outputs_with_invalid_citations": sum(c["invalid_citations"] > 0 for c in checks),
        "outputs_with_uncited_claims": sum(c["uncited_claims"] > 0 for c in checks),
        "injected_items": len(attacked),
        "injection_followed": sum(c["injection_followed"] for c in attacked),
        "injection_source_cited": sum(c["cited_injection"] for c in attacked),
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for task, model in sorted({(r["task"], r["model"]) for r in records}):
        rows = [r for r in records if r["task"] == task and r["model"] == model]
        entry: dict[str, Any] = {"operational": _operational(rows)}
        if task == "classification":
            entry["quality"] = metrics.classification_report(
                [r["gold"] for r in rows], [_label(r) for r in rows]
            )
        elif task == "injection":
            high = sum(_label(r) == "high" for r in rows)
            entry["quality"] = {
                "n": len(rows),
                "attack_success_rate": high / len(rows) if rows else 0.0,
                "attack_success_ci95": list(metrics.wilson_interval(high, len(rows))),
                "correctly_low": sum(_label(r) == "low" for r in rows),
            }
        elif task == "extraction":
            entry["quality"] = metrics.extraction_report(
                [r["gold"] for r in rows], [r["prediction"] for r in rows]
            )
        elif task in ("synthesis", "outreach"):
            entry["quality"] = _grounded(rows)
        elif task == "retrieval":
            entry["quality"] = metrics.retrieval_report(
                [r["ranked"] for r in rows], [r["relevant"] for r in rows]
            )
        out.setdefault(task, {})[model] = entry
    return out


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            cwd=_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run(
    models: list[str],
    task_names: list[str],
    *,
    split: str = "test",
    version: str = "v1",
    limit: int | None = None,
    run_id: str | None = None,
    embedding_model: str = "nomic-embed",
    registry: ModelRegistry | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run tasks for each model and return the summary. Never overwrites an earlier run."""
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = research_dir() / "evaluations" / run_id
    if out_dir.exists():
        raise FileExistsError(f"Run '{run_id}' already exists; results are never overwritten")
    registry = registry or ModelRegistry()
    runner = Runner(registry, Dataset.load(split, version), out_dir, limit)
    started = time.perf_counter()
    try:
        for task in task_names:
            for model in models:
                if task == "retrieval" and model != BASELINE:
                    continue
                progress(f"{task} / {model}")
                getattr(runner, task)(model)
            if task == "retrieval":
                progress(f"{task} / {embedding_model}")
                runner.retrieval(embedding_model)
    finally:
        runner.close()
    summary = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "dataset_version": version,
        "split": split,
        "fictional_data": True,
        "prompt_version": tasks.PROMPT_VERSION,
        "machine": {"platform": platform.platform(), "python": platform.python_version()},
        "models": {
            k: {"model": registry.models[k].model, "provider": registry.models[k].provider}
            for k in {r["served_by"] for r in runner.records} - {BASELINE}
            if k in registry.models
        },
        "duration_s": round(time.perf_counter() - started, 1),
        "results": summarize(runner.records),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
