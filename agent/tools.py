from __future__ import annotations

import hashlib
import json
from typing import Any, Dict
from urllib.parse import urlparse

import requests

from config import (
    AGENTCORE_GATEWAY_ENDPOINT,
    AGENTCORE_GATEWAY_TOOL_NAME,
    BACKEND_API_BASE,
    BEDROCK_KB_ID,
)

_resolved_kb_tool_name: str | None = None


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]

def _is_local_backend() -> bool:
    try:
        host = urlparse(BACKEND_API_BASE).hostname or ""
    except ValueError:
        host = ""
    return host in {"localhost", "127.0.0.1"} or host.endswith(".local")

def _auth_headers(token: str) -> Dict[str, str]:
    if not token:
        return {}
    if token.lower().startswith("bearer "):
        return {"Authorization": token}
    return {"Authorization": f"Bearer {token}"}

def _gateway_endpoint() -> str:
    if not AGENTCORE_GATEWAY_ENDPOINT:
        return ""
    return (
        AGENTCORE_GATEWAY_ENDPOINT
        if AGENTCORE_GATEWAY_ENDPOINT.rstrip("/").endswith("/mcp")
        else f"{AGENTCORE_GATEWAY_ENDPOINT.rstrip('/')}/mcp"
    )


def _gateway_jsonrpc(payload: Dict[str, Any], user_token: str) -> Dict[str, Any]:
    endpoint = _gateway_endpoint()
    if not endpoint:
        raise RuntimeError("AGENTCORE_GATEWAY_ENDPOINT not configured")
    if not AGENTCORE_GATEWAY_ENDPOINT:
        raise RuntimeError("AGENTCORE_GATEWAY_ENDPOINT not configured")
    response = requests.post(
        endpoint,
        json=payload,
        headers=_auth_headers(user_token),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _mock_summary(range_days: str) -> Dict[str, Any]:
    return {
        "range": range_days,
        "total_spend": 14_200_000,
        "total_income": 38_200_000,
        "largest_txn": {"amount": 5_500_000, "merchant": "Techcombank"},
        "jar_breakdown": [
            {"jar": "Bills", "amount": 4_200_000},
            {"jar": "Living", "amount": 6_800_000},
            {"jar": "Goals", "amount": 3_200_000},
        ],
        "note": "Mocked context (backend not reachable from runtime).",
    }


def sql_read_views(user_token: str, range_days: str) -> Dict[str, Any]:
    if _is_local_backend():
        return _mock_summary(range_days)
    headers = _auth_headers(user_token)
    try:
        response = requests.get(
            f"{BACKEND_API_BASE}/aggregates/summary",
            params={"range": range_days},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return _mock_summary(range_days)


def goals_get_set(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _is_local_backend():
        return {"status": "mocked", "payload": payload}
    headers = _auth_headers(user_token)
    response = requests.post(
        f"{BACKEND_API_BASE}/goals",
        json=payload,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def notifications_send(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _is_local_backend():
        return {"status": "mocked", "payload": payload}
    headers = _auth_headers(user_token)
    response = requests.post(
        f"{BACKEND_API_BASE}/notifications",
        json=payload,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _parse_kb_content(content: Any) -> Dict[str, Any]:
    context_text = ""
    sources: list[Dict[str, Any]] = []
    if not isinstance(content, list):
        return {"context": context_text, "matches": sources}
    for item in content:
        text = item.get("text", "") if isinstance(item, dict) else ""
        if text.startswith("Context:"):
            context_text = text.replace("Context:", "", 1).strip()
        if text.startswith("RAG Sources:"):
            raw = text.replace("RAG Sources:", "", 1).strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    sources = parsed
            except json.JSONDecodeError:
                pass
    matches = []
    for src in sources:
        matches.append(
            {
                "id": src.get("id", ""),
                "text": src.get("snippet", ""),
                "citation": src.get("fileName") or src.get("id") or "KB",
                "score": src.get("score", 0),
            }
        )
    return {"context": context_text, "matches": matches}

def _resolve_kb_tool_name(user_token: str) -> str:
    global _resolved_kb_tool_name
    if AGENTCORE_GATEWAY_TOOL_NAME:
        return AGENTCORE_GATEWAY_TOOL_NAME
    if _resolved_kb_tool_name:
        return _resolved_kb_tool_name
    try:
        data = _gateway_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"},
            user_token,
        )
        tools = (data.get("result") or {}).get("tools", [])
        for tool in tools:
            name = tool.get("name", "")
            if name == "retrieve_from_aws_kb" or name.endswith("___retrieve_from_aws_kb"):
                _resolved_kb_tool_name = name
                return name
    except requests.RequestException:
        pass
    return "retrieve_from_aws_kb"


def kb_retrieve(query: str, filters: Dict[str, str], user_token: str = "") -> Dict[str, Any]:
    if not BEDROCK_KB_ID:
        return {"matches": [], "note": "KB not configured"}
    if not AGENTCORE_GATEWAY_ENDPOINT:
        return {"matches": [], "note": "Gateway not configured"}
    tool_name = _resolve_kb_tool_name(user_token)
    payload = {
        "jsonrpc": "2.0",
        "id": "kb-1",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"query": query, "knowledgeBaseId": BEDROCK_KB_ID, "n": 3},
        },
    }
    try:
        data = _gateway_jsonrpc(payload, user_token)
        content = (data.get("result") or {}).get("content", [])
        parsed = _parse_kb_content(content)
        parsed["filters"] = filters
        return parsed
    except requests.RequestException as exc:
        return {"matches": [], "note": f"Gateway call failed: {exc}"}


def code_interpreter_run(expression: str) -> Dict[str, Any]:
    # Placeholder for AgentCore Code Interpreter invocation.
    return {"result": f"Computed ETA for: {expression}", "assumptions": {"inflation": 0.04}}


def audit_write(user_id: str, trace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"trace_id": trace_id, "payload_hash": _hash_payload(payload)}
