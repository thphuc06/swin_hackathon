from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict

import requests


def _mcp_base_url() -> str:
    return (os.getenv("FINANCE_MCP_URL") or "http://127.0.0.1:8020/mcp").strip()


def _mcp_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = str(os.getenv("FINANCE_MCP_AUTH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return headers


def _timeout_seconds() -> int:
    raw = os.getenv("WORKER_HTTP_TIMEOUT_SECONDS")
    if raw is None:
        return 15
    try:
        return max(1, int(raw.strip()))
    except ValueError:
        return 15


def _parse_tool_result_content(content: Any) -> Dict[str, Any]:
    if not isinstance(content, list):
        return {}
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return {}


def call_finance_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": f"wrk-{uuid.uuid4().hex[:10]}",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    response = requests.post(
        _mcp_base_url(),
        json=payload,
        headers=_mcp_headers(),
        timeout=_timeout_seconds(),
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"MCP tool call failed ({tool_name}): {data['error']}")
    result = data.get("result", {})
    if not isinstance(result, dict):
        return {}
    parsed = _parse_tool_result_content(result.get("content", []))
    if parsed:
        return parsed
    return result

