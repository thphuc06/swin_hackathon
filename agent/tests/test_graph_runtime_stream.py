from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

import graph  # noqa: E402
from router.contracts import IntentExtractionV1, TopIntentScore  # noqa: E402


class RequestedActionTests(unittest.TestCase):
    def test_pronoun_ban_does_not_map_to_sell(self) -> None:
        prompt = "thang nay toi thay co giao dich la, ban kiem tra giup"
        self.assertEqual(graph._requested_action(prompt), "advice")

    def test_recommend_buy_stock_kept(self) -> None:
        prompt = "toi co nen mua co phieu ngan hang luc nay khong"
        self.assertEqual(graph._requested_action(prompt), "recommend_buy")

    def test_home_goal_buy_house_is_not_invest_action(self) -> None:
        prompt = "toi muon mua nha 1.5 ty trong 5 nam, ke hoach tiet kiem kha thi?"
        self.assertEqual(graph._requested_action(prompt), "advice")


class RetrieveKbFilterTests(unittest.TestCase):
    @patch("graph.kb_retrieve")
    def test_planning_query_not_hardcoded_to_policy(self, mock_kb_retrieve) -> None:
        mock_kb_retrieve.return_value = {"matches": []}
        state = {
            "response": "",
            "clarification": {"pending": False},
            "prompt": "toi muon mua nha 1.5 ty trong 5 nam",
            "intent": "planning",
            "user_token": "token",
            "trace_id": "trc_test",
        }
        graph.retrieve_kb(state)
        self.assertTrue(mock_kb_retrieve.called)
        _, filters, *_ = mock_kb_retrieve.call_args.args
        self.assertEqual(filters.get("intent"), "planning")
        self.assertNotIn("doc_type", filters)

    @patch("graph.kb_retrieve")
    def test_invest_query_uses_intent_filter_only(self, mock_kb_retrieve) -> None:
        mock_kb_retrieve.return_value = {"matches": []}
        state = {
            "response": "",
            "clarification": {"pending": False},
            "prompt": "toi co nen mua co phieu khong",
            "intent": "invest",
            "user_token": "token",
            "trace_id": "trc_test",
        }
        graph.retrieve_kb(state)
        self.assertTrue(mock_kb_retrieve.called)
        _, filters, *_ = mock_kb_retrieve.call_args.args
        self.assertEqual(filters.get("intent"), "invest")
        self.assertNotIn("doc_type", filters)


class ToolExecutionSafetyTests(unittest.TestCase):
    @patch("graph.goal_feasibility_tool")
    def test_goal_horizon_is_clamped_for_mcp_contract(self, mock_goal_tool) -> None:
        mock_goal_tool.return_value = {"trace_id": "trc_goal"}
        state = {
            "user_token": "token",
            "user_id": "user-1",
            "trace_id": "trc_test",
            "prompt": "toi muon mua nha 1.5 ty trong 5 nam",
        }
        slots = {"target_amount_vnd": 1_500_000_000, "horizon_months": 60}
        tool_name, _ = graph._execute_tool_safe("goal_feasibility_v1", state, slots)
        self.assertEqual(tool_name, "goal_feasibility_v1")
        self.assertTrue(mock_goal_tool.called)
        self.assertEqual(mock_goal_tool.call_args.kwargs.get("horizon_months"), 24)

    @patch("graph.spend_analytics")
    def test_summary_range_uses_explicit_day_window(self, mock_spend_analytics) -> None:
        mock_spend_analytics.return_value = {"trace_id": "trc_spend"}
        state = {
            "user_token": "token",
            "user_id": "user-1",
            "trace_id": "trc_test",
            "prompt": "45 ngay qua toi chi tieu bao nhieu?",
            "intent": "summary",
        }
        tool_name, _ = graph._execute_tool_safe("spend_analytics_v1", state, {})
        self.assertEqual(tool_name, "spend_analytics_v1")
        self.assertEqual(mock_spend_analytics.call_args.kwargs.get("range_days"), "45d")

    @patch("graph.spend_analytics")
    def test_prompt_timeframe_overrides_default_slot_window(self, mock_spend_analytics) -> None:
        mock_spend_analytics.return_value = {"trace_id": "trc_spend"}
        state = {
            "user_token": "token",
            "user_id": "user-1",
            "trace_id": "trc_test",
            "prompt": "45 ngay qua toi chi tieu bao nhieu?",
            "intent": "summary",
        }
        tool_name, _ = graph._execute_tool_safe("spend_analytics_v1", state, {"range_days": 90})
        self.assertEqual(tool_name, "spend_analytics_v1")
        self.assertEqual(mock_spend_analytics.call_args.kwargs.get("range_days"), "45d")

    @patch("graph.anomaly_signals")
    def test_anomaly_lookback_uses_prompt_months(self, mock_anomaly_signals) -> None:
        mock_anomaly_signals.return_value = {"trace_id": "trc_anomaly"}
        state = {
            "user_token": "token",
            "user_id": "user-1",
            "trace_id": "trc_test",
            "prompt": "2 thang gan day toi co giao dich nao la khong?",
        }
        tool_name, _ = graph._execute_tool_safe("anomaly_signals_v1", state, {})
        self.assertEqual(tool_name, "anomaly_signals_v1")
        self.assertEqual(mock_anomaly_signals.call_args.kwargs.get("lookback_days"), 60)

    @patch("graph.anomaly_signals")
    @patch("graph._now_utc")
    def test_anomaly_prompt_timeframe_overrides_default_slot_window(self, mock_now_utc, mock_anomaly_signals) -> None:
        mock_now_utc.return_value = datetime(2026, 2, 11, 10, 0, 0, tzinfo=timezone.utc)
        mock_anomaly_signals.return_value = {"trace_id": "trc_anomaly"}
        state = {
            "user_token": "token",
            "user_id": "user-1",
            "trace_id": "trc_test",
            "prompt": "thang nay toi thay co giao dich la khong?",
        }
        tool_name, _ = graph._execute_tool_safe("anomaly_signals_v1", state, {"lookback_days": 90})
        self.assertEqual(tool_name, "anomaly_signals_v1")
        # "thang nay" resolves to 11d and is clamped to anomaly minimum 30d.
        self.assertEqual(mock_anomaly_signals.call_args.kwargs.get("lookback_days"), 30)

    @patch("graph.recurring_cashflow_detect_tool")
    def test_recurring_lookback_respects_min_contract(self, mock_recurring_tool) -> None:
        mock_recurring_tool.return_value = {"trace_id": "trc_recurring"}
        state = {
            "user_token": "token",
            "user_id": "user-1",
            "trace_id": "trc_test",
            "prompt": "2 thang gan day toi co nhieu khoan chi dinh ky nao?",
        }
        tool_name, _ = graph._execute_tool_safe("recurring_cashflow_detect_v1", state, {})
        self.assertEqual(tool_name, "recurring_cashflow_detect_v1")
        # Recurring contract minimum remains 3 months for stability.
        self.assertEqual(mock_recurring_tool.call_args.kwargs.get("lookback_months"), 3)


class TimeframeParserTests(unittest.TestCase):
    @patch("graph._now_utc")
    def test_this_month_resolves_to_days_since_month_start(self, mock_now_utc) -> None:
        mock_now_utc.return_value = datetime(2026, 2, 11, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(graph._resolve_summary_range("thang nay toi chi tieu bao nhieu?", "summary"), "11d")

    def test_two_months_window_resolves_without_bucket(self) -> None:
        self.assertEqual(graph._resolve_summary_range("2 thang gan day", "summary"), "60d")

    def test_risk_default_window_kept_for_backward_compatibility(self) -> None:
        self.assertEqual(graph._resolve_summary_range("toi muon danh gia rui ro hien tai", "risk"), "90d")


class IntentRouterOverrideSafetyTests(unittest.TestCase):
    @patch("graph.extract_intent_with_bedrock")
    def test_service_priority_override_skips_low_top2_clarification(self, mock_extract) -> None:
        extraction = IntentExtractionV1(
            intent="scenario",
            confidence=0.91,
            top2=[
                TopIntentScore(intent="scenario", score=0.51),
                TopIntentScore(intent="planning", score=0.49),
            ],
            slots={"horizon_months": 6, "income_delta_pct": -0.1},
            reason="test",
        )
        mock_extract.return_value = (extraction, [], {})
        state = {
            "response": "",
            "prompt": "neu dong tien am keo dai, toi nen uu tien dich vu ngan hang nao truoc?",
            "clarification": {"round": 0},
            "scenario_request": {},
            "extraction": {},
            "route_decision": {},
            "intent": "",
            "user_profile": {},
        }
        next_state = graph.intent_router(state)
        self.assertEqual(next_state.get("intent"), "planning")
        route = next_state.get("route_decision", {})
        self.assertFalse(bool(route.get("clarify_needed")))
        self.assertNotIn("low_top2_gap", list(route.get("reason_codes", [])))

    @patch("graph.extract_intent_with_bedrock")
    def test_anomaly_override_skips_low_top2_clarification(self, mock_extract) -> None:
        extraction = IntentExtractionV1(
            intent="summary",
            confidence=0.89,
            top2=[
                TopIntentScore(intent="summary", score=0.51),
                TopIntentScore(intent="risk", score=0.49),
            ],
            slots={},
            reason="test",
        )
        mock_extract.return_value = (extraction, [], {})
        state = {
            "response": "",
            "prompt": "thang nay co giao dich la nao, liet ke 3 canh bao noi bat",
            "clarification": {"round": 0},
            "scenario_request": {},
            "extraction": {},
            "route_decision": {},
            "intent": "",
            "user_profile": {},
        }
        next_state = graph.intent_router(state)
        self.assertEqual(next_state.get("intent"), "risk")
        route = next_state.get("route_decision", {})
        self.assertFalse(bool(route.get("clarify_needed")))
        self.assertNotIn("low_top2_gap", list(route.get("reason_codes", [])))


if __name__ == "__main__":
    unittest.main()
