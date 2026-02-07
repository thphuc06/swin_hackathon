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

_resolved_tool_names: Dict[str, str] = {}


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _is_local_backend() -> bool:
    try:
        host = urlparse(BACKEND_API_BASE).hostname or ""
    except ValueError:
        host = ""
    return host in {"localhost", "127.0.0.1"} or host.endswith(".local")


def _should_use_local_mocks() -> bool:
    return USE_LOCAL_MOCKS and (not AGENTCORE_GATEWAY_ENDPOINT or _is_local_backend())


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
    response = requests.post(
        endpoint,
        json=payload,
        headers=_auth_headers(user_token),
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Gateway tool error: {data['error']}")
    return data


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


def _resolve_tool_name(base_name: str, user_token: str) -> str:
    if base_name in _resolved_tool_names:
        return _resolved_tool_names[base_name]

    data = _gateway_jsonrpc({"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"}, user_token)
    tools = (data.get("result") or {}).get("tools", [])
    for tool in tools:
        name = str(tool.get("name") or "")
        if name == base_name or name.endswith(f"___{base_name}"):
            _resolved_tool_names[base_name] = name
            return name
    raise RuntimeError(f"Tool {base_name} not found in AgentCore Gateway tools/list")


def _call_gateway_tool(base_name: str, arguments: Dict[str, Any], user_token: str) -> Dict[str, Any]:
    resolved_name = _resolve_tool_name(base_name, user_token)
    payload = {
        "jsonrpc": "2.0",
        "id": f"tool-{base_name}",
        "method": "tools/call",
        "params": {"name": resolved_name, "arguments": arguments},
    }
    data = _gateway_jsonrpc(payload, user_token)
    content = (data.get("result") or {}).get("content", [])
    return _parse_tool_result_content(content)


def _mock_spend(range_days: str) -> Dict[str, Any]:
    return {
        "range": range_days,
        "total_spend": 14_200_000,
        "total_income": 38_200_000,
        "net_cashflow": 24_000_000,
        "jar_splits": [],
        "top_merchants": [],
        "budget_drift": [],
        "trace_id": "trc_mocked01",
    }


def _mock_forecast(horizon: str = "weekly_12") -> Dict[str, Any]:
    points = []
    count = 12 if horizon == "weekly_12" else 30
    for idx in range(count):
        points.append(
            {
                "period": f"p{idx+1}",
                "income_estimate": 35_000_000,
                "spend_estimate": 21_000_000,
                "p10": 10_000_000,
                "p50": 14_000_000,
                "p90": 18_000_000,
            }
        )
    return {
        "points": points,
        "confidence_band": {"p10_avg": 10_000_000, "p50_avg": 14_000_000, "p90_avg": 18_000_000},
        "trace_id": "trc_mocked01",
    }


def spend_analytics(user_token: str, user_id: str, range_days: str = "30d", trace_id: str | None = None) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return _mock_spend(range_days)
    return _call_gateway_tool(
        "spend_analytics_v1",
        {"user_id": user_id, "range": range_days, "trace_id": trace_id},
        user_token,
    )


def anomaly_signals(user_token: str, user_id: str, lookback_days: int = 90, trace_id: str | None = None) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "flags": ["abnormal_spend"],
            "abnormal_spend": {"flag": True, "z_score": 2.8},
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "anomaly_signals_v1",
        {"user_id": user_id, "lookback_days": lookback_days, "trace_id": trace_id},
        user_token,
    )


def cashflow_forecast_tool(
    user_token: str,
    user_id: str,
    horizon: str = "weekly_12",
    scenario_overrides: Dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return _mock_forecast(horizon)
    return _call_gateway_tool(
        "cashflow_forecast_v1",
        {
            "user_id": user_id,
            "horizon": horizon,
            "scenario_overrides": scenario_overrides or {},
            "trace_id": trace_id,
        },
        user_token,
    )


def jar_allocation_suggest_tool(
    user_token: str,
    user_id: str,
    monthly_income_override: float | None = None,
    goal_overrides: list[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "allocations": [
                {"jar_name": "Bills", "amount": 8_000_000, "ratio": 0.25},
                {"jar_name": "Emergency", "amount": 6_000_000, "ratio": 0.2},
            ],
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "jar_allocation_suggest_v1",
        {
            "user_id": user_id,
            "monthly_income_override": monthly_income_override,
            "goal_overrides": goal_overrides or [],
            "trace_id": trace_id,
        },
        user_token,
    )


def risk_profile_non_investment_tool(
    user_token: str,
    user_id: str,
    lookback_days: int = 180,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "risk_band": "moderate",
            "cashflow_volatility": 0.4,
            "emergency_runway_months": 4,
            "overspend_propensity": 0.45,
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "risk_profile_non_investment_v1",
        {"user_id": user_id, "lookback_days": lookback_days, "trace_id": trace_id},
        user_token,
    )


def suitability_guard_tool(
    user_token: str,
    user_id: str,
    intent: str,
    requested_action: str,
    prompt: str,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        blocked = requested_action.lower() in {"buy", "sell", "execute"}
        return {
            "allow": not blocked,
            "decision": "deny_execution" if blocked else "allow",
            "required_disclaimer": "Educational guidance only. We do not provide investment advice.",
            "education_only": "invest" in intent.lower() or "invest" in prompt.lower(),
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "suitability_guard_v1",
        {
            "user_id": user_id,
            "intent": intent,
            "requested_action": requested_action,
            "prompt": prompt,
            "trace_id": trace_id,
        },
        user_token,
    )


def recurring_cashflow_detect_tool(
    user_token: str,
    user_id: str,
    lookback_months: int = 6,
    min_occurrence_months: int = 3,
    recurring_overrides: list[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "recurring_income": [],
            "recurring_expense": [{"counterparty_norm": "LANDLORD", "average_amount": 9000000}],
            "fixed_cost_ratio": 0.42,
            "drift_alerts": [],
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "recurring_cashflow_detect_v1",
        {
            "user_id": user_id,
            "lookback_months": lookback_months,
            "min_occurrence_months": min_occurrence_months,
            "recurring_overrides": recurring_overrides or [],
            "trace_id": trace_id,
        },
        user_token,
    )


def goal_feasibility_tool(
    user_token: str,
    user_id: str,
    target_amount: float | None = None,
    horizon_months: int | None = None,
    goal_id: str | None = None,
    seasonality: bool = True,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "required_monthly_saving": 8_000_000,
            "feasible": True,
            "gap_amount": 0,
            "grade": "A",
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "goal_feasibility_v1",
        {
            "user_id": user_id,
            "target_amount": target_amount,
            "horizon_months": horizon_months,
            "goal_id": goal_id,
            "seasonality": seasonality,
            "trace_id": trace_id,
        },
        user_token,
    )


def what_if_scenario_tool(
    user_token: str,
    user_id: str,
    horizon_months: int = 12,
    seasonality: bool = True,
    goal: str = "maximize_savings",
    base_scenario_overrides: Dict[str, Any] | None = None,
    variants: list[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "scenario_comparison": [
                {"name": "base", "delta_vs_base": 0},
                {"name": "cut_discretionary_spend_15pct", "delta_vs_base": 5_000_000},
            ],
            "best_variant_by_goal": "cut_discretionary_spend_15pct",
            "base_total_net_p50": 40_000_000,
            "trace_id": "trc_mocked01",
        }
    return _call_gateway_tool(
        "what_if_scenario_v1",
        {
            "user_id": user_id,
            "horizon_months": horizon_months,
            "seasonality": seasonality,
            "goal": goal,
            "base_scenario_overrides": base_scenario_overrides or {},
            "variants": variants,
            "trace_id": trace_id,
        },
        user_token,
    )


# Legacy aliases retained for compatibility.
def sql_read_views(user_token: str, range_days: str, user_id: str = "demo-user") -> Dict[str, Any]:
    return spend_analytics(user_token, user_id=user_id, range_days=range_days)


def forecast_cashflow(user_token: str, range_days: str = "90d", user_id: str = "demo-user") -> Dict[str, Any]:
    horizon = "daily_30" if range_days == "30d" else "weekly_12"
    return cashflow_forecast_tool(user_token, user_id=user_id, horizon=horizon)


def forecast_cashflow_scenario(user_token: str, payload: Dict[str, Any], user_id: str = "demo-user") -> Dict[str, Any]:
    horizon = str(payload.get("horizon") or payload.get("horizon_months") or "weekly_12")
    if horizon not in {"daily_30", "weekly_12"}:
        horizon = "weekly_12"
    return cashflow_forecast_tool(
        user_token,
        user_id=user_id,
        horizon=horizon,
        scenario_overrides=payload.get("scenario_overrides", {}),
        trace_id=payload.get("trace_id"),
    )


def forecast_runway(user_token: str, payload: Dict[str, Any], user_id: str = "demo-user") -> Dict[str, Any]:
    forecast = payload.get("forecast") or {}
    points = forecast.get("points") or forecast.get("monthly_forecast") or []
    cash = float(payload.get("cash_buffer") or 0)
    periods = 0
    for point in points:
        periods += 1
        cash += float(point.get("p50") or 0)
        if cash < 0:
            break
    return {
        "runway_periods": periods,
        "risk_flags": ["runway_below_threshold"] if cash < 0 else [],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
    }


def decision_savings_goal(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    forecast = payload.get("forecast") or {}
    points = forecast.get("points") or []
    target = float(payload.get("target_amount") or 0)
    horizon = max(1, int(payload.get("horizon_months") or 1))
    projected = sum(max(0.0, float((points[idx].get("p50") if idx < len(points) else 0))) for idx in range(horizon))
    required = target / horizon
    feasible = projected >= target
    return {
        "metrics": {"required_monthly_saving": required, "projected_positive_cashflow": projected},
        "grade": "A" if feasible else "C",
        "reasons": ["Deterministic projection from cashflow_forecast_v1"],
        "guardrails": [],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
    }


def decision_house_affordability(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    monthly_income = float(payload.get("monthly_income") or 0)
    monthly_payment = float(payload.get("house_price") or 0) / max(1, int(payload.get("loan_years") or 1) * 12)
    dti = monthly_payment / monthly_income if monthly_income > 0 else 1.0
    return {
        "metrics": {"monthly_payment": monthly_payment, "DTI": dti},
        "grade": "A" if dti < 0.35 else ("B" if dti < 0.45 else "C"),
        "reasons": ["Approximation for compatibility path."],
        "guardrails": [],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
    }


def decision_investment_capacity(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "metrics": {"investable_low": 0, "investable_high": 0},
        "grade": "N/A",
        "reasons": ["Use suitability_guard_v1 + risk_profile_non_investment_v1 instead."],
        "guardrails": ["education_only=true"],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
        "education_only": True,
    }


def decision_what_if(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = str(payload.get("user_id") or "demo-user")
    return what_if_scenario_tool(
        user_token,
        user_id=user_id,
        horizon_months=int(payload.get("horizon_months") or 12),
        seasonality=bool(payload.get("seasonality", True)),
        goal=str(payload.get("goal") or "maximize_savings"),
        base_scenario_overrides=payload.get("base_scenario_overrides") or {},
        variants=payload.get("variants"),
        trace_id=payload.get("trace_id"),
    )


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
    if AGENTCORE_GATEWAY_TOOL_NAME:
        return AGENTCORE_GATEWAY_TOOL_NAME
    try:
        return _resolve_tool_name("retrieve_from_aws_kb", user_token)
    except Exception:
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
    except Exception as exc:
        return {"matches": [], "note": f"Gateway call failed: {exc}"}


def goals_get_set(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"status": "mocked", "payload": payload}
    return _request_json("POST", "/goals", user_token, payload=payload, timeout=10)


def notifications_send(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"status": "mocked", "payload": payload}
    return _request_json("POST", "/notifications", user_token, payload=payload, timeout=10)


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
