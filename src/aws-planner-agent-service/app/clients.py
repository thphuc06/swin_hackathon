"""Legacy standalone planner-agent-service clients.

These clients target the older direct MCP/service topology and are not used by
the production specialist-first flow in this repo.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from app.trace import trace_headers


def _strip_bearer(token: str) -> str:
    raw = token.strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


@dataclass
class MCPClientConfig:
    base_url: str
    auth_token: str
    timeout_seconds: float


class MCPClient:
    def __init__(self, config: MCPClientConfig) -> None:
        self.config = config

    def _headers(self, trace_context: Dict[str, Any] | None = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = self.config.auth_token.strip()
        if token:
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        if trace_context:
            headers.update(trace_headers(trace_context))
        return headers

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        trace_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": f"planner-{uuid.uuid4().hex[:10]}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        response = requests.post(
            self.config.base_url,
            json=payload,
            headers=self._headers(trace_context),
            timeout=self.config.timeout_seconds,
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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def build_finance_client() -> MCPClient:
    base_url = (os.getenv("FINANCE_MCP_URL") or "http://127.0.0.1:8020/mcp").strip()
    token = str(os.getenv("FINANCE_MCP_AUTH_TOKEN") or "").strip()
    timeout_seconds = _env_float("FINANCE_MCP_TIMEOUT_SECONDS", 12.0)
    return MCPClient(MCPClientConfig(base_url=base_url, auth_token=token, timeout_seconds=timeout_seconds))


def build_kb_client() -> Optional[MCPClient]:
    base_url = str(os.getenv("KB_MCP_URL") or "").strip()
    if not base_url:
        return None
    token = str(os.getenv("KB_MCP_AUTH_TOKEN") or "").strip()
    timeout_seconds = _env_float("KB_MCP_TIMEOUT_SECONDS", 10.0)
    return MCPClient(MCPClientConfig(base_url=base_url, auth_token=token, timeout_seconds=timeout_seconds))
