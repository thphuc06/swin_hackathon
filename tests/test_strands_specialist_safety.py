from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from strands_orchestrator.nodes.safety_node import safety_node


def _base_state(prompt: str, intent: str) -> dict:
    return {
        "prompt": prompt,
        "intent": intent,
        "response": "",
        "trace_id": "trc_test1234",
        "clarification": {"pending": False},
        "tool_outputs": {},
        "tool_calls": [],
        "response_meta": {},
    }


class StrandsSpecialistSafetyTests(unittest.TestCase):
    def test_non_invest_prompt_is_allowed_without_degraded_refusal(self) -> None:
        state = _base_state("Summarize my recent spending and cashflow.", "summary")
        with patch("strands_orchestrator.nodes.safety_node.enable_specialist_delegation", return_value=True):
            result = safety_node(state)

        decision = result["tool_outputs"]["suitability_guard_v1"]
        self.assertTrue(decision["allow"])
        self.assertEqual("allow", decision["decision"])
        self.assertEqual(["non_investment_intent"], decision["reason_codes"])
        self.assertEqual("", result["response"])
        self.assertNotIn("safety_guard_degraded", result.get("response_meta", {}).get("reason_codes", []))

    def test_invest_recommendation_prompt_is_refused_without_degraded_mode(self) -> None:
        state = _base_state("Should I buy FPT stock now?", "invest")
        with patch("strands_orchestrator.nodes.safety_node.enable_specialist_delegation", return_value=True):
            result = safety_node(state)

        decision = result["tool_outputs"]["suitability_guard_v1"]
        self.assertFalse(decision["allow"])
        self.assertEqual("deny_recommendation", decision["decision"])
        self.assertEqual("suitability_refusal", result["response_meta"]["fallback_used"])
        self.assertIn("investment_recommendation_blocked", result["response_meta"]["reason_codes"])
        self.assertNotIn("safety_guard_degraded", result["response_meta"]["reason_codes"])

    def test_invest_education_prompt_is_allowed_in_education_only_mode(self) -> None:
        state = _base_state("Explain the key risks of FPT stock over 3 years.", "invest")
        with patch("strands_orchestrator.nodes.safety_node.enable_specialist_delegation", return_value=True):
            result = safety_node(state)

        decision = result["tool_outputs"]["suitability_guard_v1"]
        self.assertTrue(decision["allow"])
        self.assertEqual("education_only", decision["decision"])
        self.assertTrue(result["education_only"])
        self.assertEqual("", result["response"])


if __name__ == "__main__":
    unittest.main()
