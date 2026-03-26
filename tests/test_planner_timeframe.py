from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from planner_agent.agent import run_planner
from planner_agent.contracts import ActorInfo, CorrelationInfo
from planner_agent.timeframe import TimeframeHint, derive_timeframe_hint
from planner_agent.tool_router import PlannerContext, build_tools


@contextmanager
def temp_env(**updates):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _request_envelope(prompt: str) -> dict:
    return {
        "schema_version": "v1",
        "actor": {
            "actor_id": "usr_123",
            "user_id": "usr_123",
            "tenant_id": "tenant_a",
            "scopes": ["chat:invoke", "finance:read"],
        },
        "correlation": {
            "session_id": "usr_123:default",
            "request_id": "req_abc",
            "trace_id": "trc_xyz",
            "parent_request_id": "req_root",
            "request_timestamp": "2026-03-16T12:00:00Z",
        },
        "request": {
            "prompt": prompt,
            "intent": "planning",
            "policy_flags": {"education_only": True},
            "user_context": {},
            "goals": [],
            "session_summary": "",
        },
        "routing": {
            "specialist_id": "planner",
            "tool_name": "run_planner_agent_v1",
        },
    }


class PlannerTimeframeTests(unittest.TestCase):
    def test_prompt_parses_arbitrary_month_window(self) -> None:
        hint = derive_timeframe_hint("Phan tich tai chinh 4 thang gan day cua toi.")

        self.assertEqual(120, hint.analysis_days)
        self.assertEqual(4, hint.analysis_months)
        self.assertEqual("120d", hint.spend_range)

    def test_prompt_parses_english_month_window(self) -> None:
        hint = derive_timeframe_hint("Have there been any unusual transactions in my account over the last 8 months?")

        self.assertEqual(240, hint.analysis_days)
        self.assertEqual(8, hint.analysis_months)
        self.assertEqual("240d", hint.spend_range)

    def test_prompt_prefers_retrospective_window_over_future_goal_horizon(self) -> None:
        hint = derive_timeframe_hint(
            "Phan tich 90 ngay gan day cua toi va len ke hoach tiet kiem 50000000 trong 6 thang toi."
        )

        self.assertEqual(90, hint.analysis_days)
        self.assertEqual(3, hint.analysis_months)
        self.assertEqual("90 ngay", hint.matched_text)

    def test_tool_defaults_follow_timeframe_hint(self) -> None:
        context = PlannerContext(
            actor=ActorInfo(actor_id="usr_123", user_id="usr_123", tenant_id="tenant_a", scopes=[]),
            correlation=CorrelationInfo(
                session_id="usr_123:default",
                request_id="req_abc",
                trace_id="trc_xyz",
                parent_request_id="req_root",
                request_timestamp="2026-03-16T12:00:00Z",
            ),
            trace_context={},
            supabase_client=type("FakeSupabaseClient", (), {"configured": True})(),
            timeframe_hint=TimeframeHint(analysis_days=120, analysis_months=4, source="prompt", matched_text="4 thang"),
        )

        spend_tool, _, forecast_tool, _, risk_tool, _, recurring_tool, _, _ = build_tools(context)

        with patch("planner_agent.tool_router.invoke_finance_tool", return_value={}) as invoke_tool:
            spend_tool()
            forecast_tool()
            risk_tool()
            recurring_tool()

        observed = [(call.args[1], call.kwargs) for call in invoke_tool.call_args_list]
        self.assertEqual("120d", observed[0][1]["range"])
        self.assertEqual(84, observed[1][1]["horizon_days"])
        self.assertEqual(120, observed[1][1]["history_days"])
        self.assertEqual(120, observed[2][1]["lookback_days"])
        self.assertEqual(4, observed[3][1]["lookback_months"])

    def test_deterministic_planner_uses_dynamic_timeframe_defaults(self) -> None:
        envelope = _request_envelope("Phan tich tai chinh 6 thang gan day cua toi.")
        recorded_calls: list[tuple[str, dict]] = []

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            recorded_calls.append((tool_name, dict(kwargs)))
            context.tool_trace.append(
                {
                    "tool_name": tool_name,
                    "status": "ok",
                    "latency_ms": 1,
                    "details": "test",
                }
            )
            if tool_name == "spend_analytics_v1":
                return {"total_spend": 100.0, "net_cashflow": 25.0, "budget_drift": []}
            if tool_name == "cashflow_forecast_v1":
                return {"confidence_band": {"p50_avg": 40.0}}
            if tool_name == "jar_allocation_suggest_v1":
                return {"baseline_monthly_income": 300.0, "allocations": [{"jar_name": "Bills"}]}
            return {}

        with temp_env(PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertEqual("ok", result["status"])
        self.assertIn(("spend_analytics_v1", {"range": "180d"}), recorded_calls)
        self.assertIn(("cashflow_forecast_v1", {"horizon_days": 84, "history_days": 180}), recorded_calls)


if __name__ == "__main__":
    unittest.main()
