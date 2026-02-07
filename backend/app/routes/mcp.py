from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field, ValidationError

from app.services.auth import verify_jwt
from app.services.finance import (
    anomaly_signals,
    cashflow_forecast,
    jar_allocation_suggest,
    risk_profile_non_investment,
    spend_analytics,
    suitability_guard,
)

router = APIRouter(tags=["mcp"])


class SpendInput(BaseModel):
    user_id: str
    range: str = "30d"
    as_of: str | None = None
    trace_id: str | None = None


class AnomalyInput(BaseModel):
    user_id: str
    lookback_days: int = Field(default=90, ge=30, le=365)
    as_of: str | None = None
    trace_id: str | None = None


class ForecastInput(BaseModel):
    user_id: str
    horizon: str = Field(default="weekly_12", pattern=r"^(daily_30|weekly_12)$")
    scenario_overrides: Dict[str, Any] = {}
    as_of: str | None = None
    trace_id: str | None = None


class AllocationInput(BaseModel):
    user_id: str
    monthly_income_override: float | None = Field(default=None, ge=0)
    goal_overrides: list[Dict[str, Any]] | None = None
    as_of: str | None = None
    trace_id: str | None = None


class RiskInput(BaseModel):
    user_id: str
    lookback_days: int = Field(default=180, ge=60, le=720)
    as_of: str | None = None
    trace_id: str | None = None


class SuitabilityInput(BaseModel):
    user_id: str
    intent: str = ""
    requested_action: str = ""
    prompt: str = ""
    trace_id: str | None = None


TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "spend_analytics_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "range": {"type": "string", "enum": ["30d", "60d", "90d"], "default": "30d"},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "anomaly_signals_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "lookback_days": {"type": "integer", "default": 90},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "cashflow_forecast_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "horizon": {"type": "string", "enum": ["daily_30", "weekly_12"], "default": "weekly_12"},
            "scenario_overrides": {"type": "object"},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "jar_allocation_suggest_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "monthly_income_override": {"type": "number"},
            "goal_overrides": {"type": "array", "items": {"type": "object"}},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "risk_profile_non_investment_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "lookback_days": {"type": "integer", "default": 180},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "suitability_guard_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "intent": {"type": "string"},
            "requested_action": {"type": "string"},
            "prompt": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
}


TOOLS_LIST = [
    {
        "name": "spend_analytics_v1",
        "description": "Deterministic 30/60/90d spend analytics from SQL truth.",
        "inputSchema": TOOL_SCHEMAS["spend_analytics_v1"],
    },
    {
        "name": "anomaly_signals_v1",
        "description": "Deterministic anomaly signals for spend/income/category/runway risk.",
        "inputSchema": TOOL_SCHEMAS["anomaly_signals_v1"],
    },
    {
        "name": "cashflow_forecast_v1",
        "description": "Deterministic short-horizon cashflow forecast with confidence bands.",
        "inputSchema": TOOL_SCHEMAS["cashflow_forecast_v1"],
    },
    {
        "name": "jar_allocation_suggest_v1",
        "description": "Rule-based jar allocation suggestion from SQL behavior and goals.",
        "inputSchema": TOOL_SCHEMAS["jar_allocation_suggest_v1"],
    },
    {
        "name": "risk_profile_non_investment_v1",
        "description": "Non-investment risk profile from volatility/runway/overspend behavior.",
        "inputSchema": TOOL_SCHEMAS["risk_profile_non_investment_v1"],
    },
    {
        "name": "suitability_guard_v1",
        "description": "Suitability guard for education-only and unsafe action refusal.",
        "inputSchema": TOOL_SCHEMAS["suitability_guard_v1"],
    },
]


def _jsonrpc_ok(id_value: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_value, "result": result}


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": id_value, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


def _resolve_tool_name(name: str) -> str:
    if name in TOOL_SCHEMAS:
        return name
    if "___" in name:
        suffix = name.split("___")[-1]
        if suffix in TOOL_SCHEMAS:
            return suffix
    return name


def _resolve_user(authorization: str | None) -> Dict[str, Any]:
    return verify_jwt(authorization)


@router.get("/mcp")
def mcp_health() -> str:
    return "MCP endpoint ready. Use POST /mcp for JSON-RPC."


@router.post("/mcp")
def mcp_jsonrpc(payload: Dict[str, Any], authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    req_id = payload.get("id")
    method = payload.get("method")

    if payload.get("jsonrpc") != "2.0" or not method:
        return _jsonrpc_error(req_id, -32600, "Invalid Request")

    if method == "initialize":
        return _jsonrpc_ok(
            req_id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "finance-mcp-server", "version": "0.1.0"},
            },
        )

    if method == "tools/list":
        return _jsonrpc_ok(req_id, {"tools": TOOLS_LIST})

    if method != "tools/call":
        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    try:
        user = _resolve_user(authorization)
    except Exception as exc:
        return _jsonrpc_error(req_id, -32001, "Unauthorized", str(exc))

    params = payload.get("params") or {}
    requested_name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    tool_name = _resolve_tool_name(requested_name)

    try:
        if tool_name == "spend_analytics_v1":
            args = SpendInput.model_validate(arguments)
            result = spend_analytics(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                range_value=args.range,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "anomaly_signals_v1":
            args = AnomalyInput.model_validate(arguments)
            result = anomaly_signals(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                lookback_days=args.lookback_days,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "cashflow_forecast_v1":
            args = ForecastInput.model_validate(arguments)
            result = cashflow_forecast(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                horizon=args.horizon,
                scenario_overrides=args.scenario_overrides,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "jar_allocation_suggest_v1":
            args = AllocationInput.model_validate(arguments)
            result = jar_allocation_suggest(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                monthly_income_override=args.monthly_income_override,
                goal_overrides=args.goal_overrides,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "risk_profile_non_investment_v1":
            args = RiskInput.model_validate(arguments)
            result = risk_profile_non_investment(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                lookback_days=args.lookback_days,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "suitability_guard_v1":
            args = SuitabilityInput.model_validate(arguments)
            result = suitability_guard(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                intent=args.intent,
                requested_action=args.requested_action,
                prompt=args.prompt,
                trace_id=args.trace_id,
            )
        else:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {requested_name}")
    except ValidationError as exc:
        return _jsonrpc_error(req_id, -32602, "Invalid tool arguments", exc.errors())
    except PermissionError as exc:
        return _jsonrpc_error(req_id, -32003, "Forbidden", str(exc))
    except Exception as exc:
        return _jsonrpc_error(req_id, -32000, "Tool execution failed", str(exc))

    return _jsonrpc_ok(req_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
