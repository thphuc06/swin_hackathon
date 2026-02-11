from __future__ import annotations

import sys
import unittest
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
    def test_invest_query_keeps_policy_filter(self, mock_kb_retrieve) -> None:
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
        self.assertEqual(filters.get("doc_type"), "policy")


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


if __name__ == "__main__":
    unittest.main()
