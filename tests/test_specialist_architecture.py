from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from planner_agent.agent import run_planner
from service_agent.agent import run_service
from service_agent.contracts import ServiceExplanation
from stock.adapter import run_stock
from strands_orchestrator.specialist import (
    build_specialist_payload,
    call_specialist_tool,
    get_specialist_by_id,
    select_specialist_for_state,
    validate_specialist_output,
)
from strands_orchestrator.nodes.tool_invocation_node import tool_invocation_node
from strands_orchestrator.specialist_response import apply_specialist_response


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


def _request_envelope(intent: str = "planning") -> dict:
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
            "request_timestamp": "2026-03-14T12:00:00Z",
        },
        "request": {
            "prompt": "Create a monthly budget plan",
            "intent": intent,
            "policy_flags": {"education_only": True},
            "user_context": {},
            "goals": [],
            "session_summary": "",
        },
        "routing": {
            "specialist_id": "",
            "tool_name": "",
        },
    }


class SpecialistArchitectureTests(unittest.TestCase):
    def test_catalog_selection_is_specialist_first(self) -> None:
        planning_state = {
            "intent": "planning",
            "extraction": {"confidence": 0.22},
            "prompt": "Create a monthly budget plan",
        }
        stock_state = {
            "intent": "invest",
            "extraction": {"confidence": 0.18},
            "prompt": "Help me think about stocks",
        }

        planning_specialist, planning_meta = select_specialist_for_state(planning_state)
        stock_specialist, stock_meta = select_specialist_for_state(stock_state)

        self.assertIsNotNone(planning_specialist)
        self.assertEqual("planner", planning_specialist.id)
        self.assertEqual("specialist_catalog_fallback", planning_meta["selection_mode"])
        self.assertIsNotNone(stock_specialist)
        self.assertEqual("stock", stock_specialist.id)
        self.assertEqual("specialist_catalog_fallback", stock_meta["selection_mode"])

    def test_service_selection_prefers_roadmap_prompts(self) -> None:
        service_state = {
            "intent": "planning",
            "prompt": "Help me build a financial roadmap to buy a car in 12 months",
            "extraction": {"confidence": 0.41},
            "request_envelope": _request_envelope(intent="planning"),
            "session_memory": {"last_planner_contract": {"sections": {"EXECUTIVE_SUMMARY": {}}}},
        }

        specialist, meta = select_specialist_for_state(service_state)

        self.assertIsNotNone(specialist)
        self.assertEqual("service", specialist.id)
        self.assertEqual("service_roadmap_hint", meta["selection_mode"])

    def test_payload_preserves_actor_and_correlation(self) -> None:
        descriptor = get_specialist_by_id("stock")
        self.assertIsNotNone(descriptor)

        state = {
            "prompt": "Help me think about stocks",
            "intent": "invest",
            "user_id": "usr_123",
            "request_id": "req_abc",
            "session_id": "usr_123:default",
            "trace_id": "trc_xyz",
            "request_timestamp": "2026-03-14T12:00:00Z",
            "education_only": True,
            "user_profile": {"risk_appetite": "moderate"},
            "request_envelope": _request_envelope(intent="invest"),
            "agent_outputs": {
                "planner": {
                    "result": {"summary": "Budget is stable."},
                }
            },
        }

        payload = build_specialist_payload(descriptor, state)

        self.assertEqual(state["request_envelope"]["actor"], payload["actor"])
        self.assertEqual(state["request_envelope"]["correlation"], payload["correlation"])
        self.assertEqual("stock", payload["routing"]["specialist_id"])
        self.assertEqual("run_stock_agent_v1", payload["routing"]["tool_name"])
        self.assertEqual("Budget is stable.", payload["request"]["user_context"]["planner_summary"])

    def test_service_payload_ignores_stock_context_from_session_memory(self) -> None:
        descriptor = get_specialist_by_id("service")
        self.assertIsNotNone(descriptor)

        state = {
            "prompt": "Build me a home purchase roadmap.",
            "intent": "planning",
            "user_id": "usr_123",
            "request_id": "req_service",
            "session_id": "usr_123:default",
            "trace_id": "trc_service",
            "request_timestamp": "2026-03-14T12:00:00Z",
            "education_only": True,
            "user_profile": {"risk_appetite": "moderate"},
            "request_envelope": _request_envelope(intent="planning"),
            "session_memory": {
                "last_planner_summary": "Cashflow is positive.",
                "last_stock_context": {
                    "summary": "Vietnam bank stocks look mixed right now.",
                    "suitability_status": "warn",
                    "market_tone": "cautious",
                    "warning_flags": ["market_caution"],
                    "source": "session_memory",
                },
            },
        }

        payload = build_specialist_payload(descriptor, state)

        self.assertNotIn("stock_context", payload["request"]["user_context"])

    def test_stock_tool_invocation_routes_through_specialist_runtime(self) -> None:
        state = {
            "response": "",
            "clarification": {"pending": False},
            "selected_specialist_id": "stock",
            "selected_agent": "",
            "prompt": "Please give an educational overview of Vietnam bank stocks.",
            "intent": "invest",
            "education_only": True,
            "user_profile": {"risk_appetite": "moderate"},
            "user_id": "usr_123",
            "user_token": "Bearer token",
            "request_id": "req_abc",
            "session_id": "sess_abc",
            "trace_id": "trc_abc",
            "request_timestamp": "2026-03-22T12:00:00Z",
            "tool_outputs": {
                "risk_profile_non_investment_v1": {"risk_band": "moderate", "emergency_runway_months": 6.0},
                "spend_analytics_v1": {"net_cashflow": 2500000},
                "anomaly_signals_v1": {"flags": []},
            },
            "tool_calls": [],
            "agent_outputs": {},
            "tool_errors": {},
            "response_meta": {"reason_codes": []},
            "extraction": {"slots": {"horizon_months": 12}},
            "request_envelope": _request_envelope(intent="invest"),
        }
        stock_result = {
            "schema_version": "v1",
            "agent_id": "stock",
            "agent_version": "0.1.0",
            "tool_name": "run_stock_agent_v1",
            "status": "ok",
            "correlation": {
                "session_id": "sess_abc",
                "request_id": "req_abc",
                "trace_id": "trc_abc",
                "parent_request_id": "req_abc",
                "request_timestamp": "2026-03-22T12:00:00Z",
            },
            "result": {
                "summary": "Specialist stock summary.",
                "recommendations": [],
                "alternatives": [{"ticker": "VCB", "rationale": "Highlighted in the latest external market snapshot."}],
                "suitability": {"status": "warn", "reason": "education_only"},
                "market_notes": ["Banking stocks remain active."],
                "citations": [],
                "warnings": [],
            },
            "warnings": [],
            "errors": [],
        }

        with patch(
            "strands_orchestrator.nodes.tool_invocation_node.call_specialist_tool",
            return_value=stock_result,
        ) as specialist_call:
            updated = tool_invocation_node(state)

        specialist_call.assert_called_once()
        self.assertIn("run_stock_agent_v1", updated["tool_calls"])
        self.assertIn("stock", updated["agent_outputs"])
        self.assertEqual("Specialist stock summary.", updated["agent_outputs"]["stock"]["result"]["summary"])
        self.assertEqual("warn", updated["agent_outputs"]["stock"]["result"]["suitability"]["status"])
        self.assertEqual("VCB", updated["agent_outputs"]["stock"]["result"]["alternatives"][0]["ticker"])
        validate_specialist_output("run_stock_agent_v1.output.json", updated["agent_outputs"]["stock"])

    def test_service_tool_invocation_hidden_prefetch_only_uses_planner_context(self) -> None:
        state = {
            "response": "",
            "clarification": {"pending": False},
            "selected_specialist_id": "service",
            "selected_agent": "",
            "prompt": "Build me a roadmap to buy a home in 36 months.",
            "intent": "planning",
            "education_only": True,
            "user_profile": {"risk_appetite": "moderate"},
            "user_id": "usr_123",
            "user_token": "Bearer token",
            "request_id": "req_service_hidden",
            "session_id": "sess_service_hidden",
            "trace_id": "trc_service_hidden",
            "request_timestamp": "2026-03-23T09:00:00Z",
            "tool_outputs": {},
            "tool_calls": [],
            "agent_outputs": {},
            "tool_errors": {},
            "response_meta": {"reason_codes": []},
            "extraction": {"slots": {"goal_type": "home_purchase", "target_amount": 2000000000, "horizon_months": 36}},
            "request_envelope": _request_envelope(intent="planning"),
        }

        planner_result = {
            "agent_id": "planner",
            "tool_name": "run_planner_agent_v1",
            "status": "ok",
            "result": {"summary": "Planner summary."},
            "standardized_contract": {
                "contract_spec_version": "financial_advisory_contract_v1",
                "sections": {"EXECUTIVE_SUMMARY": {"observed_net_cashflow": 12000000}},
            },
        }
        service_result = {
            "agent_id": "service",
            "tool_name": "run_service_agent_v1",
            "status": "ok",
            "result": {"summary": "Service roadmap summary."},
            "roadmap_contract": {"status": "ready", "current_phase": "stabilize"},
            "explanation": {"summary": "Service roadmap summary."},
        }
        observed_service_payload = {}

        def fake_call_specialist_tool(descriptor, payload, *_args, **_kwargs):
            if descriptor.id == "planner":
                return planner_result
            if descriptor.id == "service":
                observed_service_payload.update(payload)
                return service_result
            raise AssertionError(f"Unexpected specialist invocation: {descriptor.id}")

        with patch("strands_orchestrator.nodes.tool_invocation_node.validate_specialist_output"):
            with patch("strands_orchestrator.nodes.tool_invocation_node.call_specialist_tool", side_effect=fake_call_specialist_tool):
                updated = tool_invocation_node(state)

        self.assertIn("planner", updated["agent_outputs"])
        self.assertIn("service", updated["agent_outputs"])
        self.assertNotIn("stock", updated["agent_outputs"])
        self.assertEqual("Planner summary.", observed_service_payload["request"]["user_context"]["planner_summary"])
        self.assertNotIn("stock_context", observed_service_payload["request"]["user_context"])

    def test_service_payload_includes_planner_contract_from_session_memory(self) -> None:
        descriptor = get_specialist_by_id("service")
        self.assertIsNotNone(descriptor)

        planner_contract = {
            "contract_spec_version": "financial_advisory_contract_v1",
            "sections": {"EXECUTIVE_SUMMARY": {"observed_net_cashflow": -1000}},
        }
        state = {
            "prompt": "Build me a roadmap to buy a car in 12 months",
            "intent": "planning",
            "user_id": "usr_123",
            "request_id": "req_abc",
            "session_id": "usr_123:default",
            "trace_id": "trc_xyz",
            "request_timestamp": "2026-03-14T12:00:00Z",
            "education_only": True,
            "user_profile": {"risk_appetite": "moderate"},
            "request_envelope": _request_envelope(intent="planning"),
            "session_memory": {"last_planner_contract": planner_contract, "last_planner_summary": "Cashflow is tight."},
            "extraction": {"slots": {"goal_type": "vehicle_purchase", "target_amount": 60000000, "horizon_months": 12}},
        }

        payload = build_specialist_payload(descriptor, state)

        self.assertEqual(state["request_envelope"]["actor"], payload["actor"])
        self.assertEqual(planner_contract, payload["request"]["user_context"]["planner_standardized_contract"])
        self.assertEqual("Cashflow is tight.", payload["request"]["user_context"]["planner_summary"])
        self.assertEqual(1, len(payload["request"]["goals"]))

    def test_service_runs_in_process_with_structured_contract(self) -> None:
        envelope = _request_envelope(intent="planning")
        envelope["routing"] = {"specialist_id": "service", "tool_name": "run_service_agent_v1"}
        envelope["request"]["prompt"] = "Build me a roadmap to buy a car in 12 months"
        envelope["request"]["goals"] = [
            {
                "goal_type": "vehicle_purchase",
                "target_amount": 60000000,
                "target_timeline_months": 12,
                "priority": "high",
            }
        ]
        envelope["request"]["user_context"] = {
            "planner_state": {
                "cashflow_status": "negative",
                "savings_capacity": {"amount_monthly": 4000000, "label": "moderate"},
                "runway_months": 2.4,
                "liquidity_pressure": "high",
                "anomaly_state": "active",
                "readiness_label": "cautious",
                "feasibility_hint": "medium",
                "risk_band": "moderate",
            }
        }

        candidate_set = {
            "schema_version": "service_candidate_set_v1",
            "readiness_class": "ready",
            "candidates": [
                {
                    "candidate_id": "cand_protect_first",
                    "journey_pattern": "protect_then_stabilize_then_accumulate_then_review",
                    "phase_types": ["protect_liquidity", "stabilize", "accumulate", "readiness_review"],
                    "current_phase_hint": "protect_liquidity",
                    "service_candidates": [
                        {"phase_type": "protect_liquidity", "service_ids": ["anomaly_review", "liquidity_guardrails"]},
                        {"phase_type": "stabilize", "service_ids": ["budget_controls", "recurring_expense_cleanup"]},
                        {"phase_type": "accumulate", "service_ids": ["goal_bucket_setup", "auto_save_activation"]},
                    ],
                    "proposal_confidence": 0.74,
                    "model_fit_score": 0.7,
                }
            ],
        }
        explanation = (
            ServiceExplanation(
                summary="Here is your roadmap.",
                why_fit="This path fits because liquidity needs protecting early.",
                current_phase_explanation="Your current phase is protect liquidity first, so the immediate focus is to stop immediate cash leakage and reduce near-term liquidity risk.",
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
                    "trend_commentary": "The projection remains cautious for now.",
                },
                cautions=["Keep projections directional only."],
                confidence_note="Confidence in the roadmap structure is stronger than confidence in the projection pace.",
            ),
            {"mode": "bedrock", "model_id": "test-model"},
        )

        with patch("service_agent.agent.propose_candidates", return_value=(candidate_set, {"mode": "bedrock", "model_id": "test-model"})):
            with patch("service_agent.agent.build_explanation", return_value=explanation):
                result = run_service(envelope)

        self.assertEqual("service", result["agent_id"])
        self.assertIn(result["status"], {"ok", "partial"})
        self.assertIn("roadmap_contract", result)
        self.assertIn("current_phase", result["roadmap_contract"])
        validate_specialist_output("run_service_agent_v1.output.json", result)

    def test_specialist_response_promotes_planner_and_service_side_payloads(self) -> None:
        planner_state = {
            "agent_outputs": {
                "planner": {
                    "agent_id": "planner",
                    "status": "ok",
                    "result": {"summary": "Planner summary."},
                    "standardized_contract": {
                        "contract_spec_version": "financial_advisory_contract_v1",
                        "txt_render_spec_version": "planner_text_v1",
                        "report_title": "Planner",
                        "section_order": [],
                        "sections": {},
                        "human_readable": {"summary": "Planner summary."},
                    },
                }
            },
            "response_meta": {"reason_codes": []},
            "tool_errors": {},
        }
        planner_next = apply_specialist_response(planner_state)
        self.assertEqual("Planner summary.", planner_next["planner_context"]["planner_summary"])
        self.assertIn("planner_standardized_contract", planner_next["planner_context"])

        service_state = {
            "agent_outputs": {
                "service": {
                    "agent_id": "service",
                    "status": "ok",
                    "result": {"summary": "Roadmap summary."},
                    "roadmap_contract": {
                        "schema_version": "service_roadmap_contract_v1",
                        "status": "ready",
                        "current_phase": "protect_liquidity",
                        "phase_sequence": ["protect_liquidity", "stabilize", "accumulate"],
                        "goal": {"goal_type": "vehicle_purchase"},
                        "milestones": [{"title": "Resolve the immediate leakage or anomaly risk", "phase_type": "protect_liquidity", "status": "current"}],
                    },
                    "explanation": {
                        "summary": "Roadmap summary.",
                        "why_fit": "This path fits because you need to protect liquidity first.",
                        "current_phase_explanation": "The current focus is to protect your cashflow before pushing harder toward the goal.",
                        "phase_explanations": [],
                        "milestone_explanations": [],
                        "next_action_explanation": {
                            "why_now": "Handle the highest-risk transactions first so the rest of the plan can move on firmer ground.",
                            "what_to_check": "Review the flagged transactions.",
                            "what_success_looks_like": "The leakage risk is contained.",
                            "what_happens_next": "The roadmap can move into repair."
                        },
                        "projection_explanation": {
                            "basis": "Projection uses current monthly capacity.",
                            "pace_assessment": "The pace is still cautious.",
                            "target_gap_commentary": "A meaningful gap remains.",
                            "trend_commentary": "The projection is still early."
                        },
                        "cautions": ["Keep projections directional only."],
                        "confidence_note": "Confidence is cautious."
                    },
                }
            },
            "response_meta": {"reason_codes": []},
            "tool_errors": {},
        }
        service_next = apply_specialist_response(service_state)
        self.assertEqual("protect_liquidity", service_next["roadmap_payload"]["current_phase"])
        self.assertIn("Roadmap at a glance:", service_next["response"])
        self.assertIn("Current focus: Protect your cash flow", service_next["response"])
        self.assertNotIn("protect_liquidity", service_next["response"])
        self.assertNotIn("Roadmap snapshot:", service_next["response"])

    def test_specialist_response_prefers_selected_service_over_hidden_planner_output(self) -> None:
        state = {
            "selected_specialist_id": "service",
            "agent_outputs": {
                "planner": {
                    "agent_id": "planner",
                    "status": "ok",
                    "result": {"summary": "Hidden planner summary."},
                    "standardized_contract": {
                        "contract_spec_version": "financial_advisory_contract_v1",
                        "txt_render_spec_version": "planner_text_v1",
                        "report_title": "Planner",
                        "section_order": [],
                        "sections": {},
                        "human_readable": {"summary": "Hidden planner summary."},
                    },
                },
                "service": {
                    "agent_id": "service",
                    "status": "ok",
                    "result": {"summary": "Roadmap summary."},
                    "roadmap_contract": {
                        "schema_version": "service_roadmap_contract_v1",
                        "status": "ready",
                        "current_phase": "stabilize",
                        "phase_sequence": ["stabilize", "accumulate"],
                        "goal": {"goal_type": "home_purchase"},
                        "milestones": [{"title": "Stabilize cashflow", "phase_type": "stabilize", "status": "current"}],
                    },
                    "explanation": {
                        "summary": "Roadmap summary.",
                        "why_fit": "This path fits because the current goal needs a steadier base first.",
                        "current_phase_explanation": "The current focus is to stabilize before accelerating.",
                        "phase_explanations": [],
                        "milestone_explanations": [],
                        "next_action_explanation": {
                            "why_now": "Fix the baseline first.",
                            "what_to_check": "Review recurring expenses.",
                            "what_success_looks_like": "Cashflow is easier to predict.",
                            "what_happens_next": "The roadmap can move into accumulate."
                        },
                        "projection_explanation": {
                            "basis": "Projection uses current monthly capacity.",
                            "pace_assessment": "The pace is still building.",
                            "target_gap_commentary": "A meaningful gap remains.",
                            "trend_commentary": "The projection is still early."
                        },
                        "cautions": ["Keep projections directional only."],
                        "confidence_note": "Confidence is cautious."
                    },
                },
            },
            "response_meta": {"reason_codes": []},
            "tool_errors": {},
        }

        next_state = apply_specialist_response(state)

        self.assertEqual("stabilize", next_state["roadmap_payload"]["current_phase"])
        self.assertIn("Roadmap at a glance:", next_state["response"])
        self.assertNotEqual("Hidden planner summary.", next_state["response"])
        self.assertNotIn("planner_context", next_state)

    def test_planner_runs_in_process_without_finance_mcp(self) -> None:
        envelope = _request_envelope(intent="planning")

        class FakeSupabaseClient:
            configured = True

        def fake_invoke(context, tool_name, **kwargs):
            context.tool_trace.append(
                {
                    "tool_name": tool_name,
                    "status": "ok",
                    "latency_ms": 1,
                    "details": "direct_internal_call",
                }
            )
            if tool_name == "spend_analytics_v1":
                return {"total_spend": 100.0, "net_cashflow": 25.0, "budget_drift": []}
            if tool_name == "cashflow_forecast_v1":
                return {"confidence_band": {"p50_avg": 40.0}}
            if tool_name == "jar_allocation_suggest_v1":
                return {"baseline_monthly_income": 300.0, "allocations": [{"jar_name": "Bills"}]}
            return {}

        with temp_env(FINANCE_MCP_URL="http://unused-finance-mcp", PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                    result = run_planner(envelope)

        self.assertEqual("ok", result["status"])
        self.assertEqual(envelope["correlation"], result["correlation"])
        self.assertIn("Net cashflow", result["summary"])
        self.assertTrue(any(item["tool_name"] == "spend_analytics_v1" for item in result["result"]["tool_trace"]))
        self.assertIn("standardized_contract", result)
        self.assertEqual("financial_advisory_contract_v1", result["standardized_contract"]["contract_spec_version"])
        self.assertEqual(result["result"]["summary"], result["standardized_contract"]["human_readable"]["summary"])
        validate_specialist_output("run_planner_agent_v1.output.json", result)

    def test_stock_local_adapter_does_not_require_external_hosting(self) -> None:
        envelope = _request_envelope(intent="invest")
        envelope["routing"] = {"specialist_id": "stock", "tool_name": "run_stock_agent_v1"}
        envelope["request"]["user_context"] = {
            "risk_profile": {"risk_band": "moderate"},
            "planner_summary": "Budget is stable.",
        }

        with temp_env(STOCK_AGENT_EXTERNAL_ENABLED="false", STOCK_AGENT_EXTERNAL_BASE_URL=None):
            result = run_stock(envelope)

        self.assertEqual("partial", result["status"])
        self.assertEqual(envelope["correlation"], result["correlation"])
        self.assertIn("education-only", result["result"]["summary"].lower())
        validate_specialist_output("run_stock_agent_v1.output.json", result)

    def test_stock_external_timeout_degrades_to_local_partial_response(self) -> None:
        envelope = _request_envelope(intent="invest")
        envelope["routing"] = {"specialist_id": "stock", "tool_name": "run_stock_agent_v1"}

        with temp_env(STOCK_AGENT_EXTERNAL_ENABLED="true", STOCK_AGENT_EXTERNAL_URL="https://example.com/ask"):
            with patch("stock.adapter.requests.post", side_effect=requests.Timeout("simulated timeout")):
                result = run_stock(envelope)

        self.assertEqual("partial", result["status"])
        self.assertIn("education-only", result["result"]["summary"].lower())
        self.assertTrue(any(item["code"] == "stock_external_warning" for item in result["warnings"]))
        validate_specialist_output("run_stock_agent_v1.output.json", result)

    def test_stock_external_answer_is_mapped_into_symbols_and_market_notes(self) -> None:
        envelope = _request_envelope(intent="invest")
        envelope["routing"] = {"specialist_id": "stock", "tool_name": "run_stock_agent_v1"}

        class _FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {
                    "answer": (
                        "## Cap nhat thi truong\n\n"
                        "| Mã CK | Giá |\n"
                        "|-------|-----|\n"
                        "| VCB   | 58.400 |\n"
                        "| TCB   | 30.800 |\n\n"
                        "**Điểm nhấn phiên:**\n"
                        "- Ngan hang giao dich soi dong\n"
                        "- Cong nghe giu nhip tang truong\n"
                    ),
                    "success": True,
                }

        with temp_env(STOCK_AGENT_EXTERNAL_ENABLED="true", STOCK_AGENT_EXTERNAL_URL="https://example.com/ask"):
            with patch("stock.adapter.requests.post", return_value=_FakeResponse()):
                result = run_stock(envelope)

        self.assertEqual("ok", result["status"])
        self.assertEqual("VCB", result["result"]["alternatives"][0]["ticker"])
        self.assertTrue(result["result"]["market_notes"])
        self.assertEqual([], result["result"]["recommendations"])
        self.assertEqual("warn", result["result"]["suitability"]["status"])
        validate_specialist_output("run_stock_agent_v1.output.json", result)

    def test_gateway_transport_metadata_is_stripped_before_specialist_validation(self) -> None:
        descriptor = get_specialist_by_id("planner")
        self.assertIsNotNone(descriptor)

        payload = _request_envelope(intent="planning")
        payload["routing"] = {"specialist_id": "planner", "tool_name": "run_planner_agent_v1"}
        gateway_result = {
            "schema_version": "v1",
            "agent_id": "planner",
            "agent_version": "0.1.0",
            "tool_name": "run_planner_agent_v1",
            "status": "ok",
            "correlation": dict(payload["correlation"]),
            "result": {"summary": "ok"},
            "warnings": [],
            "errors": [],
            "call_id": "spec_123",
            "idempotency_key": "idem_123",
        }

        with patch("strands_orchestrator.specialist._call_gateway_tool", return_value=gateway_result):
            result = call_specialist_tool(
                descriptor,
                payload,
                "Bearer token",
                trace_id="trc_test",
            )

        self.assertNotIn("call_id", result)
        self.assertNotIn("idempotency_key", result)
        validate_specialist_output("run_planner_agent_v1.output.json", result)

    def test_deployed_planner_defaults_to_deterministic_execution_mode(self) -> None:
        with temp_env(
            APP_ENV="staging",
            PLANNER_EXECUTION_MODE=None,
            PLANNER_STUB_MODE="false",
            BEDROCK_MODEL_ID="global.anthropic.claude-sonnet-4-6",
        ):
            import planner_agent.agent as planner_agent

            self.assertEqual("deterministic", planner_agent._planner_execution_mode())

    def test_specialist_gateway_alias_retry_only_applies_to_name_resolution_errors(self) -> None:
        descriptor = get_specialist_by_id("planner")
        self.assertIsNotNone(descriptor)

        payload = _request_envelope(intent="planning")
        payload["routing"] = {"specialist_id": "planner", "tool_name": "run_planner_agent_v1"}

        with patch(
            "strands_orchestrator.specialist._call_gateway_tool",
            side_effect=RuntimeError("MCP invocation failed: Apache transport request failed"),
        ) as gateway_mock:
            with self.assertRaises(RuntimeError):
                call_specialist_tool(
                    descriptor,
                    payload,
                    "Bearer token",
                    trace_id="trc_test",
                )

        self.assertEqual(1, gateway_mock.call_count)


if __name__ == "__main__":
    unittest.main()
