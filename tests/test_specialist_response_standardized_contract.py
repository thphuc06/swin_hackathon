from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from strands_orchestrator.specialist_response import apply_specialist_response


class SpecialistResponseStandardizedContractTests(unittest.TestCase):
    def test_planner_response_prefers_standardized_contract_human_readable_payload(self) -> None:
        state = {
            "trace_id": "trc_test",
            "tool_calls": ["run_planner_agent_v1"],
            "tool_outputs": {},
            "tool_errors": {},
            "response_meta": {"reason_codes": []},
            "agent_outputs": {
                "planner": {
                    "schema_version": "v1",
                    "agent_id": "planner",
                    "agent_version": "0.1.0",
                    "tool_name": "run_planner_agent_v1",
                    "status": "ok",
                    "correlation": {
                        "session_id": "sess_1",
                        "request_id": "req_1",
                        "trace_id": "trc_test",
                        "parent_request_id": "",
                    },
                    "result": {
                        "summary": "Legacy planner summary.",
                        "key_facts": [],
                        "recommendations": [],
                        "next_actions": [],
                        "warnings": [],
                        "citations": [],
                    },
                    "standardized_contract": {
                        "contract_spec_version": "financial_advisory_contract_v1",
                        "txt_render_spec_version": "financial_advisory_txt_v1",
                        "report_title": "Financial Advisory Report",
                        "section_order": [
                            "HEADER",
                            "EXECUTIVE_SUMMARY",
                            "CORE_FINANCIAL_ANALYSIS",
                            "PLANNER_CORE_COMPUTED_SIGNALS",
                            "FINANCIAL_USAGE_INSIGHT",
                            "STRATEGY_OPTIONS",
                            "BANKING_SERVICE_RECOMMENDATIONS",
                            "ACTIONABLE_NEXT_STEPS",
                            "EVIDENCE_TOOL_GROUNDING",
                        ],
                        "sections": {
                            "HEADER": {
                                "report_title": "Financial Advisory Report",
                                "analysis_window_label": "2025-09-01..2026-02-28",
                                "planner_intent": "planning",
                                "execution_mode": "deterministic",
                                "planner_status": "ok",
                            },
                            "EXECUTIVE_SUMMARY": {
                                "observed_income_total": 255210000.0,
                                "observed_expense_total": 254266000.0,
                                "observed_net_cashflow": 944000.0,
                                "computed_financial_stability_band": "watch",
                                "computed_risk_band": "moderate",
                                "computed_planning_readiness": "ready",
                            },
                            "CORE_FINANCIAL_ANALYSIS": {
                                "observed_income": {
                                    "total_income": 255210000.0,
                                    "baseline_monthly_income": 42535000.0,
                                },
                                "observed_expenses": {
                                    "total_spend": 254266000.0,
                                    "budget_drift": [{"category": "Dining", "status": "over"}],
                                },
                                "observed_cashflow": {
                                    "net_cashflow": 944000.0,
                                    "forecast_probability_negative_net": 0.36,
                                },
                                "observed_recurring_patterns": {
                                    "fixed_cost_ratio": 0.41,
                                    "drift_alerts": ["rent_drift", "utilities_drift"],
                                },
                                "observed_anomaly": {
                                    "flags": ["merchant_spike", "category_spike"],
                                },
                                "computed_risk": {
                                    "emergency_runway_months": 4.5,
                                },
                            },
                            "PLANNER_CORE_COMPUTED_SIGNALS": {
                                "trust_core": {
                                    "mean_confidence_score": 0.82,
                                    "mean_trust_score": 0.79,
                                },
                                "planning_and_execution_readiness": {
                                    "overall_groundedness": "grounded",
                                    "execution_readiness": "allowed_within_policy",
                                },
                                "evidence_quality_and_agent_use": {
                                    "human_feedback_requested": True,
                                },
                            },
                            "FINANCIAL_USAGE_INSIGHT": {
                                "inferred_spending_habits": "concentrated",
                                "inferred_cashflow_habits": "positive",
                                "inferred_budgeting_discipline": "watch",
                                "positive_signals": ["positive_observed_cashflow"],
                                "attention_signals": ["budget_overrun_detected"],
                            },
                            "STRATEGY_OPTIONS": {
                                "balanced": {
                                    "status": "active",
                                    "focus": "Stabilize monthly cashflow while keeping planned allocations in place.",
                                    "rationale": "Use the planner baseline and jar allocation guidance as the default operating mode.",
                                    "confidence": "ready",
                                }
                            },
                            "BANKING_SERVICE_RECOMMENDATIONS": {
                                "recommendations": [
                                    {
                                        "service_category": "budget_controls_and_spend_limits",
                                        "why": "Budget drift is already present in the observed spending window.",
                                        "confidence": "medium",
                                        "grounded_by": ["spend_analytics_v1.budget_drift"],
                                    }
                                ]
                            },
                            "ACTIONABLE_NEXT_STEPS": {
                                "steps": [
                                    {
                                        "priority": 1,
                                        "action": "Review the largest recurring bill this week",
                                        "owner": "user",
                                        "timeframe": "this week",
                                    }
                                ]
                            },
                            "EVIDENCE_TOOL_GROUNDING": {
                                "tools_executed": ["spend_analytics_v1", "cashflow_forecast_v1"],
                            },
                        },
                        "human_readable": {
                            "summary": "Structured summary.",
                            "key_facts": ["Observed net cashflow: 944000.0."],
                            "recommendations": [
                                {
                                    "title": "Review recurring bills",
                                    "rationale": "Recurring drift is visible in the standardized contract.",
                                    "priority": "high",
                                }
                            ],
                            "next_actions": [
                                {
                                    "action": "Review the largest recurring bill this week",
                                    "owner": "user",
                                    "timeframe": "this week",
                                }
                            ],
                            "warnings": [{"code": "directional_only", "message": "Treat forecast as directional."}],
                            "citations": [{"source_id": "src_1", "title": "services_loans_and_credit.md"}],
                        },
                    },
                    "warnings": [],
                    "errors": [],
                }
            },
        }

        updated = apply_specialist_response(state)

        self.assertIn("## Here's the big picture", updated["response"])
        self.assertIn(
            "Over this period, your finances stayed slightly positive, with income ahead of spending by 944,000.",
            updated["response"],
        )
        self.assertIn("Right now, your finances look okay, but they need a bit of watching.", updated["response"])
        self.assertIn("You have room to plan more confidently from here.", updated["response"])
        self.assertIn("## Snapshot", updated["response"])
        self.assertIn("| Analysis window | 2025-09-01..2026-02-28 |", updated["response"])
        self.assertIn("| Total income | 255,210,000 |", updated["response"])
        self.assertIn("| Observed net cashflow | 944,000 |", updated["response"])
        self.assertIn("| Baseline monthly income | 42,535,000 |", updated["response"])
        self.assertIn("## What stands out", updated["response"])
        self.assertIn("Your income stayed ahead of expenses by about 944,000 over this window.", updated["response"])
        self.assertIn("The main unusual signals were an unusual spike with one merchant, an unusual spike in one spending category.", updated["response"])
        self.assertIn("Positive signals: observed cashflow stayed positive.", updated["response"])
        self.assertIn("The main thing to watch is some categories appear to be running over budget.", updated["response"])
        self.assertIn("## Forecast and risk outlook", updated["response"])
        self.assertIn("The forecast still leans negative, with about a 36.0% chance of negative cashflow.", updated["response"])
        self.assertIn("Your current risk band is moderate.", updated["response"])
        self.assertIn("Planner confidence is around 0.82 and overall trust is around 0.79", updated["response"])
        self.assertIn("directional only", updated["response"])
        self.assertIn("## Strategy options", updated["response"])
        self.assertIn("Balanced: Stabilize monthly cashflow while keeping planned allocations in place.", updated["response"])
        self.assertIn("## Recommendations", updated["response"])
        self.assertIn("**Review recurring bills** - recurring drift is visible in the standardized contract.", updated["response"])
        self.assertIn("**Tighten budget controls** - it helps slow budget drift before it becomes a bigger cashflow problem.", updated["response"])
        self.assertIn("## Next steps", updated["response"])
        self.assertIn("Review the largest recurring bill this week (this week)", updated["response"])
        self.assertIn("## Notes and cautions", updated["response"])
        self.assertIn(
            "Forecast and allocation signals are useful for direction, but not precise enough to treat as exact predictions.",
            updated["response"],
        )
        self.assertNotIn("## Helpful service ideas", updated["response"])
        self.assertNotIn("...", updated["response"])
        self.assertNotIn("spend_analytics_v1", updated["response"])
        self.assertNotIn("cashflow_forecast_v1", updated["response"])
        self.assertNotIn("category id", updated["response"].lower())
        self.assertNotIn("Forecast uncertainty: {", updated["response"])
        self.assertNotIn("Trace:", updated["response"])
        self.assertNotIn("Tools:", updated["response"])
        self.assertNotIn("Citations:", updated["response"])
        self.assertNotIn("directional_only:", updated["response"])
        self.assertEqual(
            "financial_advisory_contract_v1",
            updated["response_meta"]["specialist"]["standardized_contract"]["contract_spec_version"],
        )
        self.assertIn("planner_standardized_contract", updated["response_meta"]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
