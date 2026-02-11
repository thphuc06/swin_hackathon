from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from router.contracts import IntentExtractionV1, TopIntentScore  # noqa: E402
from router.policy import build_route_decision, suggest_intent_override  # noqa: E402


def _make_extraction(intent: str) -> IntentExtractionV1:
    return IntentExtractionV1(
        intent=intent,  # type: ignore[arg-type]
        confidence=0.95,
        top2=[
            TopIntentScore(intent=intent, score=0.95),  # type: ignore[arg-type]
            TopIntentScore(intent="summary", score=0.05),
        ],
        slots={},
        reason="test",
    )


def _decision_after_override(prompt: str, base_intent: str) -> tuple[str, list[str]]:
    extraction = _make_extraction(base_intent)
    override_intent, _ = suggest_intent_override(prompt, extraction)
    if override_intent is not None:
        extraction = extraction.model_copy(update={"intent": override_intent})
    decision = build_route_decision(
        mode="semantic_enforce",
        extraction=extraction,
        policy_version="v1",
        intent_conf_min=0.7,
        top2_gap_min=0.2,
        scenario_conf_min=0.7,
        max_clarify_questions=2,
        clarify_round=0,
    )
    return decision.final_intent, decision.tool_bundle


class RouterOverrideTests(unittest.TestCase):
    def test_case06_anomaly_overrides_to_risk(self) -> None:
        prompt = "thang nay toi thay co giao dich la, ban kiem tra giup"
        override_intent, reason = suggest_intent_override(prompt, _make_extraction("invest"))
        self.assertEqual(override_intent, "risk")
        self.assertEqual(reason, "intent_override:anomaly_to_risk")

        final_intent, tool_bundle = _decision_after_override(prompt, "invest")
        self.assertEqual(final_intent, "risk")
        self.assertIn("anomaly_signals_v1", tool_bundle)

    def test_case09_home_goal_overrides_to_planning(self) -> None:
        prompt = "toi muon mua nha 1.5 ty trong 5 nam, ke hoach tiet kiem kha thi?"
        override_intent, reason = suggest_intent_override(prompt, _make_extraction("invest"))
        self.assertEqual(override_intent, "planning")
        self.assertEqual(reason, "intent_override:home_goal_to_planning")

        final_intent, tool_bundle = _decision_after_override(prompt, "invest")
        self.assertEqual(final_intent, "planning")
        self.assertIn("goal_feasibility_v1", tool_bundle)
        self.assertIn("recurring_cashflow_detect_v1", tool_bundle)

    def test_case05_recurring_prompt_routes_to_planning_and_recurring_tool(self) -> None:
        prompt = "toi hay co khoan chi co dinh moi thang, giup toi nhan dien va toi uu"
        override_intent, reason = suggest_intent_override(prompt, _make_extraction("summary"))
        self.assertEqual(override_intent, "planning")
        self.assertEqual(reason, "intent_override:recurring_to_planning")

        final_intent, tool_bundle = _decision_after_override(prompt, "summary")
        self.assertEqual(final_intent, "planning")
        self.assertIn("recurring_cashflow_detect_v1", tool_bundle)

    def test_invest_recommendation_prompt_does_not_override_out_of_invest(self) -> None:
        prompt = "toi co nen mua co phieu ngan hang luc nay khong"
        override_intent, reason = suggest_intent_override(prompt, _make_extraction("invest"))
        self.assertIsNone(override_intent)
        self.assertEqual(reason, "")

    def test_service_priority_under_negative_cashflow_overrides_to_planning(self) -> None:
        prompt = "neu dong tien am keo dai, toi nen uu tien dich vu ngan hang nao truoc?"
        override_intent, reason = suggest_intent_override(prompt, _make_extraction("scenario"))
        self.assertEqual(override_intent, "planning")
        self.assertEqual(reason, "intent_override:service_priority_to_planning")


if __name__ == "__main__":
    unittest.main()
