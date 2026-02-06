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
    USE_LOCAL_MOCKS,
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


def _should_use_local_mocks() -> bool:
    return USE_LOCAL_MOCKS and _is_local_backend()


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


def _request_json(
    method: str,
    path: str,
    user_token: str,
    *,
    params: Dict[str, Any] | None = None,
    payload: Dict[str, Any] | None = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    response = requests.request(
        method=method,
        url=f"{BACKEND_API_BASE}{path}",
        headers=_auth_headers(user_token),
        params=params,
        json=payload,
        timeout=timeout,
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


def _mock_forecast(horizon_months: int = 3) -> Dict[str, Any]:
    points = []
    for idx in range(max(1, min(24, horizon_months))):
        month = f"2026-{idx+1:02d}"
        points.append(
            {
                "month": month,
                "income_estimate": 35_000_000,
                "spend_estimate": 21_000_000,
                "p10": 10_000_000,
                "p50": 14_000_000,
                "p90": 18_000_000,
            }
        )
    return {
        "forecast_points": points,
        "monthly_forecast": points,
        "confidence_band": {"p10_avg": 10_000_000, "p50_avg": 14_000_000, "p90_avg": 18_000_000},
        "assumptions": ["Mocked forecast"],
        "trace_id": "trc_mocked01",
        "model_meta": {"model_version": "mock", "low_history": True},
    }


def sql_read_views(user_token: str, range_days: str) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return _mock_summary(range_days)
    try:
        return _request_json(
            "GET",
            "/aggregates/summary",
            user_token,
            params={"range": range_days},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Backend call failed: GET /aggregates/summary") from exc


def goals_get_set(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"status": "mocked", "payload": payload}
    return _request_json("POST", "/goals", user_token, payload=payload, timeout=10)


def notifications_send(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"status": "mocked", "payload": payload}
    return _request_json("POST", "/notifications", user_token, payload=payload, timeout=10)


def forecast_cashflow(user_token: str, range_days: str = "90d") -> Dict[str, Any]:
    if _should_use_local_mocks():
        return _mock_forecast(horizon_months=3)
    try:
        return _request_json(
            "GET",
            "/forecast/cashflow",
            user_token,
            params={"range": range_days},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Backend call failed: GET /forecast/cashflow") from exc


def forecast_cashflow_scenario(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        horizon = int(payload.get("horizon_months", 12))
        return _mock_forecast(horizon)
    try:
        return _request_json("POST", "/forecast/cashflow/scenario", user_token, payload=payload, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError("Backend call failed: POST /forecast/cashflow/scenario") from exc


def forecast_runway(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "runway_months": 12,
            "stress_result": [],
            "risk_flags": [],
            "trace_id": payload.get("trace_id", "trc_mocked01"),
        }
    try:
        return _request_json("POST", "/forecast/runway", user_token, payload=payload, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError("Backend call failed: POST /forecast/runway") from exc


def decision_savings_goal(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "metrics": {"required_monthly_saving": 8_000_000, "gap_amount": 0},
            "grade": "A",
            "reasons": ["Mocked decision"],
            "guardrails": [],
            "trace_id": payload.get("trace_id", "trc_mocked01"),
        }
    return _request_json("POST", "/decision/savings-goal", user_token, payload=payload, timeout=20)


def decision_house_affordability(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "metrics": {"monthly_payment": 12_000_000, "DTI": 0.32},
            "grade": "B",
            "reasons": ["Mocked house affordability"],
            "guardrails": [],
            "trace_id": payload.get("trace_id", "trc_mocked01"),
        }
    return _request_json("POST", "/decision/house-affordability", user_token, payload=payload, timeout=20)


def decision_investment_capacity(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "metrics": {"investable_low": 2_000_000, "investable_high": 3_500_000},
            "grade": "B",
            "reasons": ["Mocked investment capacity"],
            "guardrails": ["education_only=true"],
            "trace_id": payload.get("trace_id", "trc_mocked01"),
            "education_only": True,
        }
    return _request_json("POST", "/decision/investment-capacity", user_token, payload=payload, timeout=20)


def decision_what_if(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "scenario_comparison": [{"name": "base", "total_net_p50": 1}],
            "best_variant_by_goal": "base",
            "trace_id": payload.get("trace_id", "trc_mocked01"),
        }
    return _request_json("POST", "/decision/what-if", user_token, payload=payload, timeout=20)


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
    return {"result": f"Computed ETA for: {expression}", "assumptions": {"inflation": 0.04}}


def audit_write(user_id: str, trace_id: str, payload: Dict[str, Any], user_token: str = "") -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"trace_id": trace_id, "payload_hash": _hash_payload(payload)}
    try:
        body = {
            "trace_id": trace_id,
            "event_type": "agent_summary",
            "payload": {
                **payload,
                "user_id": user_id,
            },
        }
        return _request_json("POST", "/audit", user_token, payload=body, timeout=10)
    except requests.RequestException:
        return {"trace_id": trace_id, "payload_hash": _hash_payload(payload)}
