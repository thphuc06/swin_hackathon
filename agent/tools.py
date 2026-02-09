from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict
from urllib.parse import urlparse

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import (
    AGENTCORE_GATEWAY_ENDPOINT,
    AGENTCORE_GATEWAY_TOOL_NAME,
    BACKEND_API_BASE,
    BEDROCK_KB_ID,
    USE_LOCAL_MOCKS,
)

logger = logging.getLogger(__name__)

# Tool registry cache (initialized at startup)
_resolved_tool_names: Dict[str, str] = {}
_tool_schemas: Dict[str, Dict[str, Any]] = {}  # Maps tool name -> full tool definition
_registry_initialized: bool = False


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _is_local_backend() -> bool:
    try:
        host = urlparse(BACKEND_API_BASE).hostname or ""
    except ValueError:
        host = ""
    return host in {"localhost", "127.0.0.1"} or host.endswith(".local")


def _should_use_local_mocks() -> bool:
    # Strict guard: mock data is only allowed for offline localhost development.
    if not USE_LOCAL_MOCKS:
        return False
    if not _is_local_backend():
        return False
    if AGENTCORE_GATEWAY_ENDPOINT.strip():
        return False
    return True


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


@retry(
    retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _gateway_jsonrpc(payload: Dict[str, Any], user_token: str, call_id: str | None = None) -> Dict[str, Any]:
    """Call AgentCore Gateway with retry logic for transient errors.
    
    Retries up to 3 times with exponential backoff (1s, 2s, 4s) for:
    - Network errors (ConnectionError, Timeout)
    - 5xx server errors
    
    Does NOT retry:
    - 4xx validation errors
    - Business logic errors
    """
    endpoint = _gateway_endpoint()
    if not endpoint:
        raise RuntimeError("AGENTCORE_GATEWAY_ENDPOINT not configured")
    
    log_ctx = {"call_id": call_id or "unknown", "method": payload.get("method")}
    
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=_auth_headers(user_token),
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            logger.warning("Gateway error: %s call_id=%s", data["error"], call_id)
            raise RuntimeError(f"Gateway tool error: {data['error']}")
        return data
    except requests.exceptions.HTTPError as exc:
        # Don't retry 4xx errors (client errors)
        if exc.response is not None and 400 <= exc.response.status_code < 500:
            logger.warning("Gateway client error: %s call_id=%s", exc, call_id)
            raise
        # Retry 5xx errors
        logger.warning("Gateway server error, will retry: %s call_id=%s", exc, call_id)
        raise


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


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned[key] = _drop_none(item)
        return cleaned
    if isinstance(value, list):
        return [_drop_none(item) for item in value if item is not None]
    return value


def initialize_tool_registry(user_token: str) -> Dict[str, Any]:
    """Initialize tool registry at startup by calling tools/list once.
    
    Populates:
    - _resolved_tool_names: Maps base_name -> full_name
    - _tool_schemas: Maps base_name -> full tool definition (with inputSchema)
    
    Returns:
        dict with 'count' and 'tools' for logging/monitoring
    """
    global _registry_initialized, _resolved_tool_names, _tool_schemas
    
    if _registry_initialized:
        return {"count": len(_resolved_tool_names), "tools": list(_resolved_tool_names.keys())}
    
    try:
        data = _gateway_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools-init", "method": "tools/list"},
            user_token,
            call_id="registry-init",
        )
        tools = (data.get("result") or {}).get("tools", [])
        
        for tool in tools:
            full_name = str(tool.get("name") or "")
            # Extract base name (remove server prefix if present)
            base_name = full_name.split("___")[-1] if "___" in full_name else full_name
            
            _resolved_tool_names[base_name] = full_name
            _tool_schemas[base_name] = tool
        
        _registry_initialized = True
        logger.info(
            "Tool registry initialized: %d tools loaded - %s",
            len(_resolved_tool_names),
            ", ".join(_resolved_tool_names.keys()),
        )
        
        return {"count": len(_resolved_tool_names), "tools": list(_resolved_tool_names.keys())}
    
    except Exception as exc:
        logger.error("Failed to initialize tool registry: %s", exc)
        # Don't fail startup - fall back to lazy loading
        return {"count": 0, "tools": [], "error": str(exc)}


def _resolve_tool_name(base_name: str, user_token: str) -> str:
    """Resolve tool name from cache (populated at startup).
    
    Falls back to lazy loading if registry not initialized.
    """
    if base_name in _resolved_tool_names:
        return _resolved_tool_names[base_name]
    
    # Fallback: lazy load if not in cache (shouldn't happen after startup)
    logger.warning("Tool %s not in registry, lazy loading (this should not happen)", base_name)
    
    data = _gateway_jsonrpc(
        {"jsonrpc": "2.0", "id": "tools-lazy", "method": "tools/list"},
        user_token,
        call_id=f"lazy-{base_name}",
    )
    tools = (data.get("result") or {}).get("tools", [])
    for tool in tools:
        name = str(tool.get("name") or "")
        if name == base_name or name.endswith(f"___{base_name}"):
            _resolved_tool_names[base_name] = name
            _tool_schemas[base_name] = tool
            return name
    raise RuntimeError(f"Tool {base_name} not found in AgentCore Gateway tools/list")


def _validate_tool_arguments(base_name: str, arguments: Dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate tool arguments against cached inputSchema (client-side validation).
    
    Returns:
        (is_valid, errors) tuple
    """
    if base_name not in _tool_schemas:
        # No schema available, skip validation
        return True, []
    
    tool_def = _tool_schemas[base_name]
    input_schema = tool_def.get("inputSchema")
    
    if not input_schema or not isinstance(input_schema, dict):
        # No schema to validate against
        return True, []
    
    try:
        import jsonschema
        jsonschema.validate(instance=arguments, schema=input_schema)
        return True, []
    except jsonschema.ValidationError as exc:
        return False, [str(exc.message)]
    except jsonschema.SchemaError as exc:
        logger.warning("Invalid schema for tool %s: %s", base_name, exc)
        return True, []  # Skip validation if schema itself is invalid
    except Exception as exc:
        logger.warning("Validation error for tool %s: %s", base_name, exc)
        return True, []  # Skip validation on unexpected errors


def _call_gateway_tool(
    base_name: str,
    arguments: Dict[str, Any],
    user_token: str,
    *,
    call_id: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    """Call MCP tool via AgentCore Gateway with validation and retry logic.
    
    Args:
        base_name: Tool name (e.g., 'anomaly_signals_v1')
        arguments: Tool arguments to validate and send
        user_token: Authorization token
        call_id: Unique call ID for this invocation (for correlation)
        trace_id: Request-level trace ID (for request correlation)
    
    Returns:
        Parsed tool output as dict
    """
    call_id = call_id or str(uuid.uuid4())
    
    # Client-side JSON Schema validation (fail fast)
    is_valid, validation_errors = _validate_tool_arguments(base_name, arguments)
    if not is_valid:
        error_msg = f"Invalid arguments for {base_name}: {'; '.join(validation_errors)}"
        logger.warning(
            "Client-side validation failed: tool=%s call_id=%s trace_id=%s errors=%s",
            base_name,
            call_id,
            trace_id,
            validation_errors,
        )
        raise ValueError(error_msg)
    
    resolved_name = _resolve_tool_name(base_name, user_token)
    sanitized_arguments = _drop_none(arguments)
    
    payload = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": resolved_name, "arguments": sanitized_arguments},
    }
    
    logger.info(
        "Calling tool: %s call_id=%s trace_id=%s",
        base_name,
        call_id,
        trace_id,
    )
    
    data = _gateway_jsonrpc(payload, user_token, call_id=call_id)
    result = data.get("result") or {}
    
    if bool(result.get("isError")):
        content = result.get("content", [])
        detail = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    detail = item["text"].strip()
                    if detail:
                        break
        logger.warning(
            "Tool error: tool=%s call_id=%s trace_id=%s error=%s",
            base_name,
            call_id,
            trace_id,
            detail,
        )
        raise RuntimeError(f"Gateway tool error for {base_name}: {detail or 'unknown error'}")
    
    content = result.get("content", [])
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
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "spend_analytics_v1",
        {"user_id": user_id, "range": range_days, "trace_id": trace_id},
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def anomaly_signals(user_token: str, user_id: str, lookback_days: int = 90, trace_id: str | None = None) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "flags": ["abnormal_spend"],
            "abnormal_spend": {"flag": True, "z_score": 2.8},
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "anomaly_signals_v1",
        {"user_id": user_id, "lookback_days": lookback_days, "trace_id": trace_id},
        user_token,
        call_id=call_id,
        trace_id=trace_id,
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
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "cashflow_forecast_v1",
        {
            "user_id": user_id,
            "horizon": horizon,
            "scenario_overrides": scenario_overrides or {},
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
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
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "jar_allocation_suggest_v1",
        {
            "user_id": user_id,
            "monthly_income_override": monthly_income_override,
            "goal_overrides": goal_overrides or [],
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
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
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "risk_profile_non_investment_v1",
        {"user_id": user_id, "lookback_days": lookback_days, "trace_id": trace_id},
        user_token,
        call_id=call_id,
        trace_id=trace_id,
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
        action = (requested_action or "").strip().lower()
        blocked_execution = action in {"buy", "sell", "execute", "trade", "order"}
        blocked_recommendation = action in {"recommend_buy", "recommend_sell", "recommend_trade"}
        blocked = blocked_execution or blocked_recommendation
        decision = "allow"
        refusal_message = ""
        if blocked_execution:
            decision = "deny_execution"
            refusal_message = "I cannot execute buy/sell actions. I can provide educational guidance only."
        elif blocked_recommendation:
            decision = "deny_recommendation"
            refusal_message = (
                "I cannot provide buy/sell recommendations. "
                "I can help with cashflow, budgeting, and non-investment risk planning."
            )
        return {
            "allow": not blocked,
            "decision": decision,
            "reason_codes": (
                ["execution_blocked", "education_only_policy"]
                if blocked_execution
                else ["investment_recommendation_blocked", "education_only_policy"]
                if blocked_recommendation
                else ["non_investment_intent"]
            ),
            "refusal_message": refusal_message,
            "required_disclaimer": "Educational guidance only. We do not provide investment advice.",
            "education_only": "invest" in intent.lower() or "invest" in prompt.lower(),
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
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
        call_id=call_id,
        trace_id=trace_id,
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
    call_id = str(uuid.uuid4())
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
        call_id=call_id,
        trace_id=trace_id,
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
    call_id = str(uuid.uuid4())
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
        call_id=call_id,
        trace_id=trace_id,
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
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "what_if_scenario_v1",
        {
            "user_id": user_id,
            "horizon_months": horizon_months,
            "seasonality": seasonality,
            "goal": goal,
            "base_scenario_overrides": base_scenario_overrides or {},
            "variants": variants or [],
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
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


def kb_retrieve(query: str, filters: Dict[str, str], user_token: str = "", trace_id: str | None = None) -> Dict[str, Any]:
    if not BEDROCK_KB_ID:
        return {"matches": [], "note": "KB not configured"}
    if not AGENTCORE_GATEWAY_ENDPOINT:
        return {"matches": [], "note": "Gateway not configured"}
    
    call_id = str(uuid.uuid4())
    tool_name = _resolve_kb_tool_name(user_token)
    payload = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"query": query, "knowledgeBaseId": BEDROCK_KB_ID, "n": 3},
        },
    }
    
    logger.info(
        "KB retrieve: query=%s call_id=%s trace_id=%s",
        query[:50] + "..." if len(query) > 50 else query,
        call_id,
        trace_id,
    )
    
    try:
        data = _gateway_jsonrpc(payload, user_token, call_id=call_id)
        content = (data.get("result") or {}).get("content", [])
        parsed = _parse_kb_content(content)
        parsed["filters"] = filters
        return parsed
    except Exception as exc:
        logger.warning("KB retrieve failed: call_id=%s trace_id=%s error=%s", call_id, trace_id, exc)
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
