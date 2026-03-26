from __future__ import annotations

from functools import lru_cache
import uuid
from typing import Any, Dict

import graph as legacy_graph
from observability.trace_context import build_trace_context, utc_now_iso
from observability.tracing import new_request_id, new_trace_id
from strands_orchestrator.graph import build_graph


def _response_mode() -> str:
    return legacy_graph._response_mode()  # type: ignore[attr-defined]


@lru_cache
def _graph() -> Any:
    return build_graph()


def run_strands_agent(
    prompt: str,
    user_token: str,
    user_id: str,
    session_id: str | None = None,
    *,
    trace_id: str | None = None,
    request_timestamp: str | None = None,
    request_envelope: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    trace_id = str(trace_id or "").strip() or str(
        ((request_envelope or {}).get("correlation") or {}).get("trace_id") or ""
    ) or new_trace_id()
    request_id = str(((request_envelope or {}).get("correlation") or {}).get("request_id") or "").strip() or new_request_id()
    resolved_session_id = str(session_id or "").strip() or f"sess_{uuid.uuid4().hex}"
    request_timestamp = str(request_timestamp or "").strip() or utc_now_iso()
    trace_ctx = build_trace_context(
        trace_id=trace_id,
        session_id=resolved_session_id,
        agent_name="orchestrator",
        tool_name="orchestrator",
        schema_version="v1",
        request_timestamp=request_timestamp,
    )

    state: Dict[str, Any] = {
        "prompt": prompt,
        "user_token": user_token,
        "user_id": user_id,
        "request_id": request_id,
        "session_id": resolved_session_id,
        "request_timestamp": request_timestamp,
        "request_envelope": request_envelope or {},
        "trace_ctx": trace_ctx,
        "session_memory": {},
        "intent": "",
        "scenario_request": {},
        "context": {},
        "kb": {},
        "tool_outputs": {},
        "tool_calls": [],
        "education_only": False,
        "user_profile": {"risk_appetite": "unknown"},
        "extraction": {},
        "route_decision": {},
        "clarification": {
            "pending": False,
            "round": 0,
            "max_questions": legacy_graph.ROUTER_MAX_CLARIFY_QUESTIONS,
        },
        "encoding_meta": {},
        "evidence_pack": {},
        "advisory_context": {},
        "answer_plan_v2": {},
        "tool_errors": {},
        "selected_agent": "",
        "selected_specialist_id": "",
        "specialist_selection": {},
        "agent_outputs": {},
        "planner_context": {},
        "roadmap_payload": {},
        "response_meta": {
            "mode": _response_mode(),
            "model_id": "",
            "prompt_version": legacy_graph.RESPONSE_PROMPT_VERSION,
            "schema_version": legacy_graph.RESPONSE_SCHEMA_VERSION,
            "policy_version": legacy_graph.RESPONSE_POLICY_VERSION,
            "validation_passed": False,
            "fallback_used": None,
            "used_fact_ids": [],
            "used_insight_ids": [],
            "used_action_ids": [],
            "latency_ms": 0,
            "reason_codes": [],
            "disclaimer_effective": legacy_graph.DEFAULT_DISCLAIMER,
            "encoding_decision": "pass",
            "encoding_score": 0.0,
            "encoding_repair_applied": False,
            "encoding_reason_codes": [],
            "encoding_guess": "",
            "encoding_input_fingerprint": "",
            "tool_errors": {},
        },
        "response": "",
        "trace_id": trace_id,
    }

    graph = _graph()
    graph(prompt, invocation_state=state)

    return {
        "response": state.get("response", ""),
        "trace_id": trace_id,
        "request_id": request_id,
        "session_id": resolved_session_id,
        "citations": state.get("kb", {}),
        "tool_calls": state.get("tool_calls", []),
        "tool_outputs": state.get("tool_outputs", {}),
        "agent_outputs": state.get("agent_outputs", {}),
        "planner_context": state.get("planner_context", {}) if isinstance(state.get("planner_context"), dict) else {},
        "roadmap_payload": state.get("roadmap_payload", {}) if isinstance(state.get("roadmap_payload"), dict) else {},
        "routing_meta": {
            "intent": state.get("intent", ""),
            "extraction": state.get("extraction", {}),
            "route_decision": state.get("route_decision", {}),
            "clarification": state.get("clarification", {}),
            "encoding_meta": state.get("encoding_meta", {}),
            "user_profile": state.get("user_profile", {}),
            "selected_agent": state.get("selected_agent", ""),
            "selected_specialist_id": state.get("selected_specialist_id", ""),
            "session_id": resolved_session_id,
        },
        "response_meta": state.get("response_meta", {}),
    }
