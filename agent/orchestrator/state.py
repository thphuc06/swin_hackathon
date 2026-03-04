from __future__ import annotations

from typing import Any, Dict, TypedDict


class OrchestratorState(TypedDict, total=False):
    trace_id: str
    request_id: str
    session_id: str
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
    agent_outputs: Dict[str, Any]
