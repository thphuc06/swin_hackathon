from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from planner_agent.contracts import (
    AgentResultEnvelope,
    ErrorItem,
    PlannerNextAction,
    PlannerRecommendation,
    PlannerResult,
    SpecialistRequestEnvelope,
    WarningItem,
)
from planner_agent.finance.data import fetch_profiles
from planner_agent.finance.supabase_rest import get_supabase_client
from planner_agent.policy import build_tool_plan
from planner_agent.prompts import SYSTEM_PROMPT, build_user_message
from planner_agent.reporting import build_standardized_contract, build_standardized_runtime_metadata
from planner_agent.timeframe import derive_timeframe_hint
from planner_agent.tool_router import PlannerContext, build_tools, invoke_finance_tool, resolve_timeframe_defaults
from planner_agent.utils import extract_json_object

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "v1"
AGENT_ID = "planner"
TOOL_NAME = "run_planner_agent_v1"
VALID_APP_ENVS = {"local", "demo", "staging", "prod"}
DEPLOYED_APP_ENVS = {"staging", "prod"}
VALID_PLANNER_EXECUTION_MODES = {"deterministic", "model", "auto"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _planner_model_id() -> str:
    return str(os.getenv("PLANNER_MODEL_ID") or os.getenv("BEDROCK_MODEL_ID") or "").strip()


def _app_env() -> str:
    raw = str(os.getenv("APP_ENV") or "").strip().lower()
    if not raw:
        return "local"
    if raw not in VALID_APP_ENVS:
        raise RuntimeError("APP_ENV must be one of: local, demo, staging, prod.")
    return raw


def _bedrock_region() -> str:
    region = str(os.getenv("AWS_REGION") or "").strip()
    if region:
        return region
    if _app_env() in DEPLOYED_APP_ENVS:
        raise RuntimeError("AWS_REGION must be explicitly set for planner runtime in staging/prod.")
    return "us-east-1"


def _planner_execution_mode() -> str:
    app_env = _app_env()
    raw_mode = str(os.getenv("PLANNER_EXECUTION_MODE") or "").strip().lower()
    legacy_stub = _env_bool("PLANNER_STUB_MODE", False)

    if raw_mode:
        if raw_mode not in VALID_PLANNER_EXECUTION_MODES:
            raise RuntimeError("PLANNER_EXECUTION_MODE must be one of: deterministic, model, auto.")
        if app_env in DEPLOYED_APP_ENVS and raw_mode == "auto":
            raise RuntimeError("PLANNER_EXECUTION_MODE=auto is not allowed in staging/prod. Use deterministic or model.")
        if legacy_stub and raw_mode != "deterministic":
            raise RuntimeError("PLANNER_STUB_MODE=true conflicts with PLANNER_EXECUTION_MODE unless mode=deterministic.")
        return raw_mode

    if app_env in DEPLOYED_APP_ENVS:
        return "deterministic"
    if legacy_stub:
        return "deterministic"
    return "auto"


def _strands_available() -> bool:
    try:
        import strands  # noqa: F401
        from strands.models import BedrockModel  # noqa: F401
    except Exception:
        return False
    return True


def _build_model():
    if not _planner_model_id() or not _strands_available():
        return None
    from strands.models import BedrockModel

    return BedrockModel(
        model_id=_planner_model_id(),
        region_name=_bedrock_region(),
        temperature=_env_float("PLANNER_TEMPERATURE", 0.2),
        max_tokens=4096,
    )


def _build_agent(context: PlannerContext):
    model = _build_model()
    if model is None:
        return None
    from strands import Agent

    return Agent(model=model, tools=build_tools(context), system_prompt=SYSTEM_PROMPT)


def _tool_warning(code: str, message: str, severity: str = "warn") -> WarningItem:
    return WarningItem(code=code, message=message, severity=severity)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _append_warning_once(warnings: List[WarningItem], code: str, message: str, severity: str = "warn") -> None:
    if any(item.code == code for item in warnings):
        return
    warnings.append(_tool_warning(code, message, severity))


def _tool_signal_context(tool_output: Dict[str, Any]) -> Dict[str, Any]:
    trust = tool_output.get("trust") if isinstance(tool_output.get("trust"), dict) else {}
    agent_use = tool_output.get("agent_use") if isinstance(tool_output.get("agent_use"), dict) else {}
    caps_applied = trust.get("caps_applied") if isinstance(trust.get("caps_applied"), list) else []
    return {
        "trust_score": _safe_float(trust.get("trust_score")),
        "trust_level": str(trust.get("trust_level") or "").strip().lower(),
        "usage_mode": str(agent_use.get("usage_mode") or "").strip().lower(),
        "monitoring_status": str(agent_use.get("monitoring_status") or "").strip().lower(),
        "human_feedback_recommended": bool(agent_use.get("human_feedback_recommended")),
        "caps_applied": [str(item).strip() for item in caps_applied if str(item).strip()],
    }


def _tool_reason_codes(tool_output: Dict[str, Any]) -> set[str]:
    reliability = tool_output.get("reliability") if isinstance(tool_output.get("reliability"), dict) else {}
    reason_codes = reliability.get("reason_codes") if isinstance(reliability.get("reason_codes"), list) else []
    return {str(item).strip() for item in reason_codes if str(item).strip()}


def _tool_validation_value(tool_output: Dict[str, Any], key: str) -> Any:
    validation = tool_output.get("validation") if isinstance(tool_output.get("validation"), dict) else {}
    return validation.get(key)


def _tool_has_no_recent_transactions(tool_output: Dict[str, Any]) -> bool:
    if "no_transactions_in_window" in _tool_reason_codes(tool_output):
        return True
    tx_count = _safe_float(_tool_validation_value(tool_output, "tx_count"))
    return tx_count == 0


def _requires_cautious_use(signal: Dict[str, Any]) -> bool:
    usage_mode = str(signal.get("usage_mode") or "").strip().lower()
    monitoring_status = str(signal.get("monitoring_status") or "").strip().lower()
    return usage_mode in {"advisory_only", "abstain"} or monitoring_status == "alert"


def _format_signal_suffix(signal: Dict[str, Any]) -> str:
    trust_level = str(signal.get("trust_level") or "").strip().lower()
    usage_mode = str(signal.get("usage_mode") or "").strip().lower()
    parts = []
    if trust_level:
        parts.append(f"trust={trust_level}")
    if usage_mode:
        parts.append(f"usage={usage_mode}")
    return f" ({', '.join(parts)})" if parts else ""


def _run_deterministic_planner(
    request: SpecialistRequestEnvelope,
    context: PlannerContext,
) -> Tuple[PlannerResult, List[WarningItem], str]:
    warnings: List[WarningItem] = []
    supabase = context.supabase_client
    if not supabase.configured:
        warnings.append(
            _tool_warning(
                "supabase_not_configured",
                "Supabase is not configured, so planner returned policy-first guidance without finance data.",
                "info",
            )
        )
        result = PlannerResult(
            summary="Planner returned a local deterministic response without finance data connectivity.",
            key_facts=[
                "The planner is running in-process behind run_planner_agent_v1.",
                "Finance MCP is not required for this execution path.",
            ],
            recommendations=[
                PlannerRecommendation(
                    title="Connect Supabase for grounded planning",
                    rationale="The planner can call internal finance modules directly once SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are available.",
                    priority="high",
                    expected_impact="Adds spend, forecast, goal, and risk grounding to the plan.",
                )
            ],
            next_actions=[
                PlannerNextAction(
                    action="Provide finance data credentials or seed a local dataset",
                    owner="platform",
                    timeframe="next",
                )
            ],
            warnings=warnings,
            tool_trace=[],
        )
        return result, warnings, "partial"

    tool_results: Dict[str, Dict[str, Any]] = {}
    for tool_name, kwargs in build_tool_plan(request, context):
        try:
            tool_results[tool_name] = invoke_finance_tool(context, tool_name, **kwargs)
        except Exception as exc:
            warnings.append(_tool_warning(f"{tool_name}_failed", str(exc)))

    summary_bits: List[str] = []
    key_facts: List[str] = []
    recommendations: List[PlannerRecommendation] = []
    next_actions: List[PlannerNextAction] = []
    recent_finance_data_insufficient = False

    spend = tool_results.get("spend_analytics_v1", {})
    if spend:
        total_spend = spend.get("total_spend")
        net_cashflow = spend.get("net_cashflow")
        spend_signal = _tool_signal_context(spend)
        spend_window_empty = _tool_has_no_recent_transactions(spend)
        recent_finance_data_insufficient = recent_finance_data_insufficient or spend_window_empty
        if spend_window_empty:
            summary_bits.append("The selected window does not contain enough recent transaction data for a grounded spend or cashflow summary.")
            key_facts.append("Recent transaction coverage in the selected window is insufficient for grounded spend analytics.")
            _append_warning_once(
                warnings,
                "recent_transaction_window_insufficient",
                "The selected analysis window does not contain enough recent transactions for grounded finance metrics.",
                "info",
            )
        else:
            if total_spend is not None:
                key_facts.append(f"Recent spend total: {total_spend}.")
            if net_cashflow is not None:
                key_facts.append(f"Observed net cashflow over the selected window: {net_cashflow}.")
                summary_bits.append(f"Net cashflow currently sits around {net_cashflow}.")
        if _requires_cautious_use(spend_signal):
            _append_warning_once(
                warnings,
                "spend_signal_cautious",
                "Spend analytics should be treated as directional guidance" + _format_signal_suffix(spend_signal) + ".",
                "info",
            )
        budget_drift = spend.get("budget_drift") if isinstance(spend.get("budget_drift"), list) else []
        over_budget = [row for row in budget_drift if isinstance(row, dict) and row.get("status") == "over"]
        if over_budget:
            first = over_budget[0]
            recommendations.append(
                PlannerRecommendation(
                    title=f"Correct drift in {str(first.get('scope_name') or 'your top budget')}",
                    rationale="Direct spend analytics show at least one budget scope is running above plan.",
                    priority="high",
                    expected_impact="Brings monthly spending back within the intended plan.",
                )
            )

    forecast = tool_results.get("cashflow_forecast_v1", {})
    if forecast:
        forecast_signal = _tool_signal_context(forecast)
        forecast_window_empty = _tool_has_no_recent_transactions(forecast) or recent_finance_data_insufficient
        band = forecast.get("confidence_band") if isinstance(forecast.get("confidence_band"), dict) else {}
        p50_avg = band.get("p50_avg")
        if p50_avg is not None and not forecast_window_empty:
            if _requires_cautious_use(forecast_signal):
                key_facts.append(f"Forecast midpoint cashflow: {p50_avg}, but it should be treated as directional guidance.")
                summary_bits.append("Forward cashflow is available, but current forecast trust suggests directional guidance only.")
            else:
                key_facts.append(f"Forecast average p50 cashflow: {p50_avg}.")
                summary_bits.append(f"Forward cashflow looks roughly {p50_avg} at the midpoint forecast.")
        if _requires_cautious_use(forecast_signal):
            severity = "warn" if forecast_signal["usage_mode"] == "abstain" else "info"
            _append_warning_once(
                warnings,
                "forecast_signal_cautious",
                "Forecast output should be used cautiously" + _format_signal_suffix(forecast_signal) + ".",
                severity,
            )

    allocation = tool_results.get("jar_allocation_suggest_v1", {})
    if allocation:
        allocation_signal = _tool_signal_context(allocation)
        allocation_window_empty = _tool_has_no_recent_transactions(allocation) or recent_finance_data_insufficient
        baseline_income = allocation.get("baseline_monthly_income")
        allocations = allocation.get("allocations") if isinstance(allocation.get("allocations"), list) else []
        if baseline_income is not None and not allocation_window_empty:
            key_facts.append(f"Baseline monthly income reference: {baseline_income}.")
        if allocations and not allocation_window_empty:
            first = allocations[0] if isinstance(allocations[0], dict) else {}
            rationale = f"Internal allocation logic prioritized {str(first.get('jar_name') or 'core needs')} first."
            if "forecast_trust_cap" in allocation_signal["caps_applied"] or _requires_cautious_use(allocation_signal):
                rationale = (
                    "Allocation guidance inherits current forecast uncertainty and should be used as a directional baseline"
                    + _format_signal_suffix(allocation_signal)
                    + "."
                )
            recommendations.append(
                PlannerRecommendation(
                    title="Apply a jar-based monthly allocation baseline",
                    rationale=rationale,
                    priority="medium",
                    expected_impact="Creates a more stable default budget plan.",
                )
            )

    goal = tool_results.get("goal_feasibility_v1", {})
    if goal:
        goal_signal = _tool_signal_context(goal)
        feasible = bool(goal.get("feasible"))
        goal_name = str(goal.get("goal_name") or "goal").strip()
        gap_amount = goal.get("gap_amount")
        key_facts.append(f"Goal feasibility for {goal_name}: {'feasible' if feasible else 'not yet feasible'}.")
        if "forecast_trust_cap" in goal_signal["caps_applied"]:
            key_facts.append(f"Goal feasibility for {goal_name} inherits current forecast uncertainty.")
        if not feasible:
            rationale = f"Current plan shows a projected gap of {gap_amount}."
            if _requires_cautious_use(goal_signal):
                rationale += " The gap estimate is useful for planning, but it should be treated directionally" + _format_signal_suffix(goal_signal) + "."
            recommendations.append(
                PlannerRecommendation(
                    title=f"Rework the timeline for {goal_name}",
                    rationale=rationale,
                    priority="high",
                    expected_impact="Improves the odds of reaching the target without cashflow stress.",
                )
            )

    anomaly = tool_results.get("anomaly_signals_v1", {})
    if anomaly:
        anomaly_signal = _tool_signal_context(anomaly)
        anomaly_window_empty = _tool_has_no_recent_transactions(anomaly)
        recent_finance_data_insufficient = recent_finance_data_insufficient or anomaly_window_empty
        flags = anomaly.get("flags") if isinstance(anomaly.get("flags"), list) else []
        if flags:
            key_facts.append(f"Detected anomaly flags: {', '.join(str(flag) for flag in flags[:3])}.")
            recommendations.append(
                PlannerRecommendation(
                    title="Review anomaly flags before locking the next budget",
                    rationale="Recent anomaly detection found unusual spend or income movement.",
                    priority="high",
                    expected_impact="Reduces the chance of planning from an unstable baseline.",
                )
            )
        feedback_request = anomaly.get("feedback_request") if isinstance(anomaly.get("feedback_request"), dict) else {}
        if bool(feedback_request.get("show_to_user")):
            next_actions.append(
                PlannerNextAction(
                    action="Confirm whether the recent anomaly alert is real, expected, or a false positive before finalizing the plan",
                    owner="user",
                    timeframe="before the next budget change",
                )
            )
            _append_warning_once(
                warnings,
                "anomaly_feedback_requested",
                "Recent anomaly output should be confirmed by the user before it is treated as ground truth"
                + _format_signal_suffix(anomaly_signal)
                + ".",
                "info",
            )
        elif _requires_cautious_use(anomaly_signal):
            _append_warning_once(
                warnings,
                "anomaly_signal_cautious",
                "Anomaly output should be treated cautiously" + _format_signal_suffix(anomaly_signal) + ".",
                "info",
            )

    risk = tool_results.get("risk_profile_non_investment_v1", {})
    if risk:
        risk_signal = _tool_signal_context(risk)
        risk_window_empty = _tool_has_no_recent_transactions(risk)
        recent_finance_data_insufficient = recent_finance_data_insufficient or risk_window_empty
        risk_band = str(risk.get("risk_band") or "").strip().lower()
        runway = risk.get("emergency_runway_months")
        if risk_window_empty or risk_band == "unknown":
            _append_warning_once(
                warnings,
                "risk_window_insufficient",
                "The selected window does not provide enough observed activity for a grounded non-investment risk classification.",
                "info",
            )
        if risk_band and risk_band != "unknown":
            key_facts.append(f"Non-investment risk band: {risk_band}.")
        if runway is not None and not risk_window_empty:
            key_facts.append(f"Emergency runway estimate: {runway} months.")
        if risk_band == "high":
            recommendations.append(
                PlannerRecommendation(
                    title="Increase emergency buffer before new commitments",
                    rationale="The internal risk model classified current non-investment risk as high.",
                    priority="high",
                    expected_impact="Improves resilience against negative cashflow swings.",
                )
            )
        if _requires_cautious_use(risk_signal):
            _append_warning_once(
                warnings,
                "risk_signal_cautious",
                "Risk profile output should be used cautiously" + _format_signal_suffix(risk_signal) + ".",
                "info",
            )

    recurring = tool_results.get("recurring_cashflow_detect_v1", {})
    if recurring:
        recurring_signal = _tool_signal_context(recurring)
        alerts = recurring.get("drift_alerts") if isinstance(recurring.get("drift_alerts"), list) else []
        if alerts:
            next_actions.append(
                PlannerNextAction(
                    action="Review recurring bill drift and cancel or renegotiate the largest mover",
                    owner="user",
                    timeframe="this month",
                )
            )
        if _requires_cautious_use(recurring_signal):
            _append_warning_once(
                warnings,
                "recurring_signal_cautious",
                "Recurring cashflow detection should be treated as planning guidance" + _format_signal_suffix(recurring_signal) + ".",
                "info",
            )

    suitability = tool_results.get("suitability_guard_v1", {})
    if suitability:
        decision = str(suitability.get("decision") or "").strip()
        if decision:
            key_facts.append(f"Policy boundary for this request: {decision}.")
        if decision and decision != "pass":
            _append_warning_once(
                warnings,
                "policy_boundary_active",
                f"Planner response is constrained by policy decision={decision}.",
                "info",
            )

    if not summary_bits:
        summary_bits.append("Planner completed with internal deterministic finance reasoning.")
    if not recommendations:
        if recent_finance_data_insufficient:
            recommendations.append(
                PlannerRecommendation(
                    title="Sync recent transactions before relying on this planning window",
                    rationale="The selected window does not currently contain enough recent transaction activity for grounded spend and cashflow guidance.",
                    priority="high",
                    expected_impact="Improves the planner baseline and reduces low-confidence zero-value summaries.",
                )
            )
        else:
            recommendations.append(
                PlannerRecommendation(
                    title="Use the grounded planner baseline for the next month",
                    rationale="The planner now executes locally with direct finance-module access and can be iterated without extra service hops.",
                    priority="medium",
                    expected_impact="Keeps the architecture shallow while preserving grounded planning behavior.",
                )
            )
    if not next_actions:
        if recent_finance_data_insufficient:
            next_actions.append(
                PlannerNextAction(
                    action="Sync recent transactions, then re-run the planner for the same analysis window",
                    owner="user",
                    timeframe="after the next sync",
                )
            )
        else:
            next_actions.append(
                PlannerNextAction(
                    action="Re-run the planner after your next transaction sync to refresh the budget baseline",
                    owner="user",
                    timeframe="next sync",
                )
            )

    status = "ok" if tool_results else "partial"
    result = PlannerResult(
        summary=" ".join(summary_bits),
        key_facts=key_facts,
        recommendations=recommendations,
        next_actions=next_actions,
        warnings=warnings,
        tool_trace=context.tool_trace,
    )
    return result, warnings, status


def _normalize_result(raw: Dict[str, Any], context: PlannerContext, fallback_summary: str) -> PlannerResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    if not data.get("summary"):
        data["summary"] = fallback_summary or "Planner completed."
    data.setdefault("key_facts", [])
    data.setdefault("recommendations", [])
    data.setdefault("next_actions", [])
    data.setdefault("citations", [])
    data.setdefault("warnings", [])
    data["tool_trace"] = context.tool_trace
    return PlannerResult.model_validate(data)


def _run_model_planner(
    request: SpecialistRequestEnvelope,
    context: PlannerContext,
) -> Tuple[PlannerResult, List[WarningItem], str]:
    agent = _build_agent(context)
    if agent is None:
        return _run_deterministic_planner(request, context)

    user_message = build_user_message(
        request.request.prompt,
        {
            "user_context": request.request.user_context,
            "goals": request.request.goals,
            "session_summary": request.request.session_summary,
            "policy_flags": request.request.policy_flags,
            "hints": context.timeframe_hint.as_prompt_hints(),
            "requested_outputs": [],
            "trace_id": request.correlation.trace_id,
        },
    )
    result = agent(user_message)
    text = str(result)
    parsed = extract_json_object(text)
    warnings: List[WarningItem] = []
    if parsed is None:
        warnings.append(_tool_warning("planner_parse", "Planner output was not valid JSON."))
        return _run_deterministic_planner(request, context)
    return _normalize_result(parsed, context, parsed.get("summary", "")), warnings, "ok"


def run_planner(payload: Dict[str, Any] | SpecialistRequestEnvelope) -> Dict[str, Any]:
    request = payload if isinstance(payload, SpecialistRequestEnvelope) else SpecialistRequestEnvelope.model_validate(payload)
    timeframe_hint = derive_timeframe_hint(request.request.prompt, request.request.user_context)
    context = PlannerContext(
        actor=request.actor,
        correlation=request.correlation,
        trace_context={
            "trace_id": request.correlation.trace_id,
            "session_id": request.correlation.session_id,
            "agent_name": AGENT_ID,
            "tool_name": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "request_timestamp": request.correlation.request_timestamp,
        },
        supabase_client=get_supabase_client(),
        timeframe_hint=timeframe_hint,
    )

    execution_mode = "unknown"
    try:
        execution_mode = _planner_execution_mode()
        if execution_mode == "deterministic":
            planner_result, warnings, status = _run_deterministic_planner(request, context)
        elif execution_mode == "model":
            planner_result, warnings, status = _run_model_planner(request, context)
        else:
            if _planner_model_id():
                planner_result, warnings, status = _run_model_planner(request, context)
            else:
                planner_result, warnings, status = _run_deterministic_planner(request, context)

        profile: Dict[str, Any] = {}
        if context.supabase_client.configured and hasattr(context.supabase_client, "fetch_rows"):
            try:
                profiles = fetch_profiles(context.supabase_client, request.actor.user_id)
                if profiles:
                    profile = dict(profiles[0])
            except Exception as exc:
                logger.warning(
                    "planner_profile_lookup_failed trace_id=%s error=%s",
                    request.correlation.trace_id,
                    exc,
                )

        standardized_contract = build_standardized_contract(
            request=request,
            planner_result=planner_result,
            planner_status=status,
            tool_results=context.tool_results,
            profile=profile,
            runtime_metadata=build_standardized_runtime_metadata(
                request_id=request.correlation.request_id,
                runtime_source="planner_specialist",
                response_mode="planner_standardized_contract",
                response_reason_codes=[
                    f"planner_status:{status}",
                    f"planner_execution_mode:{execution_mode}",
                ],
            ),
        )

        envelope = AgentResultEnvelope(
            schema_version=SCHEMA_VERSION,
            agent_id=AGENT_ID,
            agent_version=str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0"),
            tool_name=TOOL_NAME,
            status=status,
            correlation=request.correlation,
            result=planner_result,
            summary=planner_result.summary,
            standardized_contract=standardized_contract,
            warnings=warnings,
            errors=[],
        )
        return envelope.model_dump(exclude_none=True)
    except Exception as exc:
        fallback_warning = _tool_warning("planner_exception", str(exc), "critical")
        fallback = PlannerResult(
            summary="Planner failed to run.",
            key_facts=[],
            recommendations=[],
            next_actions=[],
            citations=[],
            tool_trace=context.tool_trace,
            warnings=[fallback_warning],
        )
        standardized_contract = build_standardized_contract(
            request=request,
            planner_result=fallback,
            planner_status="error",
            tool_results=context.tool_results,
            profile={},
            runtime_metadata=build_standardized_runtime_metadata(
                request_id=request.correlation.request_id,
                runtime_source="planner_specialist",
                response_mode="planner_standardized_contract",
                response_reason_codes=[
                    "planner_exception",
                    f"planner_execution_mode:{execution_mode}",
                ],
            ),
        )
        envelope = AgentResultEnvelope(
            schema_version=SCHEMA_VERSION,
            agent_id=AGENT_ID,
            agent_version=str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0"),
            tool_name=TOOL_NAME,
            status="error",
            correlation=request.correlation,
            result=fallback,
            summary=fallback.summary,
            standardized_contract=standardized_contract,
            warnings=[fallback_warning],
            errors=[ErrorItem(code="planner_exception", message=str(exc), retryable=False)],
        )
        return envelope.model_dump(exclude_none=True)
