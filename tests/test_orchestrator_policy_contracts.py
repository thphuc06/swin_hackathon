from __future__ import annotations

import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

import graph
from orchestrator_policy import DegradationPolicyEntry, get_degradation_policy, heuristic_rule_snapshot


class _FakeModel:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def model_dump(self, **kwargs):
        return dict(self._payload)


class OrchestratorPolicyContractTests(unittest.TestCase):
    def test_graph_consumes_policy_default_scenario_variants(self) -> None:
        custom_variants = [{"name": "custom_variant", "scenario_overrides": {"spend_delta_pct": -0.2}}]
        with patch("graph.policy_default_scenario_variants", return_value=custom_variants):
            scenario_request = graph._build_scenario_request_from_slots({}, {})
        self.assertEqual(custom_variants, scenario_request["variants"])

    def test_graph_timeframe_resolution_delegates_to_policy(self) -> None:
        with patch("graph.policy_resolve_summary_range", return_value="77d"):
            self.assertEqual("77d", graph._resolve_summary_range("prompt", "summary", {}))
        with patch("graph.policy_resolve_lookback_days", return_value=123):
            self.assertEqual(
                123,
                graph._resolve_lookback_days(prompt="prompt", slots={}, default_days=90, min_days=30, max_days=365),
            )
        with patch("graph.policy_resolve_lookback_months", return_value=9):
            self.assertEqual(
                9,
                graph._resolve_lookback_months(prompt="prompt", slots={}, default_months=6, min_months=3, max_months=24),
            )

    def test_heuristic_recovery_records_policy_version_and_rule(self) -> None:
        state = {
            "response": "",
            "prompt": "Canh bao rui ro dong tien cua toi",
            "trace_id": "trc_policy",
            "request_id": "req_policy",
            "session_id": "sess_policy",
            "request_timestamp": "2026-03-19T00:00:00Z",
            "session_memory": {},
            "scenario_request": {},
            "clarification": {"pending": False, "round": 0, "max_questions": 2},
            "extraction": {},
            "route_decision": {},
            "response_meta": {},
            "intent": "",
            "user_profile": {},
        }
        with patch("graph.extract_intent_with_bedrock", return_value=(None, ["bad_json"], {})):
            next_state = graph.intent_router(state)
        self.assertEqual("risk", next_state["intent"])
        self.assertIn("intent_heuristic_recovery", next_state["route_decision"]["reason_codes"])
        self.assertIn("intent_heuristic_policy:v1", next_state["route_decision"]["reason_codes"])
        self.assertIn("intent_heuristic_rule:risk_markers", next_state["route_decision"]["reason_codes"])
        self.assertEqual("risk_markers", next_state["extraction"]["heuristic_rule_id"])

    def test_reasoning_uses_degradation_matrix_fallback_labels(self) -> None:
        state = {
            "response": "",
            "prompt": "summary",
            "intent": "summary",
            "trace_id": "trc_reason",
            "tool_calls": [],
            "tool_outputs": {},
            "kb": {},
            "education_only": False,
            "user_profile": {"risk_appetite": "unknown"},
            "route_decision": {},
            "extraction": {},
            "response_meta": {},
            "tool_errors": {},
            "clarification": {"pending": False},
        }
        custom_policy = DegradationPolicyEntry(
            app_env="staging",
            owner="test",
            tool_unavailable_fallback_enabled=True,
            clarification_fallback="matrix_clarify",
            template_fallback="matrix_template",
            llm_failure_fallback="matrix_llm_failure",
            grounding_failure_fallback="matrix_grounding_failed",
            facts_only_fallback="matrix_facts_only",
            default_response_mode="llm_shadow",
            allowed_response_modes=("template", "llm_shadow", "llm_enforce"),
        )
        with patch.object(graph, "RESPONSE_MODE", "template"):
            with patch("graph.get_degradation_policy", return_value=custom_policy):
                next_state = graph.reasoning(dict(state))
        self.assertEqual("matrix_template", next_state["response_meta"]["fallback_used"])

        with patch.object(graph, "RESPONSE_MODE", "llm_enforce"):
            with patch("graph.get_degradation_policy", return_value=custom_policy):
                with patch("graph.build_evidence_pack", return_value=(_FakeModel(), [])):
                    with patch("graph.build_advisory_context", return_value=(_FakeModel(), [])):
                        with patch("graph.synthesize_answer_plan_with_bedrock", return_value=(None, [], {})):
                                with patch("graph.render_facts_only_compact_response", return_value="facts-only"):
                                    next_state = graph.reasoning(dict(state))
        self.assertEqual("matrix_llm_failure", next_state["response_meta"]["fallback_used"])

    def test_degradation_matrix_and_heuristic_registry_are_explicit(self) -> None:
        self.assertEqual("facts_only_compact_renderer", get_degradation_policy("staging").facts_only_fallback)
        self.assertEqual(
            [
                {"rule_id": "scenario_markers", "owner": "platform-orchestrator", "classification": "temporary_heuristic", "target_intent": "scenario"},
                {"rule_id": "risk_markers", "owner": "platform-orchestrator", "classification": "temporary_heuristic", "target_intent": "risk"},
                {"rule_id": "planning_markers", "owner": "platform-orchestrator", "classification": "temporary_heuristic", "target_intent": "planning"},
                {"rule_id": "summary_markers", "owner": "platform-orchestrator", "classification": "temporary_heuristic", "target_intent": "summary"},
                {"rule_id": "summary_window_last_resort", "owner": "platform-orchestrator", "classification": "temporary_heuristic", "target_intent": "summary"},
            ],
            heuristic_rule_snapshot(),
        )


if __name__ == "__main__":
    unittest.main()
