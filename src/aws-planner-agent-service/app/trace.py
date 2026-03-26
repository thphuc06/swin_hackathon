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


def build_trace_context(
    *,
    trace_id: str,
    session_id: str,
    agent_name: str,
    tool_name: str,
    schema_version: str,
    request_timestamp: str | None = None,
) -> Dict[str, str]:
    return {
        "trace_id": str(trace_id or ""),
        "session_id": str(session_id or ""),
        "agent_name": str(agent_name or ""),
        "tool_name": str(tool_name or ""),
        "schema_version": str(schema_version or "v1"),
        "request_timestamp": str(request_timestamp or _utc_now_iso()),
    }


def with_tool(trace_ctx: Mapping[str, Any], tool_name: str) -> Dict[str, str]:
    schema_version = "v1" if str(tool_name or "").endswith("_v1") else str(trace_ctx.get("schema_version") or "v1")
    return build_trace_context(
        trace_id=str(trace_ctx.get("trace_id") or ""),
        session_id=str(trace_ctx.get("session_id") or ""),
        agent_name=str(trace_ctx.get("agent_name") or "planner"),
        tool_name=str(tool_name or ""),
        schema_version=schema_version,
        request_timestamp=str(trace_ctx.get("request_timestamp") or ""),
    )


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


__all__ = ["build_trace_context", "log_event", "trace_headers", "with_tool"]
