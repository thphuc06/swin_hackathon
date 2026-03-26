from __future__ import annotations

from typing import Any, Dict, TypedDict


class OrchestratorState(TypedDict, total=False):
    trace_id: str
    request_id: str
    session_id: str
    request_timestamp: str
    request_envelope: Dict[str, Any]
    trace_ctx: Dict[str, Any]
    session_memory: Dict[str, Any]
    user_token: str
    user_id: str
    prompt: str
    intent: str
    route_decision: Dict[str, Any]
    context: Dict[str, Any]
    kb: Dict[str, Any]
    tool_outputs: Dict[str, Any]
    tool_errors: Dict[str, Any]
    tool_calls: list[str]
    response: str
    response_meta: Dict[str, Any]
    selected_agent: str
    selected_specialist_id: str
    specialist_selection: Dict[str, Any]
    agent_outputs: Dict[str, Any]
