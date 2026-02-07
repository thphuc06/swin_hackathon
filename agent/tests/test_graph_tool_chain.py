from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
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
    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.jar_allocation_suggest_tool")
    @patch("graph.risk_profile_non_investment_tool")
    @patch("graph.anomaly_signals")
    @patch("graph.cashflow_forecast_tool")
    @patch("graph.spend_analytics")
    @patch("graph.suitability_guard_tool")
    def test_planning_prompt_calls_summary_forecast_allocation(
        self,
        mock_guard,
        mock_spend,
        mock_forecast,
        mock_anomaly,
        mock_risk,
        mock_alloc,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_guard.return_value = {"allow": True, "decision": "allow", "education_only": False}
        mock_spend.return_value = {"total_spend": 10, "total_income": 20}
        mock_forecast.return_value = {"points": []}
        mock_anomaly.return_value = {"flags": []}
        mock_risk.return_value = {"risk_band": "low"}
        mock_alloc.return_value = {"allocations": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Toi can plan saving for house", "token", "user-1")
        self.assertIn("suitability_guard_v1", result["tool_calls"])
        self.assertIn("spend_analytics_v1", result["tool_calls"])
        self.assertIn("cashflow_forecast_v1", result["tool_calls"])
        self.assertIn("jar_allocation_suggest_v1", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.jar_allocation_suggest_tool")
    @patch("graph.risk_profile_non_investment_tool")
    @patch("graph.anomaly_signals")
    @patch("graph.cashflow_forecast_tool")
    @patch("graph.spend_analytics")
    @patch("graph.suitability_guard_tool")
    def test_risk_prompt_calls_anomaly_and_risk_profile(
        self,
        mock_guard,
        mock_spend,
        mock_forecast,
        mock_anomaly,
        mock_risk,
        mock_alloc,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_guard.return_value = {"allow": True, "decision": "allow", "education_only": False}
        mock_spend.return_value = {"total_spend": 10, "total_income": 20}
        mock_forecast.return_value = {"points": []}
        mock_anomaly.return_value = {"flags": ["abnormal_spend"]}
        mock_risk.return_value = {"risk_band": "moderate"}
        mock_alloc.return_value = {"allocations": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Show my risk and anomaly", "token", "user-1")
        self.assertIn("anomaly_signals_v1", result["tool_calls"])
        self.assertIn("risk_profile_non_investment_v1", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.jar_allocation_suggest_tool")
    @patch("graph.risk_profile_non_investment_tool")
    @patch("graph.anomaly_signals")
    @patch("graph.cashflow_forecast_tool")
    @patch("graph.spend_analytics")
    @patch("graph.suitability_guard_tool")
    def test_invest_prompt_education_only(
        self,
        mock_guard,
        mock_spend,
        mock_forecast,
        mock_anomaly,
        mock_risk,
        mock_alloc,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_guard.return_value = {
            "allow": True,
            "decision": "education_only",
            "education_only": True,
            "required_disclaimer": "Educational guidance only.",
        }
        mock_spend.return_value = {"total_spend": 10, "total_income": 20}
        mock_forecast.return_value = {"points": []}
        mock_anomaly.return_value = {"flags": []}
        mock_risk.return_value = {"risk_band": "moderate"}
        mock_alloc.return_value = {"allocations": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Should I invest in stock now?", "token", "user-1")
        self.assertIn("risk_profile_non_investment_v1", result["tool_calls"])
        self.assertIn("educational financial guidance only", result["response"].lower())


if __name__ == "__main__":
    unittest.main()
