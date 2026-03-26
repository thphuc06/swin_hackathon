from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence

from planner_agent.contracts import (
    PlannerHumanReadableContract,
    PlannerResult,
    PlannerStandardizedContract,
    SpecialistRequestEnvelope,
)
from planner_agent.finance.common import iso_utc, mean, safe_float
from planner_agent.policy import PLANNER_POLICY_VERSION, normalize_planner_intent


CONTRACT_SPEC_VERSION = "financial_advisory_contract_v1"
REPORT_SPEC_VERSION = "financial_advisory_txt_v1"
REPORT_TITLE = "Financial Advisory Report"
NOT_APPLICABLE = "not_applicable"
INSUFFICIENT_DATA = "insufficient_data"
SECTION_ORDER = [
    "HEADER",
    "EXECUTIVE_SUMMARY",
    "CORE_FINANCIAL_ANALYSIS",
    "PLANNER_CORE_COMPUTED_SIGNALS",
    "FINANCIAL_USAGE_INSIGHT",
    "STRATEGY_OPTIONS",
    "BANKING_SERVICE_RECOMMENDATIONS",
    "ACTIONABLE_NEXT_STEPS",
    "EVIDENCE_TOOL_GROUNDING",
    "RAW_METADATA",
]


def _planner_execution_mode_value() -> str:
    from planner_agent.agent import _planner_execution_mode

    return _planner_execution_mode()


def _value(value: Any) -> str:
    if value is None:
        return INSUFFICIENT_DATA
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _get(payload: Mapping[str, Any] | None, *path: str) -> Any:
    current: Any = payload or {}
    for part in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _tool_state(tool_output: Mapping[str, Any] | None) -> str:
    if not isinstance(tool_output, Mapping):
        return NOT_APPLICABLE
    reason_codes = _get(tool_output, "reliability", "reason_codes")
    if isinstance(reason_codes, list) and "no_transactions_in_window" in reason_codes:
        return INSUFFICIENT_DATA
    usage_mode = str(_get(tool_output, "agent_use", "usage_mode") or "").strip().lower()
    monitoring_status = str(_get(tool_output, "agent_use", "monitoring_status") or "").strip().lower()
    if usage_mode in {"advisory_only", "abstain"} or monitoring_status in {"watch", "alert"}:
        return "cautious"
    return "grounded"


def _tool_snapshot(tool_name: str, tool_output: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(tool_output, Mapping):
        return {"tool_name": tool_name, "status": NOT_APPLICABLE}
    return {
        "tool_name": tool_name,
        "status": _tool_state(tool_output),
        "confidence_score": _get(tool_output, "reliability", "confidence_score"),
        "confidence_level": _get(tool_output, "reliability", "confidence_level"),
        "reason_codes": _get(tool_output, "reliability", "reason_codes") or [],
        "components": _get(tool_output, "reliability", "components") or {},
        "trust_score": _get(tool_output, "trust", "trust_score"),
        "trust_level": _get(tool_output, "trust", "trust_level"),
        "usage_mode": _get(tool_output, "agent_use", "usage_mode"),
        "monitoring_status": _get(tool_output, "agent_use", "monitoring_status"),
        "caps_applied": _get(tool_output, "trust", "caps_applied") or [],
        "human_feedback_recommended": bool(_get(tool_output, "agent_use", "human_feedback_recommended")),
    }


def _first_window(tool_results: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
    for tool_name in (
        "spend_analytics_v1",
        "cashflow_forecast_v1",
        "anomaly_signals_v1",
        "risk_profile_non_investment_v1",
        "recurring_cashflow_detect_v1",
        "goal_feasibility_v1",
        "what_if_scenario_v1",
    ):
        tool_output = tool_results.get(tool_name)
        if isinstance(tool_output, Mapping) and isinstance(tool_output.get("window"), Mapping):
            return dict(tool_output["window"])
    return {"start": INSUFFICIENT_DATA, "end": INSUFFICIENT_DATA, "history_days": INSUFFICIENT_DATA}


def _overall_groundedness(tool_results: Mapping[str, Dict[str, Any]]) -> str:
    states = [_tool_state(tool_output) for tool_output in tool_results.values()]
    if not states:
        return INSUFFICIENT_DATA
    if all(state == "grounded" for state in states):
        return "grounded"
    if any(state == INSUFFICIENT_DATA for state in states):
        return "mixed_with_insufficient_data"
    return "mixed_cautious"


def _financial_stability(spend: Mapping[str, Any] | None, risk: Mapping[str, Any] | None, forecast: Mapping[str, Any] | None) -> str:
    if _tool_state(spend) == INSUFFICIENT_DATA:
        return INSUFFICIENT_DATA
    risk_band = str((risk or {}).get("risk_band") or "").strip().lower()
    runway = safe_float((risk or {}).get("emergency_runway_months"), None)
    probability_negative_net = safe_float((forecast or {}).get("probability_negative_net"), None)
    net_cashflow = safe_float((spend or {}).get("net_cashflow"), None)
    if risk_band == "high" or (runway is not None and runway < 3):
        return "fragile"
    if probability_negative_net is not None and probability_negative_net >= 0.5:
        return "fragile"
    if risk_band == "moderate" or (runway is not None and runway < 6):
        return "watch"
    if net_cashflow is not None and net_cashflow < 0:
        return "watch"
    return "stable"


def _planning_readiness(tool_results: Mapping[str, Dict[str, Any]], suitability: Mapping[str, Any] | None) -> str:
    decision = str((suitability or {}).get("decision") or "").strip().lower()
    if decision in {"deny_execution", "deny_recommendation"}:
        return "policy_constrained"
    states = [_tool_state(tool_output) for tool_output in tool_results.values()]
    if not states or any(state == INSUFFICIENT_DATA for state in states):
        return INSUFFICIENT_DATA
    if any(state == "cautious" for state in states):
        return "cautious"
    return "ready"


def _execution_readiness(suitability: Mapping[str, Any] | None) -> str:
    if not isinstance(suitability, Mapping):
        return NOT_APPLICABLE
    decision = str(suitability.get("decision") or "").strip().lower()
    if decision == "allow":
        return "allowed_within_policy"
    if decision == "education_only":
        return "education_only"
    if decision in {"deny_execution", "deny_recommendation"}:
        return "blocked_by_policy"
    return INSUFFICIENT_DATA


def _metric_sources() -> Dict[str, Any]:
    return {
        "observed_income_total": ["spend_analytics_v1.total_income"],
        "observed_expense_total": ["spend_analytics_v1.total_spend"],
        "observed_net_cashflow": ["spend_analytics_v1.net_cashflow"],
        "observed_baseline_monthly_income": ["jar_allocation_suggest_v1.baseline_monthly_income"],
        "observed_latest_buffer_balance": [
            "risk_profile_non_investment_v1.summary.balance_context.latest_balance",
            "goal_feasibility_v1.starting_balance_context.latest_balance",
            "what_if_scenario_v1.base_scenario.starting_balance_context.latest_balance",
        ],
        "computed_financial_stability_band": [
            "report_derived(risk_profile_non_investment_v1.risk_band, cashflow_forecast_v1.probability_negative_net, spend_analytics_v1.net_cashflow)"
        ],
        "observed_recurring_patterns": ["recurring_cashflow_detect_v1.*"],
        "observed_anomaly": ["anomaly_signals_v1.flags", "anomaly_signals_v1.transaction_outliers", "anomaly_signals_v1.runtime_alerts"],
        "computed_risk": ["risk_profile_non_investment_v1.*"],
        "computed_suitability": ["suitability_guard_v1.*"],
        "computed_goal_planning": ["goal_feasibility_v1.*", "jar_allocation_suggest_v1.allocations"],
        "computed_scenario": ["what_if_scenario_v1.*"],
        "planner_summary": ["run_planner_agent_v1.result.summary"],
    }


def _planner_metric_sources() -> Dict[str, Any]:
    return {
        "trust_core": ["<tool>.trust.* via finance.trust.build_trust"],
        "reliability": ["<tool>.reliability.* via finance.common.build_reliability"],
        "forecast_recalibration": [
            "cashflow_forecast_v1.validation.calibration_monitoring.recalibration",
            "goal_feasibility_v1.validation.calibration_monitoring",
            "what_if_scenario_v1.validation.calibration_monitoring",
        ],
        "anomaly_recalibration": ["anomaly_signals_v1.validation.calibration_monitoring.recalibration"],
        "native_uncertainty": ["<forecast-like tool>.model_evidence.native_uncertainty"],
        "planning_readiness": ["report_derived(<tool>.agent_use.usage_mode, <tool>.agent_use.monitoring_status, suitability_guard_v1.decision)"],
    }


def build_standardized_runtime_metadata(
    *,
    request_id: str | None = None,
    runtime_source: str = "planner_core_direct",
    response_mode: str | None = None,
    response_reason_codes: Sequence[str] | None = None,
) -> Dict[str, Any]:
    return {
        "request_id": str(request_id or f"req_{uuid.uuid4().hex[:10]}"),
        "runtime_source": runtime_source,
        "response_mode": response_mode or "standardized_txt_generator",
        "response_reason_codes": list(response_reason_codes or []),
        "generated_by": "planner_agent.reporting",
        "app_env": str(os.getenv("APP_ENV") or "local"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _human_readable_contract(planner_result: PlannerResult) -> PlannerHumanReadableContract:
    return PlannerHumanReadableContract(
        summary=planner_result.summary or INSUFFICIENT_DATA,
        key_facts=list(planner_result.key_facts),
        recommendations=list(planner_result.recommendations),
        next_actions=list(planner_result.next_actions),
        citations=list(planner_result.citations),
        warnings=list(planner_result.warnings),
    )


def _sections(
    *,
    request: SpecialistRequestEnvelope,
    planner_result: PlannerResult,
    planner_status: str,
    tool_results: Mapping[str, Dict[str, Any]],
    profile: Mapping[str, Any] | None,
    runtime_metadata: Mapping[str, Any] | None,
) -> Dict[str, Dict[str, Any]]:
    spend = tool_results.get("spend_analytics_v1")
    forecast = tool_results.get("cashflow_forecast_v1")
    allocation = tool_results.get("jar_allocation_suggest_v1")
    recurring = tool_results.get("recurring_cashflow_detect_v1")
    anomaly = tool_results.get("anomaly_signals_v1")
    risk = tool_results.get("risk_profile_non_investment_v1")
    suitability = tool_results.get("suitability_guard_v1")
    goal = tool_results.get("goal_feasibility_v1")
    scenario = tool_results.get("what_if_scenario_v1")
    window = _first_window(tool_results)
    planning_readiness = _planning_readiness(tool_results, suitability)

    tool_snapshots = {name: _tool_snapshot(name, result) for name, result in tool_results.items()}
    confidence_values = [safe_float(item.get("confidence_score"), None) for item in tool_snapshots.values() if item.get("confidence_score") is not None]
    trust_values = [safe_float(item.get("trust_score"), None) for item in tool_snapshots.values() if item.get("trust_score") is not None]
    top_category_share = safe_float((spend or {}).get("top_category_share"), 0.0)
    fixed_cost_ratio = safe_float((recurring or {}).get("fixed_cost_ratio"), 0.0)
    budget_drift = (spend or {}).get("budget_drift") if isinstance((spend or {}).get("budget_drift"), list) else []
    net_cashflow = safe_float((spend or {}).get("net_cashflow"), 0.0)
    risk_band = str((risk or {}).get("risk_band") or "").strip().lower()
    positive_signals: list[str] = []
    attention_signals: list[str] = []
    if net_cashflow >= 0:
        positive_signals.append("positive_observed_cashflow")
    else:
        attention_signals.append("negative_observed_cashflow")
    if not any(isinstance(item, Mapping) and item.get("status") == "over" for item in budget_drift):
        positive_signals.append("no_active_budget_overrun_detected")
    else:
        attention_signals.append("budget_overrun_detected")
    if fixed_cost_ratio >= 0.55:
        attention_signals.append("high_fixed_cost_ratio")
    elif recurring is not None:
        positive_signals.append("fixed_cost_ratio_not_elevated")
    if risk_band == "high":
        attention_signals.append("high_non_investment_risk")
    elif risk_band == "low":
        positive_signals.append("low_non_investment_risk")
    if top_category_share >= 0.45:
        attention_signals.append("concentrated_spend_distribution")

    service_recommendations: list[dict[str, Any]] = []
    if budget_drift:
        service_recommendations.append(
            {
                "service_category": "budget_controls_and_spend_limits",
                "status": "grounded",
                "confidence": _get(spend, "reliability", "confidence_level") or INSUFFICIENT_DATA,
                "grounded_by": ["spend_analytics_v1.budget_drift"],
                "why": "Budget drift is already present in the observed spending window.",
            }
        )
    anomaly_flags = (anomaly or {}).get("flags") if isinstance((anomaly or {}).get("flags"), list) else []
    if anomaly_flags:
        service_recommendations.append(
            {
                "service_category": "transaction_alerts_and_manual_verification",
                "status": "grounded",
                "confidence": _get(anomaly, "reliability", "confidence_level") or INSUFFICIENT_DATA,
                "grounded_by": ["anomaly_signals_v1.flags", "anomaly_signals_v1.feedback_request"],
                "why": "Recent anomaly signals suggest verification and monitoring should stay enabled.",
            }
        )
    runway = safe_float((risk or {}).get("emergency_runway_months"), None)
    if runway is not None and runway != 999 and runway < 6:
        service_recommendations.append(
            {
                "service_category": "emergency_buffer_support",
                "status": "grounded",
                "confidence": _get(risk, "reliability", "confidence_level") or INSUFFICIENT_DATA,
                "grounded_by": ["risk_profile_non_investment_v1.emergency_runway_months"],
                "why": "Short runway makes liquidity support more relevant than expansion.",
            }
        )
    goal_gap = safe_float((goal or {}).get("gap_amount"), None)
    if goal_gap is not None and goal_gap > 0:
        service_recommendations.append(
            {
                "service_category": "goal_savings_automation",
                "status": "grounded",
                "confidence": _get(goal, "reliability", "confidence_level") or INSUFFICIENT_DATA,
                "grounded_by": ["goal_feasibility_v1.gap_amount", "goal_feasibility_v1.probability_of_success"],
                "why": "The goal plan shows a measurable gap under current projected cashflow.",
            }
        )

    return {
        "HEADER": {
            "report_spec_version": REPORT_SPEC_VERSION,
            "report_title": REPORT_TITLE,
            "generated_at": iso_utc(),
            "session_id": request.correlation.session_id,
            "trace_id": request.correlation.trace_id,
            "user_display_name": str((profile or {}).get("display_name") or INSUFFICIENT_DATA),
            "analysis_window_label": f"{window.get('start')}..{window.get('end')}" if window.get("start") != INSUFFICIENT_DATA else INSUFFICIENT_DATA,
            "analysis_window_start": window.get("start", INSUFFICIENT_DATA),
            "analysis_window_end": window.get("end", INSUFFICIENT_DATA),
            "analysis_window_days": window.get("history_days", INSUFFICIENT_DATA),
            "planner_intent": normalize_planner_intent(request.request.intent),
            "planner_policy_version": PLANNER_POLICY_VERSION,
            "execution_mode": _planner_execution_mode_value(),
            "planner_status": planner_status,
            "runtime_source": str((runtime_metadata or {}).get("runtime_source") or "planner_core_direct"),
        },
        "EXECUTIVE_SUMMARY": {
            "observed_income_total": (spend or {}).get("total_income", INSUFFICIENT_DATA),
            "observed_expense_total": (spend or {}).get("total_spend", INSUFFICIENT_DATA),
            "observed_net_cashflow": (spend or {}).get("net_cashflow", INSUFFICIENT_DATA),
            "observed_baseline_monthly_income": (allocation or {}).get("baseline_monthly_income", INSUFFICIENT_DATA),
            "observed_latest_buffer_balance": _get(risk, "summary", "balance_context", "latest_balance")
            or _get(goal, "starting_balance_context", "latest_balance")
            or _get(scenario, "base_scenario", "starting_balance_context", "latest_balance")
            or INSUFFICIENT_DATA,
            "computed_financial_stability_band": _financial_stability(spend, risk, forecast),
            "computed_risk_band": (risk or {}).get("risk_band", INSUFFICIENT_DATA),
            "computed_planning_readiness": planning_readiness,
            "inferred_summary_text": planner_result.summary or INSUFFICIENT_DATA,
        },
        "CORE_FINANCIAL_ANALYSIS": {
            "observed_income": {
                "status": _tool_state(spend),
                "total_income": (spend or {}).get("total_income", INSUFFICIENT_DATA),
                "baseline_monthly_income": (allocation or {}).get("baseline_monthly_income", INSUFFICIENT_DATA),
            },
            "observed_expenses": {
                "status": _tool_state(spend),
                "total_spend": (spend or {}).get("total_spend", INSUFFICIENT_DATA),
                "essential_vs_discretionary_breakdown": (spend or {}).get("essential_vs_discretionary_breakdown", INSUFFICIENT_DATA),
                "category_breakdown": (spend or {}).get("category_breakdown", INSUFFICIENT_DATA),
                "top_merchants": (spend or {}).get("top_merchants", INSUFFICIENT_DATA),
                "budget_drift": (spend or {}).get("budget_drift", INSUFFICIENT_DATA),
            },
            "observed_cashflow": {
                "status": _tool_state(spend),
                "net_cashflow": (spend or {}).get("net_cashflow", INSUFFICIENT_DATA),
                "forecast_probability_negative_net": (forecast or {}).get("probability_negative_net", INSUFFICIENT_DATA),
                "forecast_confidence_band": (forecast or {}).get("confidence_band", INSUFFICIENT_DATA),
            },
            "observed_recurring_patterns": {
                "status": _tool_state(recurring),
                "recurring_income": (recurring or {}).get("recurring_income", NOT_APPLICABLE if recurring is None else INSUFFICIENT_DATA),
                "recurring_expense": (recurring or {}).get("recurring_expense", NOT_APPLICABLE if recurring is None else INSUFFICIENT_DATA),
                "fixed_cost_ratio": (recurring or {}).get("fixed_cost_ratio", NOT_APPLICABLE if recurring is None else INSUFFICIENT_DATA),
                "drift_alerts": (recurring or {}).get("drift_alerts", NOT_APPLICABLE if recurring is None else INSUFFICIENT_DATA),
            },
            "observed_anomaly": {
                "status": _tool_state(anomaly),
                "flags": (anomaly or {}).get("flags", NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
                "runtime_alerts": (anomaly or {}).get("runtime_alerts", NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
                "transaction_outliers": (anomaly or {}).get("transaction_outliers", NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
                "feedback_request": (anomaly or {}).get("feedback_request", NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
            },
            "computed_risk": {
                "status": _tool_state(risk),
                "risk_band": (risk or {}).get("risk_band", NOT_APPLICABLE if risk is None else INSUFFICIENT_DATA),
                "risk_score": (risk or {}).get("risk_score", NOT_APPLICABLE if risk is None else INSUFFICIENT_DATA),
                "emergency_runway_months": (risk or {}).get("emergency_runway_months", NOT_APPLICABLE if risk is None else INSUFFICIENT_DATA),
                "signals": (risk or {}).get("signals", NOT_APPLICABLE if risk is None else INSUFFICIENT_DATA),
                "stress_summary": (risk or {}).get("stress_summary", NOT_APPLICABLE if risk is None else INSUFFICIENT_DATA),
            },
            "computed_suitability": {
                "status": _tool_state(suitability),
                "decision": (suitability or {}).get("decision", NOT_APPLICABLE if suitability is None else INSUFFICIENT_DATA),
                "allow": (suitability or {}).get("allow", NOT_APPLICABLE if suitability is None else INSUFFICIENT_DATA),
                "matched_rules": (suitability or {}).get("matched_rules", NOT_APPLICABLE if suitability is None else INSUFFICIENT_DATA),
                "decision_explanation": (suitability or {}).get("decision_explanation", NOT_APPLICABLE if suitability is None else INSUFFICIENT_DATA),
            },
            "computed_affordability": {
                "status": NOT_APPLICABLE,
                "reason": "No first-class affordability tool is wired into the current planner path.",
            },
            "computed_goal_planning": {
                "status": _tool_state(goal) if goal is not None else NOT_APPLICABLE,
                "goal_name": (goal or {}).get("goal_name", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                "probability_of_success": (goal or {}).get("probability_of_success", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                "required_monthly_saving": (goal or {}).get("required_monthly_saving", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                "gap_amount": (goal or {}).get("gap_amount", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                "grade": (goal or {}).get("grade", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                "allocations": (allocation or {}).get("allocations", NOT_APPLICABLE if allocation is None else INSUFFICIENT_DATA),
            },
            "computed_scenario": {
                "status": _tool_state(scenario) if scenario is not None else NOT_APPLICABLE,
                "recommended_variant": (scenario or {}).get("recommended_variant", NOT_APPLICABLE if scenario is None else INSUFFICIENT_DATA),
                "scenario_comparison": (scenario or {}).get("scenario_comparison", NOT_APPLICABLE if scenario is None else INSUFFICIENT_DATA),
            },
        },
        "PLANNER_CORE_COMPUTED_SIGNALS": {
            "trust_core": {
                "per_tool": tool_snapshots,
                "mean_confidence_score": round(mean(score for score in confidence_values if score is not None), 4) if confidence_values else INSUFFICIENT_DATA,
                "mean_trust_score": round(mean(score for score in trust_values if score is not None), 4) if trust_values else INSUFFICIENT_DATA,
                "min_trust_score": round(min(score for score in trust_values if score is not None), 4) if trust_values else INSUFFICIENT_DATA,
            },
            "forecast_quality_and_recalibration": {
                "cashflow_forecast": {
                    "status": _tool_state(forecast),
                    "calibration_monitoring": _get(forecast, "validation", "calibration_monitoring") or (NOT_APPLICABLE if forecast is None else INSUFFICIENT_DATA),
                    "historical_actuals": _get(forecast, "validation", "historical_actuals") or (NOT_APPLICABLE if forecast is None else INSUFFICIENT_DATA),
                    "native_uncertainty": _get(forecast, "model_evidence", "native_uncertainty") or (NOT_APPLICABLE if forecast is None else INSUFFICIENT_DATA),
                },
                "goal_feasibility": {
                    "status": _tool_state(goal) if goal is not None else NOT_APPLICABLE,
                    "calibration_monitoring": _get(goal, "validation", "calibration_monitoring") or (NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                },
                "scenario_quality": {
                    "status": _tool_state(scenario) if scenario is not None else NOT_APPLICABLE,
                    "calibration_monitoring": _get(scenario, "validation", "calibration_monitoring") or (NOT_APPLICABLE if scenario is None else INSUFFICIENT_DATA),
                },
            },
            "anomaly_signal_quality": {
                "status": _tool_state(anomaly),
                "flags": (anomaly or {}).get("flags", NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
                "detector_agreement": (anomaly or {}).get("detector_agreement", NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
                "signal_strength": _get(anomaly, "reliability", "components", "signal_strength") or (NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
                "calibration_monitoring": _get(anomaly, "validation", "calibration_monitoring") or (NOT_APPLICABLE if anomaly is None else INSUFFICIENT_DATA),
            },
            "uncertainty_and_volatility": {
                "forecast_native_uncertainty": _get(forecast, "model_evidence", "native_uncertainty") or (NOT_APPLICABLE if forecast is None else INSUFFICIENT_DATA),
                "spend_volatility": (spend or {}).get("spend_volatility", INSUFFICIENT_DATA),
                "risk_driver_volatility": _get(risk, "drivers", "volatility") or (NOT_APPLICABLE if risk is None else INSUFFICIENT_DATA),
            },
            "planning_and_execution_readiness": {
                "planning_readiness": planning_readiness,
                "execution_readiness": _execution_readiness(suitability),
                "overall_groundedness": _overall_groundedness(tool_results),
            },
            "evidence_quality_and_agent_use": {
                "tool_states": {tool_name: _tool_state(tool_output) for tool_name, tool_output in tool_results.items()},
                "planner_warning_codes": [item.code for item in planner_result.warnings],
                "human_feedback_requested": bool(_get(anomaly, "feedback_request", "show_to_user")),
            },
        },
        "FINANCIAL_USAGE_INSIGHT": {
            "inferred_spending_habits": "concentrated" if top_category_share >= 0.45 else "diversified",
            "inferred_cashflow_habits": "positive" if net_cashflow >= 0 else "negative",
            "inferred_budgeting_discipline": "watch" if attention_signals else "steady",
            "positive_signals": positive_signals,
            "attention_signals": attention_signals,
        },
        "STRATEGY_OPTIONS": {
            "conservative": {
                "status": "active",
                "focus": "Protect liquidity and reduce downside variance.",
                "rationale": "Use the current spend, risk, and runway signals to prioritize buffer strength before new commitments.",
                "grounding": {
                    "net_cashflow": (spend or {}).get("net_cashflow", INSUFFICIENT_DATA),
                    "runway_months": (risk or {}).get("emergency_runway_months", INSUFFICIENT_DATA),
                    "risk_band": (risk or {}).get("risk_band", INSUFFICIENT_DATA),
                },
                "confidence": planning_readiness,
            },
            "balanced": {
                "status": "active",
                "focus": "Stabilize monthly cashflow while keeping planned allocations in place.",
                "rationale": "Use the planner baseline and jar allocation guidance as the default operating mode.",
                "grounding": {
                    "baseline_monthly_income": (allocation or {}).get("baseline_monthly_income", INSUFFICIENT_DATA),
                    "top_allocation_target": ((allocation or {}).get("allocations") or [{}])[0].get("jar_name", INSUFFICIENT_DATA) if isinstance((allocation or {}).get("allocations"), list) else INSUFFICIENT_DATA,
                    "planning_readiness": planning_readiness,
                },
                "confidence": planning_readiness,
            },
            "growth": {
                "status": "active" if net_cashflow > 0 and planning_readiness == "ready" else "not_ready",
                "focus": "Increase goal progress only after core liquidity remains stable.",
                "rationale": "Growth-oriented steps should only be taken when the observed window stays positive and policy constraints remain clear.",
                "grounding": {
                    "goal_gap_amount": (goal or {}).get("gap_amount", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                    "goal_probability_of_success": (goal or {}).get("probability_of_success", NOT_APPLICABLE if goal is None else INSUFFICIENT_DATA),
                    "observed_net_cashflow": (spend or {}).get("net_cashflow", INSUFFICIENT_DATA),
                },
                "confidence": "cautious" if not (net_cashflow > 0 and planning_readiness == "ready") else planning_readiness,
            },
        },
        "BANKING_SERVICE_RECOMMENDATIONS": {
            "section_status": "grounded" if service_recommendations else INSUFFICIENT_DATA,
            "recommendations": service_recommendations or INSUFFICIENT_DATA,
        },
        "ACTIONABLE_NEXT_STEPS": {
            "steps": [
                {
                    "priority": index + 1,
                    "action": item.action,
                    "owner": item.owner or NOT_APPLICABLE,
                    "timeframe": item.timeframe or NOT_APPLICABLE,
                }
                for index, item in enumerate(planner_result.next_actions[:5])
            ]
            or INSUFFICIENT_DATA,
        },
        "EVIDENCE_TOOL_GROUNDING": {
            "tools_requested": list(tool_results.keys()),
            "tools_executed": [tool_name for tool_name, tool_output in tool_results.items() if isinstance(tool_output, Mapping)],
            "tool_trace": [
                {
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "latency_ms": item.latency_ms,
                    "details": item.details or "",
                }
                for item in planner_result.tool_trace
            ],
            "metric_sources": _metric_sources(),
            "planner_metric_sources": _planner_metric_sources(),
            "caveats": [item.message for item in planner_result.warnings] or INSUFFICIENT_DATA,
        },
        "RAW_METADATA": {
            "prompt": request.request.prompt,
            "planner_summary": planner_result.summary,
            "planner_key_facts": planner_result.key_facts or INSUFFICIENT_DATA,
            "planner_recommendations": [
                {
                    "title": item.title,
                    "rationale": item.rationale,
                    "priority": item.priority,
                    "expected_impact": item.expected_impact or NOT_APPLICABLE,
                }
                for item in planner_result.recommendations
            ]
            or INSUFFICIENT_DATA,
            "planner_warnings": [
                {
                    "code": item.code,
                    "message": item.message,
                    "severity": item.severity,
                }
                for item in planner_result.warnings
            ]
            or INSUFFICIENT_DATA,
            "runtime_metadata": dict(runtime_metadata or {}) or NOT_APPLICABLE,
        },
    }


def build_standardized_contract(
    *,
    request: SpecialistRequestEnvelope,
    planner_result: PlannerResult,
    planner_status: str,
    tool_results: Mapping[str, Dict[str, Any]],
    profile: Mapping[str, Any] | None = None,
    runtime_metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    sections = _sections(
        request=request,
        planner_result=planner_result,
        planner_status=planner_status,
        tool_results=tool_results,
        profile=profile,
        runtime_metadata=runtime_metadata,
    )
    contract = PlannerStandardizedContract(
        contract_spec_version=CONTRACT_SPEC_VERSION,
        txt_render_spec_version=REPORT_SPEC_VERSION,
        report_title=REPORT_TITLE,
        section_order=list(SECTION_ORDER),
        sections=sections,
        human_readable=_human_readable_contract(planner_result),
    )
    return contract.model_dump(exclude_none=True)


def build_standardized_txt_report_from_contract(contract: Mapping[str, Any]) -> str:
    txt_spec_version = str(contract.get("txt_render_spec_version") or REPORT_SPEC_VERSION).strip() or REPORT_SPEC_VERSION
    raw_sections = contract.get("sections") if isinstance(contract.get("sections"), Mapping) else {}
    raw_section_order = contract.get("section_order")
    section_order = (
        raw_section_order
        if isinstance(raw_section_order, Sequence) and not isinstance(raw_section_order, (str, bytes))
        else SECTION_ORDER
    )
    ordered_sections = [str(item).strip() for item in section_order if str(item).strip()]
    if not ordered_sections:
        ordered_sections = list(SECTION_ORDER)

    lines = [f"=== BEGIN {txt_spec_version.upper()} ===", ""]
    for section_name in ordered_sections:
        section_payload = raw_sections.get(section_name) if isinstance(raw_sections, Mapping) else None
        if not isinstance(section_payload, Mapping):
            section_payload = {}
        lines.append(f"## {section_name}")
        for key, value in section_payload.items():
            lines.append(f"{key}: {_value(value)}")
        lines.append("")
    lines.append(f"=== END {txt_spec_version.upper()} ===")
    return "\n".join(lines).strip() + "\n"


def build_standardized_txt_report(
    *,
    request: SpecialistRequestEnvelope,
    planner_result: PlannerResult,
    planner_status: str,
    tool_results: Mapping[str, Dict[str, Any]],
    profile: Mapping[str, Any] | None = None,
    runtime_metadata: Mapping[str, Any] | None = None,
) -> str:
    contract = build_standardized_contract(
        request=request,
        planner_result=planner_result,
        planner_status=planner_status,
        tool_results=tool_results,
        profile=profile,
        runtime_metadata=runtime_metadata,
    )
    return build_standardized_txt_report_from_contract(contract)
