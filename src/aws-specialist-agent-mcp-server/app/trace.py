from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def tracing_enabled() -> bool:
    return _env_bool("ENABLE_TRACING", True)


def _header_value(headers: Mapping[str, Any], key: str) -> str:
    for name, value in headers.items():
        if str(name).lower() == key.lower():
            return str(value or "")
    return ""


def extract_trace_context(arguments: Mapping[str, Any], headers: Mapping[str, Any]) -> Dict[str, str]:
    correlation = arguments.get("correlation") if isinstance(arguments.get("correlation"), dict) else {}
    routing = arguments.get("routing") if isinstance(arguments.get("routing"), dict) else {}
    return {
        "trace_id": str(correlation.get("trace_id") or _header_value(headers, "x-trace-id") or ""),
        "session_id": str(correlation.get("session_id") or _header_value(headers, "x-session-id") or ""),
        "agent_name": str(routing.get("specialist_id") or _header_value(headers, "x-agent-name") or "specialist-mcp"),
        "tool_name": str(routing.get("tool_name") or _header_value(headers, "x-tool-name") or ""),
        "schema_version": str(
            arguments.get("schema_version")
            or _header_value(headers, "x-schema-version")
            or "v1"
        ),
        "request_timestamp": str(
            correlation.get("request_timestamp")
            or _header_value(headers, "x-request-timestamp")
            or _utc_now_iso()
        ),
    }


def trace_headers(trace_ctx: Mapping[str, Any]) -> Dict[str, str]:
    headers = {}
    for key, header in {
        "trace_id": "X-Trace-Id",
        "session_id": "X-Session-Id",
        "agent_name": "X-Agent-Name",
        "tool_name": "X-Tool-Name",
        "schema_version": "X-Schema-Version",
        "request_timestamp": "X-Request-Timestamp",
    }.items():
        value = str(trace_ctx.get(key) or "").strip()
        if value:
            headers[header] = value
    return headers


def log_event(logger, event: str, trace_ctx: Mapping[str, Any], **fields: Any) -> None:
    if not tracing_enabled():
        return
    envelope = {"event": str(event or ""), "trace": dict(trace_ctx)}
    if fields:
        envelope.update(fields)
    logger.info("trace %s", json.dumps(envelope, ensure_ascii=True, default=str))


__all__ = ["extract_trace_context", "log_event", "trace_headers", "tracing_enabled"]
