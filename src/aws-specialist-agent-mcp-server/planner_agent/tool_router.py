from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from strands import tool as strands_tool
except Exception:  # pragma: no cover - optional dependency during local/unit test execution
    def strands_tool(func):  # type: ignore[no-redef]
        return func

from planner_agent.contracts import ActorInfo, CorrelationInfo
from planner_agent.finance.allocation import jar_allocation_suggest
from planner_agent.finance.anomaly import anomaly_signals
from planner_agent.finance.forecast import cashflow_forecast
from planner_agent.finance.goal import goal_feasibility
from planner_agent.finance.recurring import recurring_cashflow_detect
from planner_agent.finance.risk import risk_profile_non_investment
from planner_agent.finance.scenario import what_if_scenario
from planner_agent.finance.spend import spend_analytics
from planner_agent.finance.suitability import suitability_guard
from planner_agent.finance.supabase_rest import SupabaseRestClient
from planner_agent.timeframe import TimeframeHint

logger = logging.getLogger(__name__)
DEFAULT_FORECAST_HORIZON_DAYS = 84


@dataclass
class PlannerContext:
    actor: ActorInfo
    correlation: CorrelationInfo
    trace_context: Dict[str, Any]
    supabase_client: SupabaseRestClient
    timeframe_hint: TimeframeHint = field(default_factory=TimeframeHint)
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _record_tool(context: PlannerContext, tool_name: str, status: str, latency_ms: int, details: str = "") -> None:
    context.tool_trace.append(
        {
            "tool_name": tool_name,
            "status": status,
            "latency_ms": latency_ms,
            "details": details,
        }
    )
    logger.info(
        "planner_tool_call trace_id=%s tool=%s status=%s latency_ms=%s details=%s",
        context.correlation.trace_id,
        tool_name,
        status,
        latency_ms,
        details,
    )


def _resolve_user_id(context: PlannerContext, user_id: Optional[str]) -> str:
    return str(user_id or context.actor.user_id or context.actor.actor_id).strip()


def resolve_timeframe_defaults(timeframe_hint: TimeframeHint | None) -> Dict[str, Any]:
    hint = timeframe_hint or TimeframeHint()
    lookback_days = hint.lookback_days
    lookback_months = hint.lookback_months
    recurring_months = lookback_months or 6
    return {
        "spend_range": hint.spend_range or "30d",
        "anomaly_days": lookback_days or 90,
        "risk_days": lookback_days or 180,
        "history_days": hint.history_days or 180,
        "recurring_months": recurring_months,
        "recurring_min_occurrence_months": max(2, min(3, recurring_months)),
    }


def invoke_finance_tool(context: PlannerContext, tool_name: str, **kwargs: Any) -> Dict[str, Any]:
    start = time.time()
    user_id = _resolve_user_id(context, kwargs.pop("user_id", None))
    shared = {
        "auth_user_id": context.actor.user_id,
        "user_id": user_id,
        "trace_id": kwargs.pop("trace_id", None) or context.correlation.trace_id,
        "client": context.supabase_client,
    }
    try:
        if tool_name == "spend_analytics_v1":
            result = spend_analytics(range_value=kwargs.pop("range", "30d"), as_of=kwargs.pop("as_of", None), **shared)
        elif tool_name == "anomaly_signals_v1":
            result = anomaly_signals(
                lookback_days=int(kwargs.pop("lookback_days", 90)),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        elif tool_name == "cashflow_forecast_v1":
            # `history_days` is preserved in planner tool signatures for backward compatibility,
            # while the upgraded finance core computes its own fixed history window.
            kwargs.pop("history_days", None)
            try:
                horizon_days = max(1, int(kwargs.pop("horizon_days", DEFAULT_FORECAST_HORIZON_DAYS)))
            except (TypeError, ValueError):
                horizon_days = DEFAULT_FORECAST_HORIZON_DAYS
            result = cashflow_forecast(
                horizon_days=horizon_days,
                scenario_overrides=kwargs.pop("scenario_overrides", None),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        elif tool_name == "jar_allocation_suggest_v1":
            result = jar_allocation_suggest(
                monthly_income_override=kwargs.pop("monthly_income_override", None),
                goal_overrides=kwargs.pop("goal_overrides", None),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        elif tool_name == "risk_profile_non_investment_v1":
            result = risk_profile_non_investment(
                lookback_days=int(kwargs.pop("lookback_days", 180)),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        elif tool_name == "suitability_guard_v1":
            result = suitability_guard(
                intent=str(kwargs.pop("intent", "")),
                requested_action=str(kwargs.pop("requested_action", "")),
                prompt=str(kwargs.pop("prompt", "")),
                **shared,
            )
        elif tool_name == "recurring_cashflow_detect_v1":
            result = recurring_cashflow_detect(
                lookback_months=int(kwargs.pop("lookback_months", 6)),
                min_occurrence_months=int(kwargs.pop("min_occurrence_months", 3)),
                recurring_overrides=kwargs.pop("recurring_overrides", None) or [],
                drift_threshold_pct=float(kwargs.pop("drift_threshold_pct", 0.2)),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        elif tool_name == "goal_feasibility_v1":
            result = goal_feasibility(
                target_amount=kwargs.pop("target_amount", None),
                horizon_months=kwargs.pop("horizon_months", None),
                goal_id=kwargs.pop("goal_id", None),
                seasonality=bool(kwargs.pop("seasonality", True)),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        elif tool_name == "what_if_scenario_v1":
            result = what_if_scenario(
                horizon_months=int(kwargs.pop("horizon_months", 12)),
                seasonality=bool(kwargs.pop("seasonality", True)),
                goal=str(kwargs.pop("goal", "maximize_savings")),
                base_scenario_overrides=kwargs.pop("base_scenario_overrides", None),
                variants=kwargs.pop("variants", None),
                as_of=kwargs.pop("as_of", None),
                **shared,
            )
        else:  # pragma: no cover - guarded by caller
            raise ValueError(f"Unknown finance tool: {tool_name}")

        _record_tool(context, tool_name, "ok", int((time.time() - start) * 1000))
        if isinstance(result, dict):
            context.tool_results[tool_name] = result
        return result
    except Exception as exc:
        _record_tool(context, tool_name, "error", int((time.time() - start) * 1000), str(exc))
        raise


def build_tools(context: PlannerContext) -> List[Any]:
    timeframe_defaults = resolve_timeframe_defaults(context.timeframe_hint)

    @strands_tool
    def spend_analytics_v1(
        user_id: Optional[str] = None,
        range: str = str(timeframe_defaults["spend_range"]),
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic spend analytics from Supabase-backed transaction history."""
        return invoke_finance_tool(context, "spend_analytics_v1", user_id=user_id, range=range, as_of=as_of, trace_id=trace_id)

    @strands_tool
    def anomaly_signals_v1(
        user_id: Optional[str] = None,
        lookback_days: int = int(timeframe_defaults["anomaly_days"]),
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic anomaly detection for spending and cashflow drift."""
        return invoke_finance_tool(
            context,
            "anomaly_signals_v1",
            user_id=user_id,
            lookback_days=lookback_days,
            as_of=as_of,
            trace_id=trace_id,
        )

    @strands_tool
    def cashflow_forecast_v1(
        user_id: Optional[str] = None,
        horizon_days: int = DEFAULT_FORECAST_HORIZON_DAYS,
        history_days: int = int(timeframe_defaults["history_days"]),
        scenario_overrides: Optional[Dict[str, Any]] = None,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic short-horizon cashflow forecasting with daily future points."""
        return invoke_finance_tool(
            context,
            "cashflow_forecast_v1",
            user_id=user_id,
            horizon_days=horizon_days,
            history_days=history_days,
            scenario_overrides=scenario_overrides,
            as_of=as_of,
            trace_id=trace_id,
        )

    @strands_tool
    def jar_allocation_suggest_v1(
        user_id: Optional[str] = None,
        monthly_income_override: Optional[float] = None,
        goal_overrides: Optional[List[Dict[str, Any]]] = None,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rule-based monthly jar allocation guidance."""
        return invoke_finance_tool(
            context,
            "jar_allocation_suggest_v1",
            user_id=user_id,
            monthly_income_override=monthly_income_override,
            goal_overrides=goal_overrides,
            as_of=as_of,
            trace_id=trace_id,
        )

    @strands_tool
    def risk_profile_non_investment_v1(
        user_id: Optional[str] = None,
        lookback_days: int = int(timeframe_defaults["risk_days"]),
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Non-investment risk profile based on spending volatility and runway."""
        return invoke_finance_tool(
            context,
            "risk_profile_non_investment_v1",
            user_id=user_id,
            lookback_days=lookback_days,
            as_of=as_of,
            trace_id=trace_id,
        )

    @strands_tool
    def suitability_guard_v1(
        user_id: Optional[str] = None,
        intent: str = "",
        requested_action: str = "",
        prompt: str = "",
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Education-only suitability guard for execution and recommendation boundaries."""
        return invoke_finance_tool(
            context,
            "suitability_guard_v1",
            user_id=user_id,
            intent=intent,
            requested_action=requested_action,
            prompt=prompt,
            trace_id=trace_id,
        )

    @strands_tool
    def recurring_cashflow_detect_v1(
        user_id: Optional[str] = None,
        lookback_months: int = int(timeframe_defaults["recurring_months"]),
        min_occurrence_months: int = int(timeframe_defaults["recurring_min_occurrence_months"]),
        recurring_overrides: Optional[List[Dict[str, Any]]] = None,
        drift_threshold_pct: float = 0.2,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Recurring cashflow and fixed-cost drift detection."""
        return invoke_finance_tool(
            context,
            "recurring_cashflow_detect_v1",
            user_id=user_id,
            lookback_months=lookback_months,
            min_occurrence_months=min_occurrence_months,
            recurring_overrides=recurring_overrides,
            drift_threshold_pct=drift_threshold_pct,
            as_of=as_of,
            trace_id=trace_id,
        )

    @strands_tool
    def goal_feasibility_v1(
        user_id: Optional[str] = None,
        target_amount: Optional[float] = None,
        horizon_months: Optional[int] = None,
        goal_id: Optional[str] = None,
        seasonality: bool = True,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Goal feasibility grounded in transaction history and forecast baselines."""
        return invoke_finance_tool(
            context,
            "goal_feasibility_v1",
            user_id=user_id,
            target_amount=target_amount,
            horizon_months=horizon_months,
            goal_id=goal_id,
            seasonality=seasonality,
            as_of=as_of,
            trace_id=trace_id,
        )

    @strands_tool
    def what_if_scenario_v1(
        user_id: Optional[str] = None,
        horizon_months: int = 12,
        seasonality: bool = True,
        goal: str = "maximize_savings",
        base_scenario_overrides: Optional[Dict[str, Any]] = None,
        variants: Optional[List[Dict[str, Any]]] = None,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """What-if scenario comparison grounded in direct finance functions."""
        return invoke_finance_tool(
            context,
            "what_if_scenario_v1",
            user_id=user_id,
            horizon_months=horizon_months,
            seasonality=seasonality,
            goal=goal,
            base_scenario_overrides=base_scenario_overrides,
            variants=variants,
            as_of=as_of,
            trace_id=trace_id,
        )

    return [
        spend_analytics_v1,
        anomaly_signals_v1,
        cashflow_forecast_v1,
        jar_allocation_suggest_v1,
        risk_profile_non_investment_v1,
        suitability_guard_v1,
        recurring_cashflow_detect_v1,
        goal_feasibility_v1,
        what_if_scenario_v1,
    ]
