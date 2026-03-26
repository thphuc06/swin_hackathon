from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from planner_agent.contracts import SpecialistRequestEnvelope
from planner_agent.tool_router import PlannerContext, resolve_timeframe_defaults


PLANNER_POLICY_VERSION = "v1"
PLANNER_DEFAULT_SCENARIO_HORIZON_MONTHS = 12
PLANNER_DEFAULT_FORECAST_HORIZON_DAYS = 84
PLANNER_UNKNOWN_INTENT_FALLBACK = "summary"
PLANNER_SUPPORTED_INTENTS = {"summary", "risk", "planning", "scenario", "invest", "out_of_scope"}


@dataclass(frozen=True)
class PlannerToolPolicyEntry:
    intent: str
    owner: str
    classification: str
    builder: Callable[[SpecialistRequestEnvelope, PlannerContext], List[Tuple[str, Dict[str, Any]]]]


def normalize_planner_intent(intent: str) -> str:
    normalized = str(intent or "").strip().lower()
    if normalized in PLANNER_SUPPORTED_INTENTS:
        return normalized
    return PLANNER_UNKNOWN_INTENT_FALLBACK


def _first_goal(request: SpecialistRequestEnvelope) -> Dict[str, Any]:
    goals = request.request.goals or []
    if not goals:
        return {}
    first = goals[0]
    return dict(first) if isinstance(first, dict) else {}


def _summary_plan(request: SpecialistRequestEnvelope, context: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    timeframe_defaults = resolve_timeframe_defaults(context.timeframe_hint)
    return [
        ("spend_analytics_v1", {"range": timeframe_defaults["spend_range"]}),
        (
            "cashflow_forecast_v1",
            {
                "horizon_days": PLANNER_DEFAULT_FORECAST_HORIZON_DAYS,
                "history_days": timeframe_defaults["history_days"],
            },
        ),
        ("jar_allocation_suggest_v1", {"goal_overrides": request.request.goals}),
    ]


def _planning_plan(request: SpecialistRequestEnvelope, context: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    timeframe_defaults = resolve_timeframe_defaults(context.timeframe_hint)
    plan = list(_summary_plan(request, context))
    plan.append(
        (
            "recurring_cashflow_detect_v1",
            {
                "lookback_months": timeframe_defaults["recurring_months"],
                "min_occurrence_months": timeframe_defaults["recurring_min_occurrence_months"],
            },
        )
    )
    first_goal = _first_goal(request)
    if first_goal:
        plan.append(
            (
                "goal_feasibility_v1",
                {
                    "goal_id": first_goal.get("id"),
                    "target_amount": first_goal.get("target_amount"),
                    "horizon_months": first_goal.get("horizon_months"),
                },
            )
        )
    return plan


def _risk_plan(request: SpecialistRequestEnvelope, context: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    timeframe_defaults = resolve_timeframe_defaults(context.timeframe_hint)
    return [
        ("spend_analytics_v1", {"range": timeframe_defaults["spend_range"]}),
        ("anomaly_signals_v1", {"lookback_days": timeframe_defaults["anomaly_days"]}),
        ("risk_profile_non_investment_v1", {"lookback_days": timeframe_defaults["risk_days"]}),
    ]


def _scenario_plan(_: SpecialistRequestEnvelope, context: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    timeframe_defaults = resolve_timeframe_defaults(context.timeframe_hint)
    return [
        (
            "cashflow_forecast_v1",
            {
                "horizon_days": PLANNER_DEFAULT_FORECAST_HORIZON_DAYS,
                "history_days": timeframe_defaults["history_days"],
            },
        ),
        ("what_if_scenario_v1", {"horizon_months": PLANNER_DEFAULT_SCENARIO_HORIZON_MONTHS}),
    ]


def _invest_plan(request: SpecialistRequestEnvelope, context: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    timeframe_defaults = resolve_timeframe_defaults(context.timeframe_hint)
    return [
        ("suitability_guard_v1", {"intent": "invest", "prompt": request.request.prompt}),
        ("risk_profile_non_investment_v1", {"lookback_days": timeframe_defaults["risk_days"]}),
    ]


def _out_of_scope_plan(request: SpecialistRequestEnvelope, _: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    intent = normalize_planner_intent(request.request.intent)
    return [("suitability_guard_v1", {"intent": intent, "prompt": request.request.prompt})]


PLANNER_TOOL_POLICY: dict[str, PlannerToolPolicyEntry] = {
    "summary": PlannerToolPolicyEntry("summary", "platform-planner", "policy", _summary_plan),
    "planning": PlannerToolPolicyEntry("planning", "platform-planner", "policy", _planning_plan),
    "risk": PlannerToolPolicyEntry("risk", "platform-planner", "policy", _risk_plan),
    "scenario": PlannerToolPolicyEntry("scenario", "platform-planner", "policy", _scenario_plan),
    "invest": PlannerToolPolicyEntry("invest", "platform-planner", "policy", _invest_plan),
    "out_of_scope": PlannerToolPolicyEntry("out_of_scope", "platform-planner", "policy", _out_of_scope_plan),
}


def build_tool_plan(request: SpecialistRequestEnvelope, context: PlannerContext) -> List[Tuple[str, Dict[str, Any]]]:
    intent = normalize_planner_intent(request.request.intent)
    return PLANNER_TOOL_POLICY[intent].builder(request, context)


def planner_policy_snapshot() -> list[dict[str, str]]:
    return [
        {
            "intent": entry.intent,
            "owner": entry.owner,
            "classification": entry.classification,
        }
        for entry in PLANNER_TOOL_POLICY.values()
    ]
