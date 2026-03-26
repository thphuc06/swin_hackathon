from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional


_TRACE_HEADERS = {
    "trace_id": "X-Trace-Id",
    "session_id": "X-Session-Id",
    "agent_name": "X-Agent-Name",
    "tool_name": "X-Tool-Name",
    "schema_version": "X-Schema-Version",
    "request_timestamp": "X-Request-Timestamp",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def tracing_enabled() -> bool:
    return _env_bool("ENABLE_TRACING", True)


def trace_log_level() -> str:
    return str(os.getenv("TRACE_LOG_LEVEL") or "INFO").strip().upper() or "INFO"


def _normalize_schema_version(tool_name: str | None, schema_version: str | None) -> str:
    raw = str(schema_version or "").strip()
    if raw:
        return raw
    tool = str(tool_name or "").strip().lower()
    if tool.endswith("_v1") or tool.endswith("v1"):
        return "v1"
    return "v1"


def build_trace_context(
    *,
    trace_id: str,
    session_id: str,
    agent_name: str,
    tool_name: str,
    schema_version: str | None,
    request_timestamp: str | None = None,
) -> Dict[str, str]:
    return {
        "trace_id": str(trace_id or ""),
        "session_id": str(session_id or ""),
        "agent_name": str(agent_name or ""),
        "tool_name": str(tool_name or ""),
        "schema_version": _normalize_schema_version(tool_name, schema_version),
        "request_timestamp": str(request_timestamp or utc_now_iso()),
    }


def trace_context_from_state(
    state: Mapping[str, Any],
    *,
    agent_name: str | None = None,
    tool_name: str | None = None,
    schema_version: str | None = None,
) -> Dict[str, str]:
    base = state.get("trace_ctx") if isinstance(state.get("trace_ctx"), dict) else {}
    return build_trace_context(
        trace_id=str(base.get("trace_id") or state.get("trace_id") or ""),
        session_id=str(base.get("session_id") or state.get("session_id") or ""),
        agent_name=str(agent_name or base.get("agent_name") or ""),
        tool_name=str(tool_name or base.get("tool_name") or ""),
        schema_version=str(schema_version or base.get("schema_version") or ""),
        request_timestamp=str(base.get("request_timestamp") or state.get("request_timestamp") or ""),
    )


def merge_trace_context(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> Dict[str, str]:
    merged = {**{k: str(v) for k, v in base.items() if v is not None}, **{k: str(v) for k, v in overrides.items() if v is not None}}
    return build_trace_context(
        trace_id=merged.get("trace_id", ""),
        session_id=merged.get("session_id", ""),
        agent_name=merged.get("agent_name", ""),
        tool_name=merged.get("tool_name", ""),
        schema_version=merged.get("schema_version", ""),
        request_timestamp=merged.get("request_timestamp", ""),
    )


def extract_trace_context(
    *,
    headers: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> Dict[str, str]:
    headers = headers or {}
    payload = payload or {}
    normalized = {str(k).lower(): v for k, v in headers.items()}
    return build_trace_context(
        trace_id=str(payload.get("trace_id") or normalized.get("x-trace-id") or ""),
        session_id=str(payload.get("session_id") or normalized.get("x-session-id") or ""),
        agent_name=str(payload.get("agent_name") or normalized.get("x-agent-name") or ""),
        tool_name=str(payload.get("tool_name") or normalized.get("x-tool-name") or ""),
        schema_version=str(payload.get("schema_version") or normalized.get("x-schema-version") or ""),
        request_timestamp=str(payload.get("request_timestamp") or normalized.get("x-request-timestamp") or ""),
    )


def trace_headers(trace_ctx: Mapping[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for key, header in _TRACE_HEADERS.items():
        value = str(trace_ctx.get(key) or "").strip()
        if value:
            headers[header] = value
    return headers


def log_trace_event(logger, event: str, trace_ctx: Mapping[str, Any], **fields: Any) -> None:
    if not tracing_enabled():
        return
    envelope = {"event": str(event or ""), "trace": dict(trace_ctx)}
    if fields:
        envelope.update(fields)
    level = trace_log_level()
    message = json.dumps(envelope, ensure_ascii=True, default=str)
    if level == "DEBUG":
        logger.debug("trace %s", message)
    elif level in {"WARN", "WARNING"}:
        logger.warning("trace %s", message)
    else:
        logger.info("trace %s", message)


__all__ = [
    "build_trace_context",
    "extract_trace_context",
    "log_trace_event",
    "merge_trace_context",
    "trace_context_from_state",
    "trace_headers",
    "trace_log_level",
    "tracing_enabled",
    "utc_now_iso",
]
