from __future__ import annotations

import logging
import time
from typing import Any, Dict

import graph as legacy_graph
from orchestrator.nodes.tool_calls import tool_calls_node as legacy_tools
from observability.trace_context import log_trace_event, trace_context_from_state
from strands_orchestrator.config import (
    enable_service_hidden_context_calls,
    enable_specialist_delegation,
)
from strands_orchestrator.specialist import (
    build_specialist_payload,
    call_specialist_tool,
    get_specialist_by_id,
    _planner_contract_from_state,
    _planner_summary_from_state,
    validate_specialist_output,
)

logger = logging.getLogger(__name__)
_HIDDEN_PLANNER_PROMPT = (
    "Please analyze my financial situation over the last 12 months for planning purposes. "
    "Summarize total income, total expenses, observed net cashflow, savings capacity, "
    "liquidity pressure, runway, anomalies, and planning readiness."
)


def _service_needs_hidden_planner(state: Dict[str, Any]) -> bool:
    request_envelope = state.get("request_envelope") if isinstance(state.get("request_envelope"), dict) else {}
    request_block = request_envelope.get("request") if isinstance(request_envelope.get("request"), dict) else {}
    user_context = request_block.get("user_context") if isinstance(request_block.get("user_context"), dict) else {}
    if isinstance(user_context.get("planner_state"), dict) and user_context.get("planner_state"):
        return False
    if isinstance(user_context.get("planner_standardized_contract"), dict) and user_context.get("planner_standardized_contract"):
        return False
    if str(user_context.get("planner_summary") or "").strip():
        return False
    if _planner_contract_from_state(state) is not None:
        return False
    if _planner_summary_from_state(state):
        return False
    return True

def _invoke_specialist_and_store(
    state: Dict[str, Any],
    descriptor: Any,
    result: Dict[str, Any],
    *,
    emit_reason_code: bool = True,
) -> None:
    validate_specialist_output(descriptor.output_schema, result)
    legacy_graph._record_tool_output(state, descriptor.tool_name, result)  # type: ignore[attr-defined]
    agent_outputs = state.get("agent_outputs")
    if not isinstance(agent_outputs, dict):
        agent_outputs = {}
    agent_outputs[descriptor.id] = result
    state["agent_outputs"] = agent_outputs
    if emit_reason_code:
        legacy_graph._append_response_reason_codes(  # type: ignore[attr-defined]
            state,
            [f"delegated:{descriptor.id}"],
        )


def _hidden_service_prefetch(state: Dict[str, Any]) -> None:
    if not enable_service_hidden_context_calls():
        return

    planner_descriptor = get_specialist_by_id("planner")

    if planner_descriptor is not None and _service_needs_hidden_planner(state):
        planner_payload = build_specialist_payload(planner_descriptor, state)
        planner_request = planner_payload.get("request") if isinstance(planner_payload.get("request"), dict) else {}
        planner_request["prompt"] = _HIDDEN_PLANNER_PROMPT
        planner_request["intent"] = "planning"
        planner_payload["request"] = planner_request
        try:
            planner_result = call_specialist_tool(
                planner_descriptor,
                planner_payload,
                state["user_token"],
                trace_id=str(state.get("trace_id") or ""),
                trace_context=trace_context_from_state(
                    state,
                    agent_name="orchestrator",
                    tool_name=planner_descriptor.tool_name,
                    schema_version=planner_descriptor.tool_version,
                ),
            )
            if isinstance(planner_result, dict):
                _invoke_specialist_and_store(state, planner_descriptor, planner_result)
                legacy_graph._append_response_reason_codes(state, ["hidden_context:planner"])  # type: ignore[attr-defined]
        except Exception as exc:
            legacy_graph._record_tool_error(state, planner_descriptor.tool_name, exc)  # type: ignore[attr-defined]
            legacy_graph._append_response_reason_codes(state, ["hidden_context_error:planner"])  # type: ignore[attr-defined]


def tool_invocation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    if not enable_specialist_delegation():
        return legacy_tools(state)
    if state.get("response"):
        return state
    if bool(state.get("clarification", {}).get("pending")):
        return state

    specialist_id = str(state.get("selected_specialist_id") or "").strip()
    if not specialist_id:
        return state

    descriptor = get_specialist_by_id(specialist_id)
    if descriptor is None:
        legacy_graph._append_response_reason_codes(state, ["specialist_not_found"])  # type: ignore[attr-defined]
        return state

    if descriptor.id == "service":
        _hidden_service_prefetch(state)

    payload = build_specialist_payload(descriptor, state)
    trace_ctx = trace_context_from_state(
        state,
        agent_name="orchestrator",
        tool_name=descriptor.tool_name,
        schema_version=descriptor.tool_version,
    )
    start_ts = legacy_graph._utc_now_iso()  # type: ignore[attr-defined]
    started_perf = time.perf_counter()
    legacy_graph._emit_tool_trace_start(state, descriptor.tool_name, start_ts=start_ts)  # type: ignore[attr-defined]
    log_trace_event(
        logger,
        "specialist_call_start",
        trace_ctx,
        payload={"agent_id": descriptor.id, "tool_name": descriptor.tool_name},
    )

    try:
        result = call_specialist_tool(
            descriptor,
            payload,
            state["user_token"],
            trace_id=str(state.get("trace_id") or ""),
            trace_context=trace_ctx,
        )
        if not isinstance(result, dict):
            raise ValueError("Specialist tool result must be a JSON object.")
        validate_specialist_output(descriptor.output_schema, result)

        legacy_graph._record_tool_output(state, descriptor.tool_name, result)  # type: ignore[attr-defined]
        agent_outputs = state.get("agent_outputs")
        if not isinstance(agent_outputs, dict):
            agent_outputs = {}
        agent_outputs[descriptor.id] = result
        state["agent_outputs"] = agent_outputs
        legacy_graph._append_response_reason_codes(  # type: ignore[attr-defined]
            state,
            [f"delegated:{descriptor.id}"],
        )

        status = str(result.get("status") or "ok").strip().lower() or "ok"
        legacy_graph._emit_tool_trace_end(  # type: ignore[attr-defined]
            state,
            descriptor.tool_name,
            start_ts=start_ts,
            started_perf=started_perf,
            status=status,
            tool_result=result,
            error_code=str(result.get("error_code") or result.get("code") or "").strip().lower(),
        )
        log_trace_event(
            logger,
            "specialist_call_end",
            trace_ctx,
            payload={"agent_id": descriptor.id, "tool_name": descriptor.tool_name, "status": status},
        )
        return state
    except Exception as exc:
        legacy_graph._record_tool_error(state, descriptor.tool_name, exc)  # type: ignore[attr-defined]
        tool_calls = state.get("tool_calls")
        if isinstance(tool_calls, list) and descriptor.tool_name not in tool_calls:
            tool_calls.append(descriptor.tool_name)
        log_trace_event(
            logger,
            "specialist_call_error",
            trace_ctx,
            payload={"agent_id": descriptor.id, "tool_name": descriptor.tool_name, "error": str(exc)},
        )
        legacy_graph._append_response_reason_codes(  # type: ignore[attr-defined]
            state,
            [f"specialist_error:{descriptor.id}"],
        )
        legacy_graph._emit_tool_trace_end(  # type: ignore[attr-defined]
            state,
            descriptor.tool_name,
            start_ts=start_ts,
            started_perf=started_perf,
            status="error",
            tool_result=exc,
            error_code=str(getattr(exc, "code", "") or "").strip().lower(),
        )
        state["response"] = legacy_graph._finalize_response(
            "Specialist service is unavailable. Please try again later.",
            "",
            str(state.get("trace_id") or ""),
            ", ".join(state.get("tool_calls", [])),
        )
        return state
