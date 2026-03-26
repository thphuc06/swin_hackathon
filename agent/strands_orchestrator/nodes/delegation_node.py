from __future__ import annotations

import logging
from typing import Any, Dict

import graph as legacy_graph
from orchestrator.nodes.select_agent import select_agent_node as legacy_select
from observability.trace_context import log_trace_event, trace_context_from_state
from strands_orchestrator.config import enable_specialist_delegation
from strands_orchestrator.specialist import select_specialist_for_state

logger = logging.getLogger(__name__)


def delegation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    if not enable_specialist_delegation():
        return legacy_select(state)
    if state.get("response"):
        return state
    if bool(state.get("clarification", {}).get("pending")):
        state["selected_agent"] = ""
        state["selected_specialist_id"] = ""
        state["specialist_selection"] = {
            "selected_id": None,
            "reason": "clarification_pending",
        }
        return state

    specialist, meta = select_specialist_for_state(state)
    state["specialist_selection"] = meta
    trace_ctx = trace_context_from_state(
        state,
        agent_name="orchestrator",
        tool_name="delegation",
        schema_version="v1",
    )
    log_trace_event(logger, "specialist_selection", trace_ctx, payload=meta)
    if specialist is None:
        state["selected_specialist_id"] = ""
        legacy_graph._append_response_reason_codes(state, ["specialist_selection_failed"])
        return state

    state["selected_agent"] = specialist.id
    state["selected_specialist_id"] = specialist.id
    return state
