from __future__ import annotations

from typing import Any, Dict

from orchestrator.nodes.respond import respond_node as legacy_respond
from strands_orchestrator.config import enable_specialist_delegation
from strands_orchestrator.specialist_response import apply_specialist_response


def response_node(state: Dict[str, Any]) -> Dict[str, Any]:
    if not enable_specialist_delegation():
        return legacy_respond(state)
    if bool(state.get("clarification", {}).get("pending")):
        return legacy_respond(state)
    next_state = apply_specialist_response(state)
    if next_state.get("response"):
        return next_state
    return legacy_respond(next_state)
