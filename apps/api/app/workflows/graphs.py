"""The research and lead-intelligence graphs: simple, deterministic, and easy to follow."""

from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.models import WorkflowKind
from app.workflows import nodes
from app.workflows.state import WorkflowState


def _base(owner: str) -> StateGraph[Any, Any, Any, Any]:
    graph: StateGraph[Any, Any, Any, Any] = StateGraph(WorkflowState)
    graph.add_node(
        "validate_request", nodes.traced("validate_request", nodes.validate_request, owner)
    )
    graph.add_node("gather_evidence", nodes.traced("gather_evidence", nodes.gather_evidence, owner))
    graph.add_node(
        "validate_sources", nodes.traced("validate_sources", nodes.validate_sources, owner)
    )
    # The model client already retries transient failures with backoff, and a retry here would
    # multiply that past the run's deadline. After that the run fails and a person can resume it.
    graph.add_node("interpret", nodes.traced("interpret", nodes.interpret(owner), owner))
    graph.add_node("finalize", nodes.traced("finalize", nodes.finalize, owner))
    graph.add_edge(START, "validate_request")
    return graph


def _build_research(owner: str) -> StateGraph[Any, Any, Any, Any]:
    graph = _base(owner)
    graph.add_edge("validate_request", "gather_evidence")
    graph.add_edge("gather_evidence", "validate_sources")
    graph.add_edge("validate_sources", "interpret")
    graph.add_edge("interpret", "finalize")
    graph.add_edge("finalize", END)
    return graph


def _after_review(state: WorkflowState) -> Literal["request_approval", "finalize"]:
    return "request_approval" if state.get("proposal") else "finalize"


def _build_lead_intelligence(owner: str) -> StateGraph[Any, Any, Any, Any]:
    graph = _base(owner)
    graph.add_node("load_context", nodes.traced("load_context", nodes.load_context, owner))
    graph.add_node("score_lead", nodes.traced("score_lead", nodes.score_lead, owner))
    graph.add_node("quality_review", nodes.traced("quality_review", nodes.quality_review, owner))
    graph.add_node(
        "request_approval", nodes.traced("request_approval", nodes.request_approval, owner)
    )
    graph.add_node("apply_decision", nodes.traced("apply_decision", nodes.apply_decision, owner))
    graph.add_edge("validate_request", "load_context")
    graph.add_edge("load_context", "gather_evidence")
    graph.add_edge("gather_evidence", "validate_sources")
    graph.add_edge("validate_sources", "score_lead")
    graph.add_edge("score_lead", "interpret")
    graph.add_edge("interpret", "quality_review")
    graph.add_conditional_edges("quality_review", _after_review)
    graph.add_edge("request_approval", "apply_decision")
    graph.add_edge("apply_decision", "finalize")
    graph.add_edge("finalize", END)
    return graph


def _build_agent(owner: str) -> StateGraph[Any, Any, Any, Any]:
    graph: StateGraph[Any, Any, Any, Any] = StateGraph(WorkflowState)
    graph.add_node(
        "validate_request", nodes.traced("validate_request", nodes.validate_request, owner)
    )
    graph.add_node("run_agent", nodes.traced("run_agent", nodes.run_agent(owner), owner))
    graph.add_node("finalize", nodes.traced("finalize", nodes.finalize, owner))
    graph.add_edge(START, "validate_request")
    graph.add_edge("validate_request", "run_agent")
    graph.add_edge("run_agent", "finalize")
    graph.add_edge("finalize", END)
    return graph


_BUILDERS = {
    WorkflowKind.research: _build_research,
    WorkflowKind.lead_intelligence: _build_lead_intelligence,
    WorkflowKind.agent: _build_agent,
}


def compile_graph(
    kind: WorkflowKind, owner: str, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[Any, Any, Any, Any]:
    return _BUILDERS[kind](owner).compile(checkpointer=checkpointer)
