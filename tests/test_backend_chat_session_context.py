from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

fake_auth = ModuleType("app.services.auth")
fake_auth.current_user = lambda: {}  # pragma: no cover - test stub
sys.modules.setdefault("app.services.auth", fake_auth)

from app.routes import chat


class BackendChatSessionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        with chat._SESSION_CONTEXT_LOCK:
            chat._SESSION_PLANNER_CONTEXT.clear()

    def test_planner_context_extracts_from_top_level_or_nested_runtime_payload(self) -> None:
        nested_payload = {
            "agent_outputs": {
                "planner": {
                    "result": {"summary": "Planner summary from nested result."},
                    "standardized_contract": {"contract_spec_version": "financial_advisory_contract_v1"},
                }
            }
        }
        extracted_nested = chat._planner_context_from_runtime_payload(nested_payload)
        self.assertEqual("Planner summary from nested result.", extracted_nested["planner_summary"])
        self.assertIn("planner_standardized_contract", extracted_nested)

        top_level_payload = {
            "planner_context": {
                "planner_summary": "Planner summary from top level.",
                "planner_standardized_contract": {"contract_spec_version": "financial_advisory_contract_v1"},
            }
        }
        extracted_top = chat._planner_context_from_runtime_payload(top_level_payload)
        self.assertEqual("Planner summary from top level.", extracted_top["planner_summary"])
        self.assertIn("planner_standardized_contract", extracted_top)

    def test_session_planner_context_round_trips_by_session_id(self) -> None:
        payload = {
            "planner_context": {
                "planner_summary": "Planner summary for session.",
                "planner_standardized_contract": {"contract_spec_version": "financial_advisory_contract_v1"},
            }
        }

        chat._store_planner_context("chat_live_123", payload)
        loaded = chat._load_planner_context("chat_live_123")

        self.assertEqual("Planner summary for session.", loaded["planner_summary"])
        self.assertIn("planner_standardized_contract", loaded)

    def test_service_payload_extracts_from_top_level_or_nested_runtime_payload(self) -> None:
        nested_payload = {
            "agent_outputs": {
                "service": {
                    "agent_id": "service",
                    "ui_explanation": {
                        "summary": "Roadmap summary.",
                        "why_this_roadmap": "It fits the current state.",
                        "why_current_phase": "Cashflow protection comes first.",
                        "what_has_to_change_next": "Leakage needs to be contained.",
                    },
                    "roadmap_contract": {"current_phase": "protect_liquidity"},
                }
            }
        }
        extracted_nested = chat._service_payload_from_runtime_payload(nested_payload)
        self.assertEqual("service", extracted_nested["agent_id"])
        self.assertEqual("protect_liquidity", extracted_nested["roadmap_contract"]["current_phase"])

        top_level_payload = {
            "service_payload": {
                "agent_id": "service",
                "ui_explanation": {
                    "summary": "Roadmap summary.",
                    "why_this_roadmap": "It fits the current state.",
                    "why_current_phase": "Cashflow protection comes first.",
                    "what_has_to_change_next": "Leakage needs to be contained.",
                },
            }
        }
        extracted_top = chat._service_payload_from_runtime_payload(top_level_payload)
        self.assertEqual("service", extracted_top["agent_id"])
        self.assertIn("ui_explanation", extracted_top)

    def test_stock_context_extracts_from_nested_runtime_payload(self) -> None:
        nested_payload = {
            "agent_outputs": {
                "stock": {
                    "agent_id": "stock",
                    "tool_name": "run_stock_agent_v1",
                    "summary": "Vietnam bank stocks look mixed right now.",
                    "result": {
                        "summary": "Vietnam bank stocks look mixed right now.",
                        "suitability": {"status": "warn"},
                        "alternatives": [
                            {"ticker": "VCB", "rationale": "Large-cap bank exposure with better balance-sheet quality."}
                        ],
                    },
                    "warnings": [
                        {"code": "market_caution", "message": "Credit quality and valuation need monitoring."}
                    ],
                }
            }
        }

        extracted = chat._stock_context_from_runtime_payload(nested_payload)

        self.assertEqual("warn", extracted["suitability_status"])
        self.assertEqual("cautious", extracted["market_tone"])
        self.assertIn("Credit quality and valuation need monitoring.", extracted["warning_flags"])
        self.assertEqual("run_stock_agent_v1", extracted["source"])

    def test_session_context_round_trips_planner_and_stock_by_session_id(self) -> None:
        planner_payload = {
            "planner_context": {
                "planner_summary": "Planner summary for session.",
                "planner_standardized_contract": {"contract_spec_version": "financial_advisory_contract_v1"},
            }
        }
        stock_payload = {
            "agent_outputs": {
                "stock": {
                    "agent_id": "stock",
                    "tool_name": "run_stock_agent_v1",
                    "summary": "Stock summary for session.",
                    "result": {"summary": "Stock summary for session.", "suitability": {"status": "warn"}},
                    "warnings": [{"code": "market_caution", "message": "Stay selective."}],
                }
            }
        }

        chat._store_planner_context("chat_live_123", planner_payload)
        chat._store_planner_context("chat_live_123", stock_payload)

        loaded_planner = chat._load_planner_context("chat_live_123")
        loaded_stock = chat._load_stock_context("chat_live_123")

        self.assertEqual("Planner summary for session.", loaded_planner["planner_summary"])
        self.assertEqual("Stock summary for session.", loaded_stock["summary"])
        self.assertEqual("warn", loaded_stock["suitability_status"])


if __name__ == "__main__":
    unittest.main()
