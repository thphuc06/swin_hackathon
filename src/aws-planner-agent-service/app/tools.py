from __future__ import annotations

import time
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional

from strands import tool

from app.clients import MCPClient
from app.trace import log_event, with_tool


logger = logging.getLogger(__name__)


@dataclass
class PlannerContext:
    trace_id: str
    trace_context: Dict[str, Any]
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)


def _record_tool(context: PlannerContext, tool_name: str, status: str, latency_ms: int, details: str = "") -> None:
    context.tool_trace.append(
        {
            "tool_name": tool_name,
            "status": status,
            "latency_ms": latency_ms,
            "details": details,
        }
    )
    tool_ctx = with_tool(context.trace_context, tool_name)
    log_event(
        logger,
        "planner_tool_call",
        tool_ctx,
        payload={"status": status, "latency_ms": latency_ms, "details": details},
    )


def build_tools(
    context: PlannerContext,
    finance_client: MCPClient,
    kb_client: Optional[MCPClient],
) -> List[Any]:
    tools: List[Any] = []

    @tool
    def spend_analytics_v1(
        user_id: str,
        range: str = "30d",
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic spend analytics from SQL truth."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "spend_analytics_v1")
            result = finance_client.call_tool(
                "spend_analytics_v1",
                {"user_id": user_id, "range": range, "as_of": as_of, "trace_id": trace_id or context.trace_id},
                trace_context=tool_ctx,
            )
            _record_tool(context, "spend_analytics_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "spend_analytics_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def anomaly_signals_v1(
        user_id: str,
        lookback_days: int = 90,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic anomaly signals for spend/income/category/runway risk."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "anomaly_signals_v1")
            result = finance_client.call_tool(
                "anomaly_signals_v1",
                {"user_id": user_id, "lookback_days": lookback_days, "as_of": as_of, "trace_id": trace_id or context.trace_id},
                trace_context=tool_ctx,
            )
            _record_tool(context, "anomaly_signals_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "anomaly_signals_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def cashflow_forecast_v1(
        user_id: str,
        horizon: str = "weekly_12",
        scenario_overrides: Optional[Dict[str, Any]] = None,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic short-horizon cashflow forecast with confidence bands."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "cashflow_forecast_v1")
            result = finance_client.call_tool(
                "cashflow_forecast_v1",
                {
                    "user_id": user_id,
                    "horizon": horizon,
                    "scenario_overrides": scenario_overrides or {},
                    "as_of": as_of,
                    "trace_id": trace_id or context.trace_id,
                },
                trace_context=tool_ctx,
            )
            _record_tool(context, "cashflow_forecast_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "cashflow_forecast_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def jar_allocation_suggest_v1(
        user_id: str,
        monthly_income_override: Optional[float] = None,
        goal_overrides: Optional[List[Dict[str, Any]]] = None,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rule-based jar allocation suggestion from SQL behavior and goals."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "jar_allocation_suggest_v1")
            result = finance_client.call_tool(
                "jar_allocation_suggest_v1",
                {
                    "user_id": user_id,
                    "monthly_income_override": monthly_income_override,
                    "goal_overrides": goal_overrides or [],
                    "as_of": as_of,
                    "trace_id": trace_id or context.trace_id,
                },
                trace_context=tool_ctx,
            )
            _record_tool(context, "jar_allocation_suggest_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "jar_allocation_suggest_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def risk_profile_non_investment_v1(
        user_id: str,
        lookback_days: int = 180,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Non-investment risk profile from volatility/runway/overspend behavior."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "risk_profile_non_investment_v1")
            result = finance_client.call_tool(
                "risk_profile_non_investment_v1",
                {"user_id": user_id, "lookback_days": lookback_days, "as_of": as_of, "trace_id": trace_id or context.trace_id},
                trace_context=tool_ctx,
            )
            _record_tool(context, "risk_profile_non_investment_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "risk_profile_non_investment_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def suitability_guard_v1(
        user_id: str,
        intent: str = "",
        requested_action: str = "",
        prompt: str = "",
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Suitability guard for education-only and unsafe action refusal."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "suitability_guard_v1")
            result = finance_client.call_tool(
                "suitability_guard_v1",
                {
                    "user_id": user_id,
                    "intent": intent,
                    "requested_action": requested_action,
                    "prompt": prompt,
                    "trace_id": trace_id or context.trace_id,
                },
                trace_context=tool_ctx,
            )
            _record_tool(context, "suitability_guard_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "suitability_guard_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def recurring_cashflow_detect_v1(
        user_id: str,
        lookback_months: int = 6,
        min_occurrence_months: int = 3,
        recurring_overrides: Optional[List[Dict[str, Any]]] = None,
        drift_threshold_pct: float = 0.2,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Detect recurring cashflows, fixed-cost ratio, and recurring drift signals."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "recurring_cashflow_detect_v1")
            result = finance_client.call_tool(
                "recurring_cashflow_detect_v1",
                {
                    "user_id": user_id,
                    "lookback_months": lookback_months,
                    "min_occurrence_months": min_occurrence_months,
                    "recurring_overrides": recurring_overrides or [],
                    "drift_threshold_pct": drift_threshold_pct,
                    "as_of": as_of,
                    "trace_id": trace_id or context.trace_id,
                },
                trace_context=tool_ctx,
            )
            _record_tool(context, "recurring_cashflow_detect_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "recurring_cashflow_detect_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def goal_feasibility_v1(
        user_id: str,
        target_amount: Optional[float] = None,
        horizon_months: Optional[int] = None,
        goal_id: Optional[str] = None,
        seasonality: bool = True,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assess goal feasibility from SQL history + deterministic forecast."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "goal_feasibility_v1")
            result = finance_client.call_tool(
                "goal_feasibility_v1",
                {
                    "user_id": user_id,
                    "target_amount": target_amount,
                    "horizon_months": horizon_months,
                    "goal_id": goal_id,
                    "seasonality": seasonality,
                    "as_of": as_of,
                    "trace_id": trace_id or context.trace_id,
                },
                trace_context=tool_ctx,
            )
            _record_tool(context, "goal_feasibility_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "goal_feasibility_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    @tool
    def what_if_scenario_v1(
        user_id: str,
        horizon_months: int = 12,
        seasonality: bool = True,
        goal: str = "maximize_savings",
        base_scenario_overrides: Optional[Dict[str, Any]] = None,
        variants: Optional[List[Dict[str, Any]]] = None,
        as_of: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compare what-if cashflow variants against baseline and goal."""
        start = time.time()
        try:
            tool_ctx = with_tool(context.trace_context, "what_if_scenario_v1")
            result = finance_client.call_tool(
                "what_if_scenario_v1",
                {
                    "user_id": user_id,
                    "horizon_months": horizon_months,
                    "seasonality": seasonality,
                    "goal": goal,
                    "base_scenario_overrides": base_scenario_overrides or {},
                    "variants": variants or [],
                    "as_of": as_of,
                    "trace_id": trace_id or context.trace_id,
                },
                trace_context=tool_ctx,
            )
            _record_tool(context, "what_if_scenario_v1", "ok", int((time.time() - start) * 1000))
            return result
        except Exception as exc:
            _record_tool(context, "what_if_scenario_v1", "error", int((time.time() - start) * 1000), str(exc))
            raise

    tools.extend(
        [
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
    )

    if kb_client is not None:

        @tool
        def retrieve_from_aws_kb(
            query: str,
            knowledgeBaseId: str,
            n: int = 3,
        ) -> Dict[str, Any]:
            """Retrieve context from the AWS Knowledge Base MCP server."""
            start = time.time()
            try:
                tool_ctx = with_tool(context.trace_context, "retrieve_from_aws_kb")
                result = kb_client.call_tool(
                    "retrieve_from_aws_kb",
                    {"query": query, "knowledgeBaseId": knowledgeBaseId, "n": n},
                    trace_context=tool_ctx,
                )
                _record_tool(context, "retrieve_from_aws_kb", "ok", int((time.time() - start) * 1000))
                return result
            except Exception as exc:
                _record_tool(context, "retrieve_from_aws_kb", "error", int((time.time() - start) * 1000), str(exc))
                raise

        tools.append(retrieve_from_aws_kb)

    return tools
