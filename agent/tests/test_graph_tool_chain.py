from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

try:
    import graph
except Exception:  # pragma: no cover
    graph = None


@unittest.skipIf(graph is None, "graph module dependencies not available")
class GraphToolChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = {
            "range": "30d",
            "total_spend": 20_000_000,
            "total_income": 45_000_000,
            "largest_txn": {"merchant": "Techcombank", "amount": 5_500_000},
        }
        self.forecast = {
            "monthly_forecast": [
                {"month": "2026-01", "income_estimate": 45_000_000, "spend_estimate": 30_000_000, "p10": 10_000_000, "p50": 15_000_000, "p90": 20_000_000},
            ],
            "trace_id": "trc_test01",
        }

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.forecast_runway")
    @patch("graph.decision_what_if")
    @patch("graph.decision_house_affordability")
    @patch("graph.decision_savings_goal")
    @patch("graph.decision_investment_capacity")
    @patch("graph.forecast_cashflow")
    @patch("graph.sql_read_views")
    def test_house_prompt_calls_house_forecast_and_what_if(
        self,
        mock_summary,
        mock_forecast,
        mock_invest,
        mock_saving,
        mock_house,
        mock_what_if,
        mock_runway,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_summary.return_value = self.summary
        mock_forecast.return_value = self.forecast
        mock_invest.return_value = {"trace_id": "trc_test01"}
        mock_saving.return_value = {"trace_id": "trc_test01"}
        mock_house.return_value = {"trace_id": "trc_test01", "metrics": {}, "grade": "B", "reasons": [], "guardrails": []}
        mock_what_if.return_value = {"trace_id": "trc_test01", "scenario_comparison": []}
        mock_runway.return_value = {"trace_id": "trc_test01", "runway_months": 10, "risk_flags": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Tôi muốn mua nhà 3 tỷ, có 900 triệu", "token", "user-1")
        self.assertIn("forecast_cashflow_core", result["tool_calls"])
        self.assertIn("evaluate_house_affordability", result["tool_calls"])
        self.assertIn("simulate_what_if", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.forecast_runway")
    @patch("graph.decision_what_if")
    @patch("graph.decision_house_affordability")
    @patch("graph.decision_savings_goal")
    @patch("graph.decision_investment_capacity")
    @patch("graph.forecast_cashflow")
    @patch("graph.sql_read_views")
    def test_saving_prompt_calls_savings_goal(
        self,
        mock_summary,
        mock_forecast,
        mock_invest,
        mock_saving,
        mock_house,
        mock_what_if,
        mock_runway,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_summary.return_value = self.summary
        mock_forecast.return_value = self.forecast
        mock_invest.return_value = {"trace_id": "trc_test01"}
        mock_saving.return_value = {"trace_id": "trc_test01", "metrics": {}, "grade": "A", "reasons": [], "guardrails": []}
        mock_house.return_value = {"trace_id": "trc_test01"}
        mock_what_if.return_value = {"trace_id": "trc_test01"}
        mock_runway.return_value = {"trace_id": "trc_test01", "runway_months": 10, "risk_flags": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent(
            "Mỗi tháng tôi tiết kiệm được bao nhiêu để đạt 500 triệu trong 24 tháng?",
            "token",
            "user-1",
        )
        self.assertIn("evaluate_savings_goal", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.forecast_runway")
    @patch("graph.decision_what_if")
    @patch("graph.decision_house_affordability")
    @patch("graph.decision_savings_goal")
    @patch("graph.decision_investment_capacity")
    @patch("graph.forecast_cashflow")
    @patch("graph.sql_read_views")
    def test_invest_prompt_calls_investment_capacity_and_is_education_only(
        self,
        mock_summary,
        mock_forecast,
        mock_invest,
        mock_saving,
        mock_house,
        mock_what_if,
        mock_runway,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_summary.return_value = self.summary
        mock_forecast.return_value = self.forecast
        mock_invest.return_value = {
            "trace_id": "trc_test01",
            "metrics": {},
            "grade": "B",
            "reasons": [],
            "guardrails": ["education_only=true"],
            "education_only": True,
        }
        mock_saving.return_value = {"trace_id": "trc_test01"}
        mock_house.return_value = {"trace_id": "trc_test01"}
        mock_what_if.return_value = {"trace_id": "trc_test01"}
        mock_runway.return_value = {"trace_id": "trc_test01", "runway_months": 10, "risk_flags": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Tôi có nên đầu tư thêm không?", "token", "user-1")
        self.assertIn("evaluate_investment_capacity", result["tool_calls"])
        self.assertIn("cannot provide investment advice", result["response"])


if __name__ == "__main__":
    unittest.main()
