from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from service_agent.agent import run_service
from service_agent.candidate_normalizer import normalize_candidate
from service_agent.candidate_ranker import rank_candidates
from service_agent.candidate_validator import validate_candidate
from service_agent.contracts import (
    CandidateProposal,
    CandidateServiceMap,
    CandidateSet,
    ServiceExplanation,
    SpecialistRequestEnvelope,
)
from service_agent.explanation_layer import build_explanation
from service_agent.layer1_sufficiency import classify_request
from service_agent.layer2_reasoning_adapter import propose_candidates
from service_agent.model_adapter import invoke_json_prompt
from service_agent.roadmap_context import normalize_request


def _service_envelope() -> dict:
    return {
        "schema_version": "v1",
        "actor": {
            "actor_id": "usr_123",
            "user_id": "usr_123",
            "tenant_id": "tenant_a",
            "scopes": ["chat:invoke"],
        },
        "correlation": {
            "session_id": "chat_service",
            "request_id": "req_service",
            "trace_id": "trc_service",
            "parent_request_id": "req_root",
            "request_timestamp": "2026-03-22T09:00:00Z",
        },
        "request": {
            "prompt": "Help me build a financial roadmap to buy a car in 12 months",
            "intent": "planning",
            "policy_flags": {"education_only": True},
            "user_context": {
                "planner_state": {
                    "cashflow_status": "negative",
                    "savings_capacity": {"amount_monthly": 4000000, "label": "moderate"},
                    "runway_months": 2.4,
                    "liquidity_pressure": "high",
                    "anomaly_state": "active",
                    "readiness_label": "cautious",
                    "feasibility_hint": "medium",
                    "risk_band": "moderate",
                },
                "risk_preference": "moderate",
                "liquidity_need": "high",
                "urgency": "medium",
            },
            "goals": [
                {
                    "goal_type": "vehicle_purchase",
                    "target_amount": 60000000,
                    "target_timeline_months": 12,
                    "priority": "high",
                }
            ],
            "session_summary": "",
        },
        "routing": {"specialist_id": "service", "tool_name": "run_service_agent_v1"},
    }


def _candidate_set() -> CandidateSet:
    return CandidateSet(
        schema_version="service_candidate_set_v1",
        readiness_class="ready",
        candidates=[
            CandidateProposal(
                candidate_id="cand_protect_first",
                journey_pattern="protect_then_stabilize_then_accumulate_then_review",
                phase_types=["protect_liquidity", "stabilize", "accumulate", "readiness_review"],
                current_phase_hint="protect_liquidity",
                service_candidates=[
                    CandidateServiceMap(phase_type="protect_liquidity", service_ids=["anomaly_review", "liquidity_guardrails"]),
                    CandidateServiceMap(phase_type="stabilize", service_ids=["budget_controls", "recurring_expense_cleanup"]),
                    CandidateServiceMap(phase_type="accumulate", service_ids=["goal_bucket_setup", "auto_save_activation"]),
                ],
                rationale_tags=["anomaly_active", "liquidity_pressure_high"],
                candidate_risk_tags=["liquidity_fragile"],
                requires_grounded_fields=["planner_state.runway_months", "planner_state.anomaly_state"],
                assumption_flags=["goal_is_primary_focus"],
                tradeoff_notes=["safer start, slower early progress"],
                proposal_confidence=0.74,
                model_fit_score=0.7,
            )
        ],
    )


def _explanation(summary: str = "Here is your roadmap.") -> tuple[ServiceExplanation, dict]:
    return (
        ServiceExplanation(
            summary=summary,
            why_fit="This path fits because liquidity needs protecting early.",
            current_phase_explanation="Your current phase is protect liquidity first, which means the immediate focus is to stop immediate cash leakage and reduce near-term liquidity risk.",
            phase_explanations=[
                {
                    "phase_type": "protect_liquidity",
                    "why_this_phase_exists": "This phase exists to contain leakage before the plan loses more ground.",
                    "why_it_is_current_or_upcoming": "It is current because anomaly risk is active.",
                    "what_success_looks_like": "The leakage risk is contained and the cashflow baseline is clearer.",
                    "what_unlocks_next_phase": "That unlocks stabilize.",
                }
            ],
            milestone_explanations=[
                {
                    "milestone_id": "ms_1",
                    "why_it_matters": "The roadmap needs a trustworthy baseline first.",
                    "what_needs_to_happen": "Flagged transactions need review.",
                    "what_changes_after_completion": "The roadmap can move into repair.",
                }
            ],
            next_action_explanation={
                "why_now": "Protecting cashflow comes first when anomaly or liquidity risk is active.",
                "what_to_check": "Review the highest-risk transactions and confirm whether leakage is real.",
                "what_success_looks_like": "You can explain the flagged outflows and contain them.",
                "what_happens_next": "The roadmap can move into stabilize.",
            },
            projection_explanation={
                "basis": "Projection uses current monthly savings capacity and current funded progress.",
                "pace_assessment": "The current pace is not yet enough.",
                "target_gap_commentary": "There is still a material gap to target.",
                "trend_commentary": "The projection is improving only after the current phase succeeds.",
            },
            phase_service_explanations=[
                {
                    "phase_type": "protect_liquidity",
                    "selected_services": [{"service_id": "liquidity_guardrails", "display_name_vi": "Hàng rào thanh khoản", "role": "primary"}],
                    "explanation": "Liquidity guardrails fit this phase because cash protection comes before accumulation.",
                }
            ],
            milestone_service_explanations=[
                {
                    "milestone_id": "ms_1",
                    "selected_services": [{"service_id": "anomaly_review", "display_name_vi": "Rà soát giao dịch bất thường", "role": "primary"}],
                    "explanation": "Anomaly review helps close the current milestone cleanly.",
                }
            ],
            next_action_service_explanation={
                "selected_service": {"service_id": "liquidity_guardrails", "display_name_vi": "Hàng rào thanh khoản"},
                "explanation": "This service supports the immediate containment step before stabilize.",
            },
            cautions=["Keep projections directional only."],
            confidence_note="Confidence in the roadmap structure is stronger than confidence in the projection pace.",
        ),
        {"mode": "bedrock", "model_id": "test-model"},
    )


class _FakeBankingServicesClient:
    configured = True

    def __init__(self, rows):
        self._rows = rows

    def table_exists(self, table: str) -> bool:
        return table == "banking_services"

    def fetch_rows(self, *args, **kwargs):
        return list(self._rows)


class ServiceAgentMvpTests(unittest.TestCase):
    def test_candidate_normalizer_canonicalizes_aliases(self) -> None:
        candidate = CandidateProposal(
            candidate_id="cand_alias",
            journey_pattern="protect_then_progress",
            phase_types=["verify_and_protect", "build_buffer", "goal_funding", "review"],
            current_phase_hint="verify_and_protect",
            service_candidates=[
                CandidateServiceMap(phase_type="verify_and_protect", service_ids=["transaction_alerts", "manual_verification"])
            ],
            proposal_confidence=0.9,
            model_fit_score=0.9,
        )

        normalized = normalize_candidate(candidate)

        self.assertEqual("protect_then_stabilize_then_accumulate_then_review", normalized.journey_pattern)
        self.assertEqual(
            ["protect_liquidity", "stabilize", "accumulate", "readiness_review"],
            normalized.phase_types,
        )
        self.assertEqual("protect_liquidity", normalized.current_phase_hint)
        self.assertEqual(["anomaly_review"], normalized.service_candidates[0].service_ids)

    def test_candidate_validator_hard_rejects_unsafe_accumulate_first(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))
        context.planner_state.savings_capacity.amount_monthly = 0.0
        candidate = CandidateProposal(
            candidate_id="cand_bad",
            journey_pattern="stabilize_then_accumulate_then_review",
            phase_types=["accumulate", "readiness_review"],
            current_phase_hint="accumulate",
            service_candidates=[CandidateServiceMap(phase_type="accumulate", service_ids=["goal_bucket_setup"])],
            proposal_confidence=0.6,
            model_fit_score=0.6,
        )

        validated = validate_candidate(candidate, context)

        self.assertFalse(validated.is_valid)
        self.assertTrue(any("non_positive_capacity" in item for item in validated.hard_reject_reasons))

    def test_candidate_ranker_is_deterministic_and_uses_stable_tie_break(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))
        candidate_a = CandidateProposal(
            candidate_id="cand_001",
            journey_pattern="protect_then_stabilize_then_accumulate_then_review",
            phase_types=["protect_liquidity", "stabilize", "accumulate", "readiness_review"],
            service_candidates=[CandidateServiceMap(phase_type="protect_liquidity", service_ids=["anomaly_review"])],
            proposal_confidence=0.7,
            model_fit_score=0.7,
        )
        candidate_b = CandidateProposal(
            candidate_id="cand_002",
            journey_pattern="protect_then_stabilize_then_accumulate_then_review",
            phase_types=["protect_liquidity", "stabilize", "accumulate", "readiness_review"],
            service_candidates=[CandidateServiceMap(phase_type="protect_liquidity", service_ids=["anomaly_review"])],
            proposal_confidence=0.7,
            model_fit_score=0.7,
        )

        ranked_first = rank_candidates(
            [validate_candidate(candidate_a, context), validate_candidate(candidate_b, context)],
            context,
        )
        ranked_second = rank_candidates(
            [validate_candidate(candidate_a, context), validate_candidate(candidate_b, context)],
            context,
        )

        self.assertEqual("cand_001", ranked_first[0].candidate.candidate_id)
        self.assertEqual("cand_001", ranked_second[0].candidate.candidate_id)
        self.assertEqual(ranked_first[0].final_score, ranked_second[0].final_score)

    def test_normalize_request_parses_stock_context(self) -> None:
        envelope = _service_envelope()
        envelope["request"]["user_context"]["stock_context"] = {
            "summary": "Vietnam equities look choppy while oil-linked volatility stays elevated.",
            "suitability_status": "warn",
            "market_tone": "cautious",
            "market_notes": ["Energy price volatility is feeding market caution."],
            "warning_flags": ["volatile_macro"],
            "cited_symbols": ["VNINDEX", "GAS"],
            "source": "stock_agent",
        }

        context = normalize_request(SpecialistRequestEnvelope.model_validate(envelope))

        self.assertIsNotNone(context.user_context.stock_context)
        self.assertEqual("warn", context.user_context.stock_context.suitability_status)
        self.assertEqual("cautious", context.user_context.stock_context.market_tone)
        self.assertEqual(["VNINDEX", "GAS"], context.user_context.stock_context.cited_symbols)

    def test_normalize_request_extracts_stock_symbols_from_envelope(self) -> None:
        envelope = _service_envelope()
        envelope["request"]["user_context"] = {
            "planner_state": envelope["request"]["user_context"]["planner_state"],
            "stock_envelope": {
                "tool_name": "run_stock_agent_v1",
                "agent_id": "stock",
                "result": {
                    "summary": "Vietnam market update.",
                    "suitability": {"status": "unknown"},
                    "alternatives": [{"ticker": "VCB", "rationale": "Highlighted in market snapshot."}],
                    "market_notes": ["Banking stocks remain active."],
                    "market_snapshot": {"highlighted_symbols": ["TCB", "MBB"]},
                },
                "warnings": [],
            },
        }

        context = normalize_request(SpecialistRequestEnvelope.model_validate(envelope))

        self.assertIsNotNone(context.user_context.stock_context)
        self.assertEqual("unknown", context.user_context.stock_context.market_tone)
        self.assertEqual(["VCB", "TCB", "MBB"], context.user_context.stock_context.cited_symbols)
        self.assertEqual(["Banking stocks remain active."], context.user_context.stock_context.market_notes)

    def test_candidate_ranker_uses_stock_context_to_prefer_cautious_richer_path(self) -> None:
        envelope = _service_envelope()
        envelope["request"]["user_context"]["planner_state"].update(
            {
                "cashflow_status": "positive",
                "savings_capacity": {"amount_monthly": 12000000, "label": "strong"},
                "runway_months": 9.0,
                "liquidity_pressure": "low",
                "anomaly_state": "none",
                "readiness_label": "ready",
                "feasibility_hint": "medium",
                "risk_band": "moderate",
            }
        )
        envelope["request"]["user_context"]["stock_context"] = {
            "summary": "Equity conditions are still choppy and caution is warranted.",
            "suitability_status": "warn",
            "market_tone": "cautious",
            "market_notes": ["Volatility remains elevated."],
            "warning_flags": ["market_volatility"],
            "source": "stock_agent",
        }
        context = classify_request(normalize_request(SpecialistRequestEnvelope.model_validate(envelope)))

        richer_candidate = CandidateProposal(
            candidate_id="cand_richer",
            journey_pattern="stabilize_then_accumulate_then_review",
            phase_types=["stabilize", "accumulate", "readiness_review"],
            current_phase_hint="stabilize",
            service_candidates=[CandidateServiceMap(phase_type="stabilize", service_ids=["budget_controls"])],
            proposal_confidence=0.68,
            model_fit_score=0.62,
        )
        compressed_candidate = CandidateProposal(
            candidate_id="cand_compressed",
            journey_pattern="stabilize_then_accumulate_then_review",
            phase_types=["accumulate", "readiness_review"],
            current_phase_hint="accumulate",
            service_candidates=[CandidateServiceMap(phase_type="accumulate", service_ids=["goal_bucket_setup"])],
            proposal_confidence=0.68,
            model_fit_score=0.62,
        )

        ranked = rank_candidates(
            [validate_candidate(richer_candidate, context), validate_candidate(compressed_candidate, context)],
            context,
        )

        self.assertEqual("cand_richer", ranked[0].candidate.candidate_id)
        self.assertGreater(
            ranked[0].components["stock_context_alignment_score"],
            ranked[1].components["stock_context_alignment_score"],
        )
        self.assertGreater(
            ranked[0].components["journey_richness_score"],
            ranked[1].components["journey_richness_score"],
        )

    def test_run_service_returns_partial_setup_when_planner_state_missing(self) -> None:
        envelope = _service_envelope()
        envelope["request"]["user_context"] = {}

        with patch("service_agent.agent.build_explanation", return_value=_explanation("Here is a setup-first roadmap.")):
            result = run_service(envelope)

        self.assertEqual("partial", result["status"])
        self.assertEqual("insufficient_financial_state", result["roadmap_contract"]["status"])
        self.assertTrue(result["roadmap_contract"]["missing_fields"])

    def test_run_service_falls_back_when_all_candidates_rejected(self) -> None:
        envelope = _service_envelope()
        bad_candidates = CandidateSet(
            schema_version="service_candidate_set_v1",
            readiness_class="ready",
            candidates=[
                CandidateProposal(
                    candidate_id="cand_reject",
                    journey_pattern="stabilize_then_accumulate_then_review",
                    phase_types=["accumulate", "readiness_review"],
                    current_phase_hint="accumulate",
                    service_candidates=[CandidateServiceMap(phase_type="accumulate", service_ids=["goal_bucket_setup"])],
                    requires_grounded_fields=["planner_state.runway_months"],
                    proposal_confidence=0.9,
                    model_fit_score=0.9,
                )
            ],
        )

        with patch("service_agent.agent.propose_candidates", return_value=(bad_candidates, {"mode": "test"})):
            with patch("service_agent.agent.build_explanation", return_value=_explanation("Here is a setup-first roadmap.")):
                result = run_service(envelope)

        self.assertEqual("partial", result["status"])
        self.assertEqual("candidate_rejected_fallback", result["roadmap_contract"]["status"])
        self.assertEqual("readiness_review", result["roadmap_contract"]["current_phase"])

    def test_run_service_compiles_structured_contract(self) -> None:
        envelope = _service_envelope()

        with patch("service_agent.agent.propose_candidates", return_value=(_candidate_set(), {"mode": "bedrock", "model_id": "test-model"})):
            with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                result = run_service(envelope)

        contract = result["roadmap_contract"]
        self.assertIn(contract["current_phase"], contract["phase_sequence"])
        self.assertTrue(contract["phases"])
        self.assertTrue(contract["milestones"])
        self.assertIn("visualization_support", contract)
        self.assertIn("projection", contract)
        self.assertIn("ui_explanation", result)
        self.assertTrue(result["ui_explanation"]["why_this_roadmap"])
        self.assertTrue(result["ui_explanation"]["why_current_phase"])
        self.assertIn("what_has_to_change_next", result["ui_explanation"])
        self.assertIn("status_banner", contract["visualization_support"])
        self.assertIn("key_metrics", contract["visualization_support"])
        self.assertIn("unlock_conditions", contract["visualization_support"])
        self.assertIn("reasoning_signals", result["diagnostics"])
        self.assertEqual("bedrock", result["diagnostics"]["layer4"]["mode"])

    def test_run_service_ignores_stock_context_even_when_present(self) -> None:
        envelope = _service_envelope()
        envelope["request"]["user_context"]["stock_context"] = {
            "summary": "Vietnam equities are mixed.",
            "suitability_status": "warn",
            "market_tone": "cautious",
            "warning_flags": ["market_caution"],
            "source": "session_memory",
        }

        def _inspect_context(context):
            self.assertIsNone(context.user_context.stock_context)
            return _candidate_set(), {"mode": "bedrock", "model_id": "test-model"}

        with patch("planner_agent.agent.run_planner", side_effect=AssertionError("planner should not be auto-invoked")):
            with patch("stock.adapter.run_stock", side_effect=AssertionError("stock should not be auto-invoked")):
                with patch("service_agent.agent.propose_candidates", side_effect=_inspect_context):
                    with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                        result = run_service(envelope)

        self.assertEqual("ok", result["status"])
        self.assertEqual("protect_liquidity", result["roadmap_contract"]["current_phase"])
        self.assertEqual("This path fits because liquidity needs protecting early.", result["ui_explanation"]["why_this_roadmap"])

    def test_run_service_never_auto_invokes_stock(self) -> None:
        envelope = _service_envelope()

        def _inspect_context(context):
            self.assertIsNone(context.user_context.stock_context)
            return _candidate_set(), {"mode": "bedrock", "model_id": "test-model"}

        with patch.dict(os.environ, {"SERVICE_AGENT_AUTO_INVOKE_STOCK": "true"}, clear=False):
            with patch("stock.adapter.run_stock", side_effect=AssertionError("stock should not be auto-invoked by default")):
                with patch("service_agent.agent.propose_candidates", side_effect=_inspect_context):
                    with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                        result = run_service(envelope)

        self.assertEqual("ok", result["status"])

    def test_run_service_attaches_banking_service_recommendations(self) -> None:
        envelope = _service_envelope()
        banking_services = [
            {
                "service_id": "liquidity_guardrails",
                "display_name_vi": "Hàng rào thanh khoản",
                "display_name_en": "Liquidity Guardrails",
                "category": "liquidity_protection",
                "description": "Protects short-term liquidity.",
                "user_benefit_vi": "Giúp bảo vệ số dư khả dụng và giảm rò rỉ dòng tiền.",
                "when_to_recommend_vi": "Khi dòng tiền còn yếu hoặc có áp lực thanh khoản.",
                "when_not_to_recommend_vi": "",
                "supported_phases": ["protect_liquidity", "stabilize"],
                "supported_milestones": ["anomaly_contained", "cashflow_stabilized"],
                "supported_goal_types": ["vehicle_purchase"],
                "liquidity_profile": "high",
                "risk_level": "low",
                "requires_positive_cashflow": False,
                "requires_anomaly_resolved": False,
                "requires_buffer_present": False,
                "is_active": True,
                "sort_order": 10,
            },
            {
                "service_id": "anomaly_review",
                "display_name_vi": "Rà soát giao dịch bất thường",
                "display_name_en": "Anomaly Review",
                "category": "alerts",
                "description": "Reviews suspicious transactions.",
                "user_benefit_vi": "Giúp xác minh giao dịch bất thường trước khi mất thêm tiền.",
                "when_to_recommend_vi": "Khi có anomaly active.",
                "when_not_to_recommend_vi": "",
                "supported_phases": ["protect_liquidity"],
                "supported_milestones": ["anomaly_contained"],
                "supported_goal_types": ["vehicle_purchase"],
                "liquidity_profile": "high",
                "risk_level": "low",
                "requires_positive_cashflow": False,
                "requires_anomaly_resolved": False,
                "requires_buffer_present": False,
                "is_active": True,
                "sort_order": 20,
            },
            {
                "service_id": "goal_bucket_setup",
                "display_name_vi": "Tạo tài khoản mục tiêu",
                "display_name_en": "Goal Bucket Setup",
                "category": "goal_funding",
                "description": "Separates goal funds from daily cash.",
                "user_benefit_vi": "Giúp tách quỹ mục tiêu khỏi tài khoản chi tiêu.",
                "when_to_recommend_vi": "Khi chuyển sang accumulate.",
                "when_not_to_recommend_vi": "",
                "supported_phases": ["accumulate"],
                "supported_milestones": ["contribution_rhythm_active"],
                "supported_goal_types": ["vehicle_purchase"],
                "liquidity_profile": "medium",
                "risk_level": "low",
                "requires_positive_cashflow": True,
                "requires_anomaly_resolved": True,
                "requires_buffer_present": False,
                "is_active": True,
                "sort_order": 30,
            },
        ]
        selection_payload = {
            "phase_recommendations": [
                {
                    "phase_type": "protect_liquidity",
                    "selected_services": [
                        {
                            "service_id": "liquidity_guardrails",
                            "role": "primary",
                            "why_recommended": "It protects short-term liquidity while the anomaly is still active.",
                            "expected_benefit": "Cash leakage becomes easier to contain.",
                        },
                        {
                            "service_id": "anomaly_review",
                            "role": "supporting",
                            "why_recommended": "It helps verify suspicious outflows before moving on.",
                            "expected_benefit": "The current leakage signal can be confirmed or dismissed.",
                        },
                    ],
                    "explanation": "Protection-first services fit because anomaly risk is still active and liquidity pressure is high.",
                }
            ],
            "milestone_recommendations": [
                {
                    "milestone_id": "ms_1",
                    "selected_services": [
                        {
                            "service_id": "anomaly_review",
                            "role": "primary",
                            "why_recommended": "This milestone depends on reviewing suspicious activity first.",
                            "expected_benefit": "The roadmap gets a cleaner baseline for the next phase.",
                        }
                    ],
                    "explanation": "Anomaly review is the clearest milestone unlock because it resolves the most urgent uncertainty.",
                }
            ],
            "next_action_service": {
                "service_id": "liquidity_guardrails",
                "why_this_service_now": "It directly supports the immediate containment step.",
                "how_it_supports_transition": "It helps the roadmap move from protect into stabilize with a safer cash position.",
            },
            "selection_warnings": [],
        }

        with patch("service_agent.agent.propose_candidates", return_value=(_candidate_set(), {"mode": "bedrock", "model_id": "test-model"})):
            with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                with patch("service_agent.banking_service_recommender.get_supabase_client", return_value=_FakeBankingServicesClient(banking_services)):
                    with patch("service_agent.banking_service_recommender._run_selection_layer", return_value=(selection_payload, {"mode": "bedrock", "model_id": "test-model"})):
                        result = run_service(envelope)

        contract = result["roadmap_contract"]
        current_phase = next(item for item in contract["phases"] if item["phase_type"] == "protect_liquidity")
        current_milestone = next(item for item in contract["milestones"] if item["milestone_id"] == "ms_1")

        self.assertEqual("ok", result["diagnostics"]["service_recommendation_status"])
        self.assertEqual(2, len(current_phase["recommended_services"]))
        self.assertEqual(2, len(current_phase["recommended_now"]))
        self.assertEqual(current_phase["recommended_services"], current_phase["recommended_now"])
        self.assertEqual("liquidity_guardrails", current_phase["recommended_services"][0]["service_id"])
        self.assertTrue(current_phase["service_selection_reason"])
        self.assertEqual("anomaly_review", current_milestone["recommended_services"][0]["service_id"])
        self.assertEqual("liquidity_guardrails", contract["next_best_action"]["recommended_service"]["service_id"])
        self.assertTrue(result["diagnostics"]["phase_service_explanations"])
        self.assertTrue(result["diagnostics"]["milestone_service_explanations"])

        accumulate_phase = next(item for item in contract["phases"] if item["phase_type"] == "accumulate")
        self.assertEqual("goal_bucket_setup", accumulate_phase["future_services_preview"][0]["service_id"])
        phase_card = next(
            item
            for item in contract["visualization_support"]["phase_cards"]
            if item["phase_type"] == "accumulate"
        )
        self.assertEqual("goal_bucket_setup", phase_card["future_services_preview"][0]["service_id"])

    def test_run_service_maps_buy_home_goal_alias_for_banking_service_filter(self) -> None:
        envelope = _service_envelope()
        envelope["request"]["goals"][0]["goal_type"] = "buy_home"
        banking_services = [
            {
                "service_id": "budget_controls",
                "display_name_vi": "Kiểm soát ngân sách",
                "display_name_en": "Budget Controls",
                "category": "budgeting",
                "description": "Brings spending back into a manageable range.",
                "user_benefit_vi": "Giúp đưa chi tiêu về vùng kiểm soát được.",
                "when_to_recommend_vi": "Khi cần ổn định lại dòng tiền.",
                "when_not_to_recommend_vi": "",
                "supported_phases": ["protect_liquidity", "stabilize"],
                "supported_milestones": ["cashflow_stabilized"],
                "supported_goal_types": ["home_purchase"],
                "liquidity_profile": "high",
                "risk_level": "low",
                "requires_positive_cashflow": False,
                "requires_anomaly_resolved": False,
                "requires_buffer_present": False,
                "is_active": True,
                "sort_order": 10,
            }
        ]
        selection_payload = {
            "phase_recommendations": [
                {
                    "phase_type": "protect_liquidity",
                    "selected_services": [
                        {
                            "service_id": "budget_controls",
                            "role": "primary",
                            "why_recommended": "It helps contain spending pressure while the plan is still fragile.",
                            "expected_benefit": "The monthly baseline becomes easier to stabilize.",
                        }
                    ],
                    "explanation": "This service fits the current protect-first posture.",
                }
            ],
            "milestone_recommendations": [],
            "next_action_service": {
                "service_id": "budget_controls",
                "why_this_service_now": "It supports the immediate cashflow repair step.",
                "how_it_supports_transition": "It helps the roadmap move into stabilize with fewer uncontrolled outflows.",
            },
            "selection_warnings": [],
        }

        with patch("service_agent.agent.propose_candidates", return_value=(_candidate_set(), {"mode": "bedrock", "model_id": "test-model"})):
            with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                with patch("service_agent.banking_service_recommender.get_supabase_client", return_value=_FakeBankingServicesClient(banking_services)):
                    with patch("service_agent.banking_service_recommender._run_selection_layer", return_value=(selection_payload, {"mode": "bedrock", "model_id": "test-model"})):
                        result = run_service(envelope)

        contract = result["roadmap_contract"]
        current_phase = next(item for item in contract["phases"] if item["phase_type"] == "protect_liquidity")

        self.assertEqual("ok", result["diagnostics"]["service_recommendation_status"])
        self.assertEqual(1, len(current_phase["recommended_services"]))
        self.assertEqual("budget_controls", current_phase["recommended_services"][0]["service_id"])
        self.assertEqual("budget_controls", contract["next_best_action"]["recommended_service"]["service_id"])

    def test_run_service_keeps_roadmap_when_banking_services_are_unavailable(self) -> None:
        envelope = _service_envelope()

        class _UnavailableClient:
            configured = False

        with patch("service_agent.agent.propose_candidates", return_value=(_candidate_set(), {"mode": "bedrock", "model_id": "test-model"})):
            with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                with patch("service_agent.banking_service_recommender.get_supabase_client", return_value=_UnavailableClient()):
                    result = run_service(envelope)

        self.assertEqual("ok", result["status"])
        self.assertEqual("supabase_not_configured", result["diagnostics"]["service_recommendation_status"])
        self.assertTrue(result["roadmap_contract"]["phases"])
        self.assertEqual([], result["roadmap_contract"]["phases"][0]["recommended_services"])
        self.assertIn("service_selection_warnings", result["diagnostics"])

    def test_run_service_returns_preview_only_when_services_are_blocked(self) -> None:
        envelope = _service_envelope()
        banking_services = [
            {
                "service_id": "goal_bucket_setup",
                "display_name_vi": "Táº¡o tÃ i khoáº£n má»¥c tiÃªu",
                "display_name_en": "Goal Bucket Setup",
                "category": "goal_funding",
                "description": "Separates goal funds from daily cash.",
                "user_benefit_vi": "GiÃºp tÃ¡ch quá»¹ má»¥c tiÃªu khá»i tÃ i khoáº£n chi tiÃªu.",
                "when_to_recommend_vi": "Khi chuyá»ƒn sang accumulate.",
                "when_not_to_recommend_vi": "",
                "supported_phases": ["accumulate"],
                "supported_milestones": ["contribution_rhythm_active"],
                "supported_goal_types": ["vehicle_purchase"],
                "liquidity_profile": "medium",
                "risk_level": "low",
                "requires_positive_cashflow": True,
                "requires_anomaly_resolved": True,
                "requires_buffer_present": False,
                "is_active": True,
                "sort_order": 30,
            },
        ]

        with patch("service_agent.agent.propose_candidates", return_value=(_candidate_set(), {"mode": "bedrock", "model_id": "test-model"})):
            with patch("service_agent.agent.build_explanation", return_value=_explanation()):
                with patch("service_agent.banking_service_recommender.get_supabase_client", return_value=_FakeBankingServicesClient(banking_services)):
                    result = run_service(envelope)

        contract = result["roadmap_contract"]
        accumulate_phase = next(item for item in contract["phases"] if item["phase_type"] == "accumulate")

        self.assertEqual("preview_only", result["diagnostics"]["service_recommendation_status"])
        self.assertEqual([], accumulate_phase["recommended_services"])
        self.assertEqual("goal_bucket_setup", accumulate_phase["future_services_preview"][0]["service_id"])

    def test_milestones_follow_phase_progress_statuses(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))
        context.planner_state.anomaly_state = "none"
        context.planner_state.liquidity_pressure = "medium"
        from service_agent.roadmap_compiler import compile_roadmap

        contract = compile_roadmap(context, _candidate_set().candidates[0])
        statuses = {item["phase_type"]: item["status"] for item in contract.model_dump()["milestones"]}

        self.assertEqual("completed", statuses["protect_liquidity"])
        self.assertEqual("current", statuses["stabilize"])
        self.assertEqual("upcoming", statuses["accumulate"])

    def test_propose_candidates_returns_empty_set_when_model_fails(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))

        with patch("service_agent.layer2_reasoning_adapter.invoke_json_prompt", side_effect=RuntimeError("model down")):
            candidate_set, meta = propose_candidates(context)

        self.assertEqual([], candidate_set.candidates)
        self.assertEqual("model_error", meta["mode"])

    def test_propose_candidates_retries_after_first_invalid_attempt(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))

        with patch(
            "service_agent.layer2_reasoning_adapter.invoke_json_prompt",
            side_effect=[
                ({"schema_version": "service_candidate_set_v1", "readiness_class": "ready", "candidates": []}, {"mode": "bedrock", "model_id": "test-model"}),
                (_candidate_set().model_dump(), {"mode": "bedrock", "model_id": "test-model"}),
            ],
        ):
            candidate_set, meta = propose_candidates(context)

        self.assertTrue(candidate_set.candidates)
        self.assertTrue(meta.get("retried"))
        self.assertEqual("bedrock", meta["mode"])

    def test_invoke_json_prompt_extracts_tool_use_input(self) -> None:
        response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "submit_candidate_set",
                                "input": _candidate_set().model_dump(),
                            }
                        }
                    ]
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
        }

        with patch("service_agent.model_adapter._client") as client_factory:
            client_factory.return_value.converse.return_value = response
            payload, meta = invoke_json_prompt(
                "Return candidates",
                model_id="test-model",
                max_tokens=200,
                tool_name="submit_candidate_set",
                tool_schema={"type": "object"},
            )

        self.assertEqual("service_candidate_set_v1", payload["schema_version"])
        self.assertTrue(meta["tool_used"])
        self.assertEqual("tool_use", meta["stop_reason"])

    def test_build_explanation_reads_structured_model_output(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))
        from service_agent.roadmap_compiler import compile_roadmap

        contract = compile_roadmap(context, _candidate_set().candidates[0])
        model_payload = {
            "summary": "Here is your roadmap: start with protecting liquidity, then move through the next phases in a steadier order that fits your current goal and financial state.",
            "why_fit": "This path fits because liquidity needs protecting early and cashflow is still under pressure.",
            "current_phase_explanation": "Your current phase is protect liquidity first, so the immediate focus is to stop immediate cash leakage and reduce near-term liquidity risk.",
            "phase_explanations": [
                {
                    "phase_type": "protect_liquidity",
                    "why_this_phase_exists": "This phase exists to stop leakage first.",
                    "why_it_is_current_or_upcoming": "It is current because anomaly risk is active.",
                    "what_success_looks_like": "The cashflow baseline becomes clearer.",
                    "what_unlocks_next_phase": "That unlocks stabilize.",
                }
            ],
            "milestone_explanations": [
                {
                    "milestone_id": "ms_1",
                    "why_it_matters": "The roadmap needs a trustworthy baseline first.",
                    "what_needs_to_happen": "Flagged transactions need review.",
                    "what_changes_after_completion": "The roadmap can move into repair.",
                }
            ],
            "next_action_explanation": {
                "why_now": "Protecting cashflow comes first when anomaly or liquidity risk is active.",
                "what_to_check": "Review the highest-risk transactions and confirm whether leakage is real.",
                "what_success_looks_like": "You can explain the flagged outflows and contain them.",
                "what_happens_next": "The roadmap can move into stabilize.",
            },
            "projection_explanation": {
                "basis": "Projection uses current monthly savings capacity and current funded progress.",
                "pace_assessment": "The current pace is not yet enough.",
                "target_gap_commentary": "There is still a material gap to target.",
                "trend_commentary": "The projection remains cautious for now.",
            },
            "phase_service_explanations": [
                {
                    "phase_type": "protect_liquidity",
                    "selected_services": [{"service_id": "liquidity_guardrails", "display_name_vi": "Hàng rào thanh khoản", "role": "primary"}],
                    "explanation": "This service fits because liquidity protection comes first.",
                }
            ],
            "milestone_service_explanations": [
                {
                    "milestone_id": "ms_1",
                    "selected_services": [{"service_id": "anomaly_review", "display_name_vi": "Rà soát giao dịch bất thường", "role": "primary"}],
                    "explanation": "This service helps unlock the milestone cleanly.",
                }
            ],
            "next_action_service_explanation": {
                "selected_service": {"service_id": "liquidity_guardrails", "display_name_vi": "Hàng rào thanh khoản"},
                "explanation": "It is the clearest service to support the next action right now.",
            },
            "cautions": ["Keep projections directional only."],
            "confidence_note": "Confidence in the roadmap structure is stronger than confidence in the projection pace.",
        }

        with patch("service_agent.explanation_layer.invoke_json_prompt", return_value=(model_payload, {"mode": "bedrock", "model_id": "test-model"})):
            explanation, meta = build_explanation(contract)

        self.assertTrue(explanation.summary)
        self.assertTrue(explanation.phase_explanations)
        self.assertTrue(explanation.next_action_explanation.why_now)
        self.assertTrue(explanation.phase_service_explanations)
        self.assertTrue(explanation.milestone_service_explanations)
        self.assertTrue(explanation.next_action_service_explanation.explanation)
        self.assertEqual("bedrock", meta["mode"])

    def test_build_explanation_fact_pack_uses_selected_service_recommendations_only(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))
        from service_agent.roadmap_compiler import compile_roadmap

        contract = compile_roadmap(context, _candidate_set().candidates[0])
        captured_prompt = {}

        def _capture_prompt(prompt, **kwargs):
            captured_prompt["prompt"] = prompt
            return (
                {
                    "summary": "",
                    "why_fit": "",
                    "current_phase_explanation": "",
                    "phase_explanations": [],
                    "milestone_explanations": [],
                    "next_action_explanation": {
                        "why_now": "",
                        "what_to_check": "",
                        "what_success_looks_like": "",
                        "what_happens_next": "",
                    },
                    "projection_explanation": {
                        "basis": "",
                        "pace_assessment": "",
                        "target_gap_commentary": "",
                        "trend_commentary": "",
                    },
                    "phase_service_explanations": [],
                    "milestone_service_explanations": [],
                    "next_action_service_explanation": {"selected_service": {}, "explanation": ""},
                    "cautions": [],
                    "confidence_note": "",
                },
                {"mode": "bedrock", "model_id": "test-model"},
            )

        with patch("service_agent.explanation_layer.invoke_json_prompt", side_effect=_capture_prompt):
            build_explanation(contract)

        fact_pack_json = captured_prompt["prompt"].split("Contract facts:\n", 1)[1]
        fact_pack = json.loads(fact_pack_json)
        self.assertEqual([], fact_pack["service_recommendations"])

    def test_build_explanation_returns_empty_payload_when_model_fails(self) -> None:
        request = SpecialistRequestEnvelope.model_validate(_service_envelope())
        context = classify_request(normalize_request(request))
        from service_agent.roadmap_compiler import compile_roadmap

        contract = compile_roadmap(context, _candidate_set().candidates[0])

        with patch("service_agent.explanation_layer.invoke_json_prompt", side_effect=RuntimeError("summary model down")):
            explanation, meta = build_explanation(contract)

        self.assertEqual("", explanation.summary)
        self.assertEqual("model_error", meta["mode"])


if __name__ == "__main__":
    unittest.main()
