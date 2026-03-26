from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from planner_agent.agent import run_planner
from strands_orchestrator.specialist import validate_specialist_output


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


def _request_envelope(*, intent: str, prompt: str) -> dict:
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
            "request_timestamp": "2026-03-18T12:00:00Z",
        },
        "request": {
            "prompt": prompt,
            "intent": intent,
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


class PlannerFinanceCoreIntegrationTests(unittest.TestCase):
    def test_summary_bundle_avoids_zero_facts_when_recent_window_has_no_transactions(self) -> None:
        envelope = _request_envelope(intent="summary", prompt="Phan tich giao dich cua toi trong 6 thang gan day.")

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            context.tool_trace.append(
                {
                    "tool_name": tool_name,
                    "status": "ok",
                    "latency_ms": 1,
                    "details": "test",
                }
            )
            if tool_name == "spend_analytics_v1":
                return {
                    "total_spend": 0.0,
                    "net_cashflow": 0.0,
                    "budget_drift": [],
                    "validation": {"tx_count": 0, "debit_txn_count": 0},
                    "reliability": {"reason_codes": ["no_transactions_in_window"], "confidence_score": 0.2},
                    "trust": {"trust_score": 0.2, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert"},
                }
            if tool_name == "cashflow_forecast_v1":
                return {
                    "confidence_band": {"p50_avg": 0.0},
                    "reliability": {"reason_codes": ["no_transactions_in_window"], "confidence_score": 0.1},
                    "trust": {"trust_score": 0.1, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert"},
                }
            if tool_name == "jar_allocation_suggest_v1":
                return {
                    "baseline_monthly_income": 0.0,
                    "allocations": [],
                    "reliability": {"reason_codes": ["no_transactions_in_window"], "confidence_score": 0.1},
                    "trust": {"trust_score": 0.1, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert"},
                }
            return {}

        with temp_env(PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertNotIn("Recent spend total: 0.0.", result["result"]["key_facts"])
        self.assertNotIn("Observed net cashflow over the selected window: 0.0.", result["result"]["key_facts"])
        self.assertIn("The selected window does not contain enough recent transaction data", result["result"]["summary"])
        warning_codes = [item["code"] for item in result["result"]["warnings"]]
        self.assertIn("recent_transaction_window_insufficient", warning_codes)
        recommendation_titles = [item["title"] for item in result["result"]["recommendations"]]
        self.assertIn("Sync recent transactions before relying on this planning window", recommendation_titles)

    def test_planning_bundle_includes_recurring_and_forecast_trust_guidance(self) -> None:
        envelope = _request_envelope(intent="planning", prompt="Lap ke hoach tai chinh 6 thang toi.")
        recorded_calls: list[str] = []

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            recorded_calls.append(tool_name)
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
                return {
                    "confidence_band": {"p50_avg": 40.0},
                    "trust": {"trust_score": 0.42, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "advisory_only", "monitoring_status": "watch"},
                }
            if tool_name == "jar_allocation_suggest_v1":
                return {
                    "baseline_monthly_income": 300.0,
                    "allocations": [{"jar_name": "Bills"}],
                    "trust": {"trust_score": 0.42, "trust_level": "low", "caps_applied": ["forecast_trust_cap"]},
                    "agent_use": {"usage_mode": "advisory_only", "monitoring_status": "watch"},
                }
            if tool_name == "recurring_cashflow_detect_v1":
                return {"drift_alerts": []}
            return {}

        with temp_env(PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertEqual(
            [
                "spend_analytics_v1",
                "cashflow_forecast_v1",
                "jar_allocation_suggest_v1",
                "recurring_cashflow_detect_v1",
            ],
            recorded_calls,
        )
        warning_codes = [item["code"] for item in result["result"]["warnings"]]
        self.assertIn("forecast_signal_cautious", warning_codes)
        self.assertIn("directional", result["result"]["summary"].lower())
        validate_specialist_output("run_planner_agent_v1.output.json", result)

    def test_risk_bundle_includes_spend_and_surfaces_anomaly_feedback_request(self) -> None:
        envelope = _request_envelope(intent="risk", prompt="Kiem tra rui ro va anomaly giao dich gan day cua toi.")
        recorded_calls: list[str] = []

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            recorded_calls.append(tool_name)
            context.tool_trace.append(
                {
                    "tool_name": tool_name,
                    "status": "ok",
                    "latency_ms": 1,
                    "details": "test",
                }
            )
            if tool_name == "spend_analytics_v1":
                return {"total_spend": 90.0, "net_cashflow": -10.0, "budget_drift": []}
            if tool_name == "anomaly_signals_v1":
                return {
                    "flags": ["unexpected_spend_spike"],
                    "feedback_request": {"show_to_user": True},
                    "trust": {"trust_score": 0.51, "trust_level": "medium", "caps_applied": []},
                    "agent_use": {
                        "usage_mode": "advisory_only",
                        "monitoring_status": "watch",
                        "human_feedback_recommended": True,
                    },
                }
            if tool_name == "risk_profile_non_investment_v1":
                return {"risk_band": "high", "emergency_runway_months": 2.0}
            return {}

        with temp_env(PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertEqual(
            [
                "spend_analytics_v1",
                "anomaly_signals_v1",
                "risk_profile_non_investment_v1",
            ],
            recorded_calls,
        )
        actions = [item["action"] for item in result["result"]["next_actions"]]
        self.assertTrue(any("Confirm whether the recent anomaly alert" in action for action in actions))
        warning_codes = [item["code"] for item in result["result"]["warnings"]]
        self.assertIn("anomaly_feedback_requested", warning_codes)
        recommendation_titles = [item["title"] for item in result["result"]["recommendations"]]
        self.assertIn("Increase emergency buffer before new commitments", recommendation_titles)
        validate_specialist_output("run_planner_agent_v1.output.json", result)

    def test_risk_bundle_avoids_false_risk_summary_when_window_has_no_transactions(self) -> None:
        envelope = _request_envelope(intent="risk", prompt="Kiem tra giao dich bat thuong cua toi trong 8 thang gan day.")

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            context.tool_trace.append(
                {
                    "tool_name": tool_name,
                    "status": "ok",
                    "latency_ms": 1,
                    "details": "test",
                }
            )
            if tool_name == "spend_analytics_v1":
                return {
                    "total_spend": 0.0,
                    "net_cashflow": 0.0,
                    "budget_drift": [],
                    "validation": {"tx_count": 0, "debit_txn_count": 0},
                    "reliability": {"reason_codes": ["no_transactions_in_window"], "confidence_score": 0.2},
                    "trust": {"trust_score": 0.2, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert"},
                }
            if tool_name == "anomaly_signals_v1":
                return {
                    "flags": [],
                    "feedback_request": {"show_to_user": False},
                    "validation": {"tx_count": 0},
                    "reliability": {"reason_codes": ["no_transactions_in_window"], "confidence_score": 0.15},
                    "trust": {"trust_score": 0.15, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert"},
                }
            if tool_name == "risk_profile_non_investment_v1":
                return {
                    "risk_band": "unknown",
                    "emergency_runway_months": None,
                    "validation": {"tx_count": 0},
                    "reliability": {"reason_codes": ["no_transactions_in_window"], "confidence_score": 0.1},
                    "trust": {"trust_score": 0.1, "trust_level": "low", "caps_applied": []},
                    "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert"},
                }
            return {}

        with temp_env(PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertNotIn("Non-investment risk band: moderate.", result["result"]["key_facts"])
        self.assertNotIn("Emergency runway estimate: 999 months.", result["result"]["key_facts"])
        self.assertFalse(any("Detected anomaly flags:" in item for item in result["result"]["key_facts"]))
        warning_codes = [item["code"] for item in result["result"]["warnings"]]
        self.assertIn("risk_window_insufficient", warning_codes)
        self.assertIn("recent_transaction_window_insufficient", warning_codes)

    def test_invest_bundle_keeps_policy_guard_and_non_investment_risk(self) -> None:
        envelope = _request_envelope(intent="invest", prompt="Toi muon danh gia kha nang dau tu cua minh.")
        recorded_calls: list[str] = []

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            recorded_calls.append(tool_name)
            context.tool_trace.append(
                {
                    "tool_name": tool_name,
                    "status": "ok",
                    "latency_ms": 1,
                    "details": "test",
                }
            )
            if tool_name == "suitability_guard_v1":
                return {"decision": "education_only"}
            if tool_name == "risk_profile_non_investment_v1":
                return {"risk_band": "moderate", "emergency_runway_months": 4.0}
            return {}

        with temp_env(PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertEqual(
            [
                "suitability_guard_v1",
                "risk_profile_non_investment_v1",
            ],
            recorded_calls,
        )
        warning_codes = [item["code"] for item in result["result"]["warnings"]]
        self.assertIn("policy_boundary_active", warning_codes)
        validate_specialist_output("run_planner_agent_v1.output.json", result)


if __name__ == "__main__":
    unittest.main()
