from __future__ import annotations

import logging
import os
import uuid
from typing import List
from typing import Any, Dict

from bedrock_agentcore import BedrockAgentCoreApp
from dotenv import load_dotenv

load_dotenv()

from identity_map import resolve_runtime_user_ids
from infra.auth import get_auth_provider
from memory import initialize_memory_store
from observability.trace_context import utc_now_iso
from observability.tracing import new_request_id, new_trace_id
from strands_orchestrator.config import use_strands_orchestrator
from tools import initialize_kb

logger = logging.getLogger(__name__)
app = BedrockAgentCoreApp()
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."

# Initialize local Knowledge Base at startup (replaces OpenSearch/Bedrock KB)
try:
    kb_result = initialize_kb()
    if kb_result.get("status") == "success":
        logger.info(
            "Startup: Local KB initialized with %d files: %s",
            kb_result.get("files", 0),
            ", ".join(kb_result.get("filenames", [])),
        )
    else:
        logger.error("Startup: KB initialization failed: %s", kb_result.get("error", "unknown"))
except Exception as exc:
    logger.error("Startup: KB initialization exception: %s", exc)

# Initialize optional memory layer (no-op unless enabled)
try:
    if initialize_memory_store() is not None:
        logger.info("Startup: Memory store initialized (in-memory)")
    else:
        logger.info("Startup: Memory store disabled")
except Exception as exc:
    logger.warning("Startup: Memory store initialization failed: %s", exc)

logger.info("Startup: Tool registry eager initialization deferred until the first authenticated request")


def _authorization_from_context(context: Any | None) -> str:
    if context is None:
        return ""

    request_headers = getattr(context, "request_headers", None)
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() == "authorization" and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None)
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("Authorization") or headers.get("authorization")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _resolve_user_token(payload: Dict[str, Any], context: Any | None) -> str:
    payload_token = payload.get("authorization")
    if isinstance(payload_token, str) and payload_token.strip():
        return payload_token.strip()

    context_token = _authorization_from_context(context)
    if context_token:
        return context_token

    return ""


def _resolve_session_id(payload: Dict[str, Any], context: Any | None, *, user_id: str) -> str:
    _ = user_id
    payload_session = payload.get("session_id")
    if isinstance(payload_session, str) and payload_session.strip():
        return payload_session.strip()

    request_headers = getattr(context, "request_headers", None) if context is not None else None
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() in {"x-session-id", "session-id"} and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None) if context is not None else None
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("X-Session-Id") or headers.get("x-session-id") or headers.get("Session-Id")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return f"sess_{uuid.uuid4().hex}"


def _resolve_trace_id(payload: Dict[str, Any], context: Any | None) -> str | None:
    payload_trace = payload.get("trace_id")
    if isinstance(payload_trace, str) and payload_trace.strip():
        return payload_trace.strip()

    request_headers = getattr(context, "request_headers", None) if context is not None else None
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() == "x-trace-id" and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None) if context is not None else None
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("X-Trace-Id") or headers.get("x-trace-id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_request_timestamp(payload: Dict[str, Any], context: Any | None) -> str | None:
    payload_ts = payload.get("request_timestamp")
    if isinstance(payload_ts, str) and payload_ts.strip():
        return payload_ts.strip()

    request_headers = getattr(context, "request_headers", None) if context is not None else None
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() == "x-request-timestamp" and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None) if context is not None else None
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("X-Request-Timestamp") or headers.get("x-request-timestamp")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_request_id(payload: Dict[str, Any], context: Any | None) -> str | None:
    payload_request_id = payload.get("request_id")
    if isinstance(payload_request_id, str) and payload_request_id.strip():
        return payload_request_id.strip()

    request_headers = getattr(context, "request_headers", None) if context is not None else None
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() in {"x-request-id", "request-id"} and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None) if context is not None else None
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("X-Request-Id") or headers.get("x-request-id") or headers.get("Request-Id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_parent_request_id(payload: Dict[str, Any], context: Any | None) -> str | None:
    payload_parent = payload.get("parent_request_id")
    if isinstance(payload_parent, str) and payload_parent.strip():
        return payload_parent.strip()

    request_headers = getattr(context, "request_headers", None) if context is not None else None
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() == "x-parent-request-id" and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None) if context is not None else None
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("X-Parent-Request-Id") or headers.get("x-parent-request-id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_scopes(claims: Dict[str, Any]) -> List[str]:
    raw = claims.get("scope") if isinstance(claims, dict) else None
    if isinstance(raw, str):
        scopes = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
        if scopes:
            return scopes

    raw_scopes = claims.get("scopes") if isinstance(claims, dict) else None
    if isinstance(raw_scopes, list):
        scopes = [str(item).strip() for item in raw_scopes if str(item).strip()]
        if scopes:
            return scopes

    return ["chat:invoke"]


def _build_request_envelope(
    *,
    prompt: str,
    actor_id: str,
    user_id: str,
    session_id: str,
    trace_id: str,
    request_id: str,
    parent_request_id: str,
    request_timestamp: str,
    auth_result: Any,
    planner_context: Dict[str, Any] | None = None,
    stock_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    claims = auth_result.claims if isinstance(getattr(auth_result, "claims", None), dict) else {}
    tenant_id = str(
        claims.get("tenant_id")
        or claims.get("custom:tenant_id")
        or claims.get("org_id")
        or ""
    ).strip()
    user_context: Dict[str, Any] = {
        "user_id": str(user_id or ""),
        "auth_subject": str(actor_id or ""),
    }
    if isinstance(planner_context, dict):
        planner_summary = str(planner_context.get("planner_summary") or "").strip()
        planner_contract = (
            planner_context.get("planner_standardized_contract")
            if isinstance(planner_context.get("planner_standardized_contract"), dict)
            else {}
        )
        if planner_summary:
            user_context["planner_summary"] = planner_summary
        if planner_contract:
            user_context["planner_standardized_contract"] = planner_contract
    if isinstance(stock_context, dict) and stock_context:
        user_context["stock_context"] = dict(stock_context)

    return {
        "schema_version": "v1",
        "actor": {
            "actor_id": str(actor_id or ""),
            "user_id": str(user_id or ""),
            "tenant_id": tenant_id,
            "scopes": _normalize_scopes(claims),
        },
        "correlation": {
            "session_id": session_id,
            "request_id": request_id,
            "trace_id": trace_id,
            "parent_request_id": parent_request_id,
            "request_timestamp": request_timestamp,
        },
        "request": {
            "prompt": prompt,
            "intent": "",
            "policy_flags": {"education_only": False},
            "user_context": user_context,
            "goals": [],
            "session_summary": "",
        },
        "routing": {
            "specialist_id": "",
            "tool_name": "",
        },
    }


@app.entrypoint
def invoke(payload: Dict[str, Any], context: Any | None = None) -> Dict[str, Any]:
    prompt = payload.get("prompt", "")
    user_token = _resolve_user_token(payload, context)
    auth_result = get_auth_provider().verify(user_token if isinstance(user_token, str) else None)
    if not bool(auth_result.authenticated) or not str(auth_result.subject or "").strip():
        raise PermissionError(f"Unauthorized runtime request: {str(auth_result.reason or 'missing_subject').strip()}")
    actor_id, data_user_id = resolve_runtime_user_ids(
        payload_user_id=payload.get("user_id"),
        auth_subject=auth_result.subject,
    )
    if actor_id != data_user_id:
        logger.info("data_user_mapping_applied actor_id=%s data_user_id=%s", actor_id, data_user_id)
    session_id = _resolve_session_id(payload, context, user_id=str(actor_id))
    trace_id = _resolve_trace_id(payload, context) or new_trace_id()
    request_timestamp = _resolve_request_timestamp(payload, context) or utc_now_iso()
    request_id = _resolve_request_id(payload, context) or new_request_id()
    parent_request_id = _resolve_parent_request_id(payload, context) or request_id
    planner_context = payload.get("planner_context") if isinstance(payload.get("planner_context"), dict) else {}
    stock_context = payload.get("stock_context") if isinstance(payload.get("stock_context"), dict) else {}
    request_envelope = _build_request_envelope(
        prompt=str(prompt or ""),
        actor_id=str(actor_id or ""),
        user_id=str(data_user_id or ""),
        session_id=session_id,
        trace_id=str(trace_id or ""),
        request_id=request_id,
        parent_request_id=parent_request_id,
        request_timestamp=request_timestamp,
        auth_result=auth_result,
        planner_context=planner_context,
        stock_context=stock_context,
    )
    if use_strands_orchestrator():
        logger.info("Orchestrator mode: Strands")
        from strands_orchestrator.runtime import run_strands_agent

        result = run_strands_agent(
            prompt=prompt,
            user_token=user_token,
            user_id=data_user_id,
            session_id=session_id,
            trace_id=trace_id,
            request_timestamp=request_timestamp,
            request_envelope=request_envelope,
        )
    else:
        logger.warning(
            "Deprecated runtime path enabled: USE_STRANDS_ORCHESTRATOR=false switches the orchestrator back to the legacy LangGraph path."
        )
        from graph import run_agent

        result = run_agent(
            prompt=prompt,
            user_token=user_token,
            user_id=data_user_id,
            session_id=session_id,
            trace_id=trace_id,
            request_timestamp=request_timestamp,
        )
    response_meta = result.get("response_meta", {}) if isinstance(result.get("response_meta"), dict) else {}
    disclaimer = str(response_meta.get("disclaimer_effective") or DEFAULT_DISCLAIMER)
    agent_outputs = result.get("agent_outputs", {}) if isinstance(result.get("agent_outputs"), dict) else {}
    planner_context = result.get("planner_context") if isinstance(result.get("planner_context"), dict) else {}
    service_output = agent_outputs.get("service") if isinstance(agent_outputs.get("service"), dict) else {}
    roadmap_payload = result.get("roadmap_payload") if isinstance(result.get("roadmap_payload"), dict) else {}
    if not roadmap_payload:
        roadmap_payload = service_output.get("roadmap_contract") if isinstance(service_output.get("roadmap_contract"), dict) else {}
    service_payload = service_output if service_output else {}
    return {
        "result": result["response"],
        "trace_id": result["trace_id"],
        "request_id": result.get("request_id", ""),
        "session_id": result.get("session_id", session_id),
        "citations": result["citations"].get("matches", []),
        "tool_calls": result.get("tool_calls", []),
        "agent_outputs": agent_outputs,
        "planner_context": planner_context,
        "service_payload": service_payload,
        "roadmap_payload": roadmap_payload,
        "routing_meta": result.get("routing_meta", {}),
        "response_meta": response_meta,
        "auth_meta": {
            "authenticated": bool(auth_result.authenticated),
            "subject": str(auth_result.subject or ""),
            "reason": str(auth_result.reason or ""),
        },
        "disclaimer": disclaimer,
    }


if __name__ == "__main__":
    _port = int(os.environ.get("PORT") or os.environ.get("AGENT_PORT", 8081))
    app.run(port=_port)
