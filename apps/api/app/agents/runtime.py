"""The bounded agent loop. Model turns, tool calls, and tokens all have hard limits.

Tool calls go through a real MCP client and server, in memory. The server is built for this one
run with a fixed identity, so the model cannot change who it acts as, and it is offered only its
role's tools. Asking for another tool is refused by the server and logged.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp import Client
from sqlalchemy.orm import Session, sessionmaker

from app.agents.evaluation.tasks import OutreachOut, SynthesisOut, _untrusted
from app.agents.llm import ChatResult, LLMError, ModelRegistry, ToolRequest
from app.agents.roles import AgentDefinition
from app.mcp.registry import Identity, ToolResult
from app.mcp.server import build_server
from app.mcp.tools import CATALOG

MAX_RESULT_CHARS = 4000
MAX_SOURCES_IN_RESULT = 2800
MAX_SOURCE_CHARS = 1200
MAX_ARGS_CHARS = 2000
_SAFE_TEXT = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
FINAL_INSTRUCTIONS = (
    "Stop calling tools and write your final answer now, from the tool results above. Every claim "
    "must cite the source labels it relies on, such as S1. Use only what the sources say. List "
    "what is still unknown."
)
EMAIL_INSTRUCTIONS = (
    "Stop calling tools and write the email now, from the tool results above. Keep the body under "
    "120 words, with no signature and no opt-out line, which are added later. In evidence_ids, "
    "list the source labels you used, such as S1. It is a draft and will not be sent automatically."
)


@dataclass
class AgentResult:
    output: SynthesisOut | None
    # An email-writing agent answers here instead.
    # label -> text, exactly as shown to the model. The review checks claims against these.
    sources: dict[str, str]
    source_ids: dict[str, str]
    stop_reason: str
    model_turns: int = 0
    tool_calls: int = 0
    refused_calls: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    served_by: str | None = None
    error: LLMError | None = None
    email: OutreachOut | None = None


def tool_schemas(tools: frozenset[str]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_model.model_json_schema(),
            },
        }
        for spec in CATALOG.values()
        if spec.name in tools
    ]


class _Sources:
    """Short labels, because small models copy long IDs badly. Only text the model was actually
    shown gets a label, as that is what its claims are checked against."""

    def __init__(self) -> None:
        self.by_label: dict[str, str] = {}
        self.ids: dict[str, str] = {}
        self._labels: dict[str, str] = {}

    def add(self, sources: dict[str, str], budget: int) -> list[str]:
        lines: list[str] = []
        used = 0
        for source_id, source_text in sources.items():
            flat = " ".join(source_text.split())[:MAX_SOURCE_CHARS]
            if used + len(flat) > budget:
                break
            used += len(flat)
            label = self._labels.get(source_id)
            if label is None:
                label = f"S{len(self._labels) + 1}"
                self._labels[source_id] = label
                self.by_label[label] = flat
                self.ids[label] = source_id
            lines.append(f"[{label}] {flat}")
        return lines

    def normalize(self, output: SynthesisOut) -> SynthesisOut:
        """A model that copied a real ID still gets credit for citing the right thing."""
        for claim in output.claims:
            claim.evidence_ids = [self._labels.get(i, i).strip("[]") for i in claim.evidence_ids]
        return output

    def normalize_email(self, output: OutreachOut) -> OutreachOut:
        output.evidence_ids = [self._labels.get(i, i).strip("[]") for i in output.evidence_ids]
        return output


def _render(result: ToolResult, sources: _Sources) -> str:
    """Everything a tool returns is marked as data, refusals included, and fits a hard cap."""
    if not result.ok:
        return _untrusted(f"Refused or failed: {result.error_category}. {result.message}")
    lines = sources.add(result.sources, MAX_SOURCES_IN_RESULT)
    cite = "\nSources you may cite:\n" + "\n".join(lines) if lines else ""
    body = json.dumps(result.output, default=str)
    return _untrusted(body[: max(0, MAX_RESULT_CHARS - len(cite))] + cite)


def _clean(request: ToolRequest, index: int) -> ToolRequest:
    """Whatever a model sent goes back into its own prompt, so it has to be small and plain."""
    arguments = request.arguments if len(json.dumps(request.arguments)) <= MAX_ARGS_CHARS else {}
    return ToolRequest(
        id=request.id if _SAFE_TEXT.fullmatch(request.id) else f"call-{index}",
        name=request.name if _SAFE_TEXT.fullmatch(request.name) else "invalid_tool",
        arguments=arguments,
    )


def _first_error(group: BaseExceptionGroup[Any]) -> BaseException:
    first = group.exceptions[0]
    return _first_error(first) if isinstance(first, BaseExceptionGroup) else first


async def run_agent(
    definition: AgentDefinition,
    identity: Identity,
    task: str,
    registry: ModelRegistry,
    model_key: str,
    session_factory: sessionmaker[Session],
    *,
    deadline_s: float = 300.0,
    check: Callable[[], None] | None = None,
) -> AgentResult:
    """Model failures are returned in `error`, with what was used so far. `check` may raise to
    stop the run, such as when someone cancels it, and is called between model turns."""
    started = time.monotonic()
    sources = _Sources()
    results: list[ToolResult] = []
    server = build_server(lambda: identity, session_factory, on_result=results.append)
    outcome = AgentResult(None, {}, {}, "finished")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": definition.instructions},
        {"role": "user", "content": task},
    ]
    schemas = tool_schemas(definition.tools)

    def account(reply: ChatResult) -> None:
        # A server that reports no usage is estimated, so that the budget still applies.
        sent = sum(len(str(m.get("content") or "")) for m in messages) // 4
        outcome.model_turns += 1
        outcome.input_tokens += reply.usage.input_tokens or sent
        outcome.output_tokens += reply.usage.output_tokens or len(reply.text) // 4
        outcome.served_by = reply.model_key

    def over_budget() -> str | None:
        if outcome.input_tokens + outcome.output_tokens >= definition.max_total_tokens:
            return "token_limit"
        return "time_limit" if time.monotonic() - started > deadline_s else None

    try:
        async with Client(server) as client:
            while True:
                if check:
                    await asyncio.to_thread(check)
                if outcome.model_turns >= definition.max_model_turns:
                    outcome.stop_reason = "turn_limit"
                    break
                if reason := over_budget():
                    outcome.stop_reason = reason
                    break
                remaining = max(1.0, deadline_s - (time.monotonic() - started))
                try:
                    reply, requests = await asyncio.to_thread(
                        registry.chat_with_tools, model_key, messages, schemas, timeout_s=remaining
                    )
                except LLMError as exc:
                    outcome.error = exc
                    break
                account(reply)
                if not requests:
                    break
                left = definition.max_tool_calls - outcome.tool_calls
                if len(requests) > left:
                    outcome.stop_reason = "tool_limit"
                requests = [_clean(r, i) for i, r in enumerate(requests[: max(left, 0)])]
                if requests:
                    messages.append(_assistant_turn(reply.text[:MAX_ARGS_CHARS], requests))
                for request in requests:
                    outcome.tool_calls += 1
                    text = await _call(client, request, results, sources, outcome)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": request.id,
                            "name": request.name,
                            "content": text,
                        }
                    )
                if outcome.stop_reason == "tool_limit":
                    break
    except BaseExceptionGroup as group:
        # The client's task group wraps anything raised inside it.
        raise _first_error(group) from None

    outcome.sources = sources.by_label
    outcome.source_ids = sources.ids
    if outcome.error is not None:
        return outcome
    if outcome.stop_reason in ("token_limit", "time_limit"):
        return outcome  # Asking for one more answer would only spend more past the limit.
    if check:
        await asyncio.to_thread(check)
    if definition.writes_email:
        messages.append({"role": "user", "content": EMAIL_INSTRUCTIONS})
        try:
            email, reply = await asyncio.to_thread(
                registry.structured, model_key, messages, OutreachOut
            )
        except LLMError as exc:
            outcome.error = exc
            return outcome
        account(reply)
        outcome.email = sources.normalize_email(email)
        return outcome
    messages.append({"role": "user", "content": FINAL_INSTRUCTIONS})
    try:
        parsed, reply = await asyncio.to_thread(
            registry.structured, model_key, messages, SynthesisOut
        )
    except LLMError as exc:
        outcome.error = exc
        return outcome
    account(reply)
    outcome.output = sources.normalize(parsed)
    return outcome


def _assistant_turn(text: str, requests: list[ToolRequest]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "id": r.id,
                "type": "function",
                "function": {"name": r.name, "arguments": json.dumps(r.arguments)},
            }
            for r in requests
        ],
    }


async def _call(
    client: Client,
    request: ToolRequest,
    results: list[ToolResult],
    sources: _Sources,
    outcome: AgentResult,
) -> str:
    before = len(results)
    called = await client.call_tool(request.name, request.arguments)
    if len(results) == before:
        # The tool hit its time limit, so there is no result to read.
        outcome.refused_calls.append(f"{request.name}: timeout")
        return _untrusted("Refused or failed: this tool took too long.")
    result = results[-1]
    if not result.ok:
        outcome.refused_calls.append(f"{request.name}: {result.error_category}")
    del called
    return _render(result, sources)


__all__ = ["AgentResult", "LLMError", "run_agent", "tool_schemas"]
