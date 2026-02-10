from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field, ValidationError

from app.auth import verify_jwt
from app.finance import (
    anomaly_signals,
    cashflow_forecast,
    goal_feasibility,
    jar_allocation_suggest,
    recurring_cashflow_detect,
    risk_profile_non_investment,
    spend_analytics,
    suitability_guard,
    what_if_scenario,
)

router = APIRouter(tags=["mcp"])
logger = logging.getLogger(__name__)


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


class RecurringInput(BaseModel):
    user_id: str
    lookback_months: int = Field(default=6, ge=3, le=24)
    min_occurrence_months: int = Field(default=3, ge=2, le=12)
    recurring_overrides: list[Dict[str, Any]] = []
    drift_threshold_pct: float = Field(default=0.2, ge=0, le=2)
    as_of: str | None = None
    trace_id: str | None = None


class GoalFeasibilityInput(BaseModel):
    user_id: str
    target_amount: float | None = Field(default=None, ge=0)
    horizon_months: int | None = Field(default=None, ge=1, le=24)
    goal_id: str | None = None
    seasonality: bool = True
    as_of: str | None = None
    trace_id: str | None = None


class WhatIfInput(BaseModel):
    user_id: str
    horizon_months: int = Field(default=12, ge=1, le=24)
    seasonality: bool = True
    goal: str = "maximize_savings"
    base_scenario_overrides: Dict[str, Any] = {}
    variants: list[Dict[str, Any]] | None = None
    as_of: str | None = None
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
    "recurring_cashflow_detect_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "lookback_months": {"type": "integer", "default": 6},
            "min_occurrence_months": {"type": "integer", "default": 3},
            "recurring_overrides": {"type": "array", "items": {"type": "object"}},
            "drift_threshold_pct": {"type": "number", "default": 0.2},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "goal_feasibility_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "target_amount": {"type": "number"},
            "horizon_months": {"type": "integer"},
            "goal_id": {"type": "string"},
            "seasonality": {"type": "boolean", "default": True},
            "as_of": {"type": "string"},
            "trace_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    "what_if_scenario_v1": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "horizon_months": {"type": "integer", "default": 12},
            "seasonality": {"type": "boolean", "default": True},
            "goal": {"type": "string", "default": "maximize_savings"},
            "base_scenario_overrides": {"type": "object"},
            "variants": {"type": "array", "items": {"type": "object"}},
            "as_of": {"type": "string"},
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
    {
        "name": "recurring_cashflow_detect_v1",
        "description": "Detect recurring cashflows, fixed-cost ratio, and recurring drift signals.",
        "inputSchema": TOOL_SCHEMAS["recurring_cashflow_detect_v1"],
    },
    {
        "name": "goal_feasibility_v1",
        "description": "Assess goal feasibility from SQL history + deterministic forecast.",
        "inputSchema": TOOL_SCHEMAS["goal_feasibility_v1"],
    },
    {
        "name": "what_if_scenario_v1",
        "description": "Compare what-if cashflow variants against baseline and goal.",
        "inputSchema": TOOL_SCHEMAS["what_if_scenario_v1"],
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
        elif tool_name == "recurring_cashflow_detect_v1":
            args = RecurringInput.model_validate(arguments)
            result = recurring_cashflow_detect(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                lookback_months=args.lookback_months,
                min_occurrence_months=args.min_occurrence_months,
                recurring_overrides=args.recurring_overrides,
                drift_threshold_pct=args.drift_threshold_pct,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "goal_feasibility_v1":
            args = GoalFeasibilityInput.model_validate(arguments)
            result = goal_feasibility(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                target_amount=args.target_amount,
                horizon_months=args.horizon_months,
                goal_id=args.goal_id,
                seasonality=args.seasonality,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        elif tool_name == "what_if_scenario_v1":
            args = WhatIfInput.model_validate(arguments)
            result = what_if_scenario(
                auth_user_id=user.get("sub", ""),
                user_id=args.user_id,
                horizon_months=args.horizon_months,
                seasonality=args.seasonality,
                goal=args.goal,
                base_scenario_overrides=args.base_scenario_overrides,
                variants=args.variants,
                as_of=args.as_of,
                trace_id=args.trace_id,
            )
        else:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {requested_name}")
    except ValidationError as exc:
        return _jsonrpc_error(req_id, -32602, "Invalid tool arguments", exc.errors())
    except PermissionError as exc:
        return _jsonrpc_error(req_id, -32003, "Forbidden", str(exc))
    except Exception as exc:
        logger.exception("MCP tool execution failed: tool=%s error=%s", tool_name, exc)
        return _jsonrpc_error(
            req_id,
            -32000,
            "Tool execution failed",
            {"tool": tool_name, "error_type": type(exc).__name__, "message": str(exc)},
        )

    return _jsonrpc_ok(req_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
