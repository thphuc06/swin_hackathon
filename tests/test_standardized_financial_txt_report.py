from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from planner_agent.contracts import PlannerNextAction, PlannerRecommendation, PlannerResult, SpecialistRequestEnvelope
from planner_agent.reporting import (
    CONTRACT_SPEC_VERSION,
    REPORT_SPEC_VERSION,
    build_standardized_contract,
    build_standardized_txt_report,
    build_standardized_txt_report_from_contract,
)


def _request() -> SpecialistRequestEnvelope:
    return SpecialistRequestEnvelope.model_validate(
        {
            "schema_version": "v1",
            "actor": {
                "actor_id": "usr_123",
                "user_id": "usr_123",
                "tenant_id": "tenant_a",
                "scopes": ["chat:invoke", "finance:read"],
            },
            "correlation": {
                "session_id": "sess_123",
                "request_id": "req_123",
                "trace_id": "trc_123",
                "parent_request_id": "",
                "request_timestamp": "2026-03-19T10:00:00Z",
            },
            "request": {
                "prompt": "Analyze my finances over the last 6 months.",
                "intent": "planning",
                "policy_flags": {},
                "user_context": {},
                "goals": [],
                "session_summary": "",
            },
            "routing": {
                "specialist_id": "planner",
                "tool_name": "run_planner_agent_v1",
            },
        }
    )


class StandardizedFinancialTxtReportTests(unittest.TestCase):
    def test_report_contains_fixed_sections_and_grounded_fields(self) -> None:
        planner_result = PlannerResult(
            summary="Grounded planner summary.",
            key_facts=["Recent spend total: 254266000.0."],
            recommendations=[
                PlannerRecommendation(
                    title="Use a jar allocation baseline",
                    rationale="Grounded by spend and forecast outputs.",
                    priority="medium",
                    expected_impact="Improves monthly budget stability.",
                )
            ],
            next_actions=[
                PlannerNextAction(
                    action="Review recurring bill drift this month",
                    owner="user",
                    timeframe="this month",
                )
            ],
            tool_trace=[],
            warnings=[],
        )
        tool_results = {
            "spend_analytics_v1": {
                "total_income": 255210000.0,
                "total_spend": 254266000.0,
                "net_cashflow": 944000.0,
                "spend_volatility": {"daily_average": 1000.0, "daily_stddev": 50.0},
                "budget_drift": [],
                "top_merchants": [{"merchant": "ACME", "amount": 100.0}],
                "category_breakdown": [{"category_name": "Bills", "share": 0.3}],
                "essential_vs_discretionary_breakdown": {"essential": 10.0, "discretionary": 5.0, "unknown": 0.0},
                "top_category_share": 0.3,
                "window": {"start": "2025-09-21", "end": "2026-03-19", "history_days": 180},
                "reliability": {
                    "confidence_score": 0.82,
                    "confidence_level": "high",
                    "abstain_recommended": False,
                    "reason_codes": [],
                    "components": {"data_quality": 0.82},
                },
                "trust": {"trust_score": 0.83, "trust_level": "high", "caps_applied": []},
                "agent_use": {"usage_mode": "direct", "monitoring_status": "healthy", "human_feedback_recommended": False},
            },
            "cashflow_forecast_v1": {
                "probability_negative_net": 0.21,
                "confidence_band": {"p10_avg": -100.0, "p50_avg": 500.0, "p90_avg": 1500.0},
                "model_evidence": {"native_uncertainty": {"source": "heuristic_sigma_band", "p10": -100.0, "p50": 500.0, "p90": 1500.0}},
                "validation": {"calibration_monitoring": {"confidence_score": 0.74, "monitoring_status": "healthy"}},
                "reliability": {
                    "confidence_score": 0.74,
                    "confidence_level": "medium",
                    "abstain_recommended": False,
                    "reason_codes": [],
                    "components": {"data_quality": 0.7, "calibration": 0.75},
                },
                "trust": {"trust_score": 0.72, "trust_level": "medium", "caps_applied": []},
                "agent_use": {"usage_mode": "advisory_only", "monitoring_status": "watch", "human_feedback_recommended": False},
            },
            "jar_allocation_suggest_v1": {
                "baseline_monthly_income": 42535000.0,
                "allocations": [{"jar_name": "Bills", "target_amount": 1000.0}],
                "reliability": {"confidence_score": 0.7, "confidence_level": "medium", "abstain_recommended": False, "reason_codes": [], "components": {"forecast_reliability": 0.74}},
                "trust": {"trust_score": 0.68, "trust_level": "medium", "caps_applied": ["forecast_trust_cap"]},
                "agent_use": {"usage_mode": "advisory_only", "monitoring_status": "watch", "human_feedback_recommended": False},
            },
            "risk_profile_non_investment_v1": {
                "risk_band": "moderate",
                "risk_score": 0.41,
                "emergency_runway_months": 7.5,
                "signals": [{"name": "cashflow_volatility", "value": 0.2}],
                "drivers": {"volatility": 0.2},
                "summary": {"balance_context": {"latest_balance": 12000000.0}},
                "reliability": {"confidence_score": 0.77, "confidence_level": "medium", "abstain_recommended": False, "reason_codes": [], "components": {"history": 0.8}},
                "trust": {"trust_score": 0.75, "trust_level": "medium", "caps_applied": []},
                "agent_use": {"usage_mode": "direct", "monitoring_status": "healthy", "human_feedback_recommended": False},
            },
            "recurring_cashflow_detect_v1": {
                "recurring_income": [{"merchant": "Salary", "recurrence_confidence": 0.9}],
                "recurring_expense": [{"merchant": "Rent", "recurrence_confidence": 0.88}],
                "fixed_cost_ratio": 0.45,
                "drift_alerts": [],
                "reliability": {"confidence_score": 0.79, "confidence_level": "medium", "abstain_recommended": False, "reason_codes": [], "components": {"sample_sufficiency": 0.8}},
                "trust": {"trust_score": 0.77, "trust_level": "medium", "caps_applied": []},
                "agent_use": {"usage_mode": "direct", "monitoring_status": "healthy", "human_feedback_recommended": False},
            },
            "anomaly_signals_v1": {
                "flags": ["merchant_spike"],
                "runtime_alerts": {"merchant_spike": {"flag": True}},
                "transaction_outliers": {"summary": {"top_probability": 0.61}},
                "feedback_request": {"show_to_user": True},
                "detector_agreement": {"agreement_score": 0.5},
                "validation": {"calibration_monitoring": {"confidence_score": 0.63, "monitoring_status": "watch"}},
                "reliability": {"confidence_score": 0.63, "confidence_level": "medium", "abstain_recommended": False, "reason_codes": [], "components": {"signal_strength": 0.61}},
                "trust": {"trust_score": 0.6, "trust_level": "medium", "caps_applied": []},
                "agent_use": {"usage_mode": "advisory_only", "monitoring_status": "watch", "human_feedback_recommended": True},
            },
            "suitability_guard_v1": {
                "decision": "allow",
                "allow": True,
                "matched_rules": ["non_investment_intent"],
                "decision_explanation": "Prompt classified as non-investment planning, so the request is allowed.",
                "reliability": {"confidence_score": 0.99, "confidence_level": "high", "abstain_recommended": False, "reason_codes": ["non_investment_intent"], "components": {"policy_match_quality": 0.99}},
                "trust": {"trust_score": 0.99, "trust_level": "high", "caps_applied": []},
                "agent_use": {"usage_mode": "direct", "monitoring_status": "healthy", "human_feedback_recommended": False},
            },
        }

        contract = build_standardized_contract(
            request=_request(),
            planner_result=planner_result,
            planner_status="ok",
            tool_results=tool_results,
            profile={"display_name": "Hoang Phuc"},
            runtime_metadata={"runtime_source": "planner_core_direct"},
        )
        report = build_standardized_txt_report_from_contract(contract)

        self.assertEqual(CONTRACT_SPEC_VERSION, contract["contract_spec_version"])
        self.assertEqual("Grounded planner summary.", contract["human_readable"]["summary"])
        self.assertIn(f"=== BEGIN {REPORT_SPEC_VERSION.upper()} ===", report)
        self.assertIn("## HEADER", report)
        self.assertIn("## EXECUTIVE_SUMMARY", report)
        self.assertIn("## CORE_FINANCIAL_ANALYSIS", report)
        self.assertIn("## PLANNER_CORE_COMPUTED_SIGNALS", report)
        self.assertIn("## EVIDENCE_TOOL_GROUNDING", report)
        self.assertIn("report_title: Financial Advisory Report", report)
        self.assertIn("user_display_name: Hoang Phuc", report)
        self.assertIn("observed_net_cashflow: 944000.0", report)
        self.assertIn("\"risk_band\": \"moderate\"", report)
        self.assertIn("\"service_category\": \"transaction_alerts_and_manual_verification\"", report)

    def test_report_keeps_not_applicable_and_insufficient_data_slots(self) -> None:
        planner_result = PlannerResult(
            summary="No grounded data available.",
            key_facts=[],
            recommendations=[],
            next_actions=[],
            tool_trace=[],
            warnings=[],
        )
        tool_results = {
            "spend_analytics_v1": {
                "total_income": 0.0,
                "total_spend": 0.0,
                "net_cashflow": 0.0,
                "window": {"start": "2025-09-21", "end": "2026-03-19", "history_days": 180},
                "reliability": {
                    "confidence_score": 0.2,
                    "confidence_level": "low",
                    "abstain_recommended": True,
                    "reason_codes": ["no_transactions_in_window"],
                    "components": {},
                },
                "trust": {"trust_score": 0.2, "trust_level": "low", "caps_applied": []},
                "agent_use": {"usage_mode": "abstain", "monitoring_status": "alert", "human_feedback_recommended": False},
            }
        }

        report = build_standardized_txt_report(
            request=_request(),
            planner_result=planner_result,
            planner_status="partial",
            tool_results=tool_results,
            profile={},
            runtime_metadata={"runtime_source": "planner_core_direct"},
        )

        self.assertIn("computed_financial_stability_band: insufficient_data", report)
        self.assertIn("\"status\": \"not_applicable\"", report)
        self.assertIn("computed_affordability: {\"reason\": \"No first-class affordability tool is wired into the current planner path.\", \"status\": \"not_applicable\"}", report)
