from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from router.contracts import IntentExtractionV1
from router.policy import suggest_intent_override, tool_bundle_for_intent
from router.policy_registry import override_rule_snapshot


class RouterPolicyRegistryTests(unittest.TestCase):
    def test_tool_bundles_resolve_from_versioned_policy(self) -> None:
        self.assertEqual(
            ["spend_analytics_v1", "cashflow_forecast_v1", "jar_allocation_suggest_v1"],
            tool_bundle_for_intent("summary"),
        )
        self.assertEqual(
            ["spend_analytics_v1", "cashflow_forecast_v1", "jar_allocation_suggest_v1"],
            tool_bundle_for_intent("unknown_intent"),
        )

    def test_override_rule_snapshot_is_versioned_and_owned(self) -> None:
        self.assertEqual(
            [
                {"rule_id": "invest_to_planning_optimize", "owner": "platform-routing", "classification": "policy", "target_intent": "planning"},
                {"rule_id": "invest_terms_to_invest", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "invest"},
                {"rule_id": "anomaly_to_risk", "owner": "platform-routing", "classification": "policy", "target_intent": "risk"},
                {"rule_id": "risk_priority_keywords", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "risk"},
                {"rule_id": "savings_deposit_to_planning", "owner": "platform-routing", "classification": "policy", "target_intent": "planning"},
                {"rule_id": "home_goal_to_planning", "owner": "platform-routing", "classification": "policy", "target_intent": "planning"},
                {"rule_id": "purchase_goal_to_planning", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "planning"},
                {"rule_id": "recurring_to_planning", "owner": "platform-routing", "classification": "policy", "target_intent": "planning"},
                {"rule_id": "service_priority_to_planning", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "planning"},
                {"rule_id": "oos_invalid_date_in_scope", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "summary"},
                {"rule_id": "low_domain_relevance", "owner": "platform-routing", "classification": "policy", "target_intent": "out_of_scope"},
                {"rule_id": "low_domain_relevance_top2_oos", "owner": "platform-routing", "classification": "policy", "target_intent": "out_of_scope"},
                {"rule_id": "scenario_to_planning", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "planning"},
                {"rule_id": "scenario_to_risk", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "risk"},
                {"rule_id": "scenario_to_summary", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "summary"},
                {"rule_id": "scenario_to_summary_default", "owner": "platform-routing", "classification": "temporary_heuristic", "target_intent": "summary"},
            ],
            override_rule_snapshot("v1"),
        )

    def test_override_registry_evaluates_prompt_fixtures(self) -> None:
        anomaly_extraction = IntentExtractionV1(
            intent="summary",
            sub_intent="",
            confidence=0.9,
            domain_relevance=1.0,
            top2=[{"intent": "summary", "score": 0.9}, {"intent": "risk", "score": 0.4}],
            slots={},
            scenario_confidence=0.0,
            reason="fixture",
        )
        override_intent, override_reason = suggest_intent_override(
            "Phan tich giao dich bat thuong va anomaly gan day cua toi",
            anomaly_extraction,
        )
        self.assertEqual("risk", override_intent)
        self.assertEqual("intent_override:anomaly_to_risk", override_reason)

        scenario_extraction = IntentExtractionV1(
            intent="scenario",
            sub_intent="",
            confidence=0.8,
            domain_relevance=1.0,
            top2=[{"intent": "scenario", "score": 0.8}, {"intent": "summary", "score": 0.5}],
            slots={},
            scenario_confidence=0.4,
            reason="fixture",
        )
        override_intent, override_reason = suggest_intent_override(
            "Tong quan dong tien va chi tieu cua toi",
            scenario_extraction,
        )
        self.assertEqual("summary", override_intent)
        self.assertEqual("intent_override:scenario_to_summary", override_reason)

        stock_extraction = IntentExtractionV1(
            intent="out_of_scope",
            sub_intent="",
            confidence=0.55,
            domain_relevance=0.32,
            top2=[{"intent": "out_of_scope", "score": 0.55}, {"intent": "invest", "score": 0.4}],
            slots={},
            scenario_confidence=0.0,
            reason="fixture",
        )
        override_intent, override_reason = suggest_intent_override(
            "Please give an educational overview of Vietnam bank stocks, key risks, diversification considerations, and what to watch before buying.",
            stock_extraction,
        )
        self.assertEqual("invest", override_intent)
        self.assertEqual("intent_override:invest_terms_to_invest", override_reason)


if __name__ == "__main__":
    unittest.main()
