from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
    @patch("graph.what_if_scenario_tool")
    @patch("graph.goal_feasibility_tool")
    @patch("graph.recurring_cashflow_detect_tool")
    @patch("graph.jar_allocation_suggest_tool")
    @patch("graph.risk_profile_non_investment_tool")
    @patch("graph.anomaly_signals")
    @patch("graph.cashflow_forecast_tool")
    @patch("graph.spend_analytics")
    @patch("graph.suitability_guard_tool")
    def test_planning_prompt_calls_planning_tool_chain(
        self,
        mock_guard,
        mock_spend,
        mock_forecast,
        mock_anomaly,
        mock_risk,
        mock_alloc,
        mock_recurring,
        mock_goal,
        mock_what_if,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_guard.return_value = {"allow": True, "decision": "allow", "education_only": False}
        mock_spend.return_value = {"total_spend": 10, "total_income": 20}
        mock_forecast.return_value = {"points": []}
        mock_anomaly.return_value = {"flags": []}
        mock_risk.return_value = {"risk_band": "low"}
        mock_alloc.return_value = {"allocations": []}
        mock_recurring.return_value = {"recurring_expense": []}
        mock_goal.return_value = {"feasible": True}
        mock_what_if.return_value = {"scenario_comparison": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Toi can plan saving for house", "token", "user-1")
        self.assertIn("suitability_guard_v1", result["tool_calls"])
        self.assertIn("spend_analytics_v1", result["tool_calls"])
        self.assertIn("cashflow_forecast_v1", result["tool_calls"])
        self.assertIn("jar_allocation_suggest_v1", result["tool_calls"])
        self.assertIn("recurring_cashflow_detect_v1", result["tool_calls"])
        self.assertIn("goal_feasibility_v1", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.what_if_scenario_tool")
    @patch("graph.goal_feasibility_tool")
    @patch("graph.recurring_cashflow_detect_tool")
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
        mock_recurring,
        mock_goal,
        mock_what_if,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_guard.return_value = {"allow": True, "decision": "allow", "education_only": False}
        mock_spend.return_value = {"total_spend": 10, "total_income": 20}
        mock_forecast.return_value = {"points": []}
        mock_anomaly.return_value = {"flags": ["abnormal_spend"]}
        mock_risk.return_value = {"risk_band": "moderate"}
        mock_alloc.return_value = {"allocations": []}
        mock_recurring.return_value = {"recurring_expense": []}
        mock_goal.return_value = {"feasible": True}
        mock_what_if.return_value = {"scenario_comparison": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Show my risk and anomaly", "token", "user-1")
        self.assertIn("anomaly_signals_v1", result["tool_calls"])
        self.assertIn("risk_profile_non_investment_v1", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.what_if_scenario_tool")
    @patch("graph.goal_feasibility_tool")
    @patch("graph.recurring_cashflow_detect_tool")
    @patch("graph.jar_allocation_suggest_tool")
    @patch("graph.risk_profile_non_investment_tool")
    @patch("graph.anomaly_signals")
    @patch("graph.cashflow_forecast_tool")
    @patch("graph.spend_analytics")
    @patch("graph.suitability_guard_tool")
    def test_scenario_prompt_calls_what_if_tool(
        self,
        mock_guard,
        mock_spend,
        mock_forecast,
        mock_anomaly,
        mock_risk,
        mock_alloc,
        mock_recurring,
        mock_goal,
        mock_what_if,
        mock_kb,
        mock_audit,
    ) -> None:
        mock_guard.return_value = {"allow": True, "decision": "allow", "education_only": False}
        mock_spend.return_value = {"total_spend": 10, "total_income": 20}
        mock_forecast.return_value = {"points": []}
        mock_anomaly.return_value = {"flags": []}
        mock_risk.return_value = {"risk_band": "low"}
        mock_alloc.return_value = {"allocations": []}
        mock_recurring.return_value = {"recurring_expense": []}
        mock_goal.return_value = {"feasible": True}
        mock_what_if.return_value = {"scenario_comparison": [{"name": "base"}]}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Neu toi giam an ngoai 15 phan tram thi sao?", "token", "user-1")
        self.assertIn("what_if_scenario_v1", result["tool_calls"])

    @patch("graph.audit_write")
    @patch("graph.kb_retrieve")
    @patch("graph.what_if_scenario_tool")
    @patch("graph.goal_feasibility_tool")
    @patch("graph.recurring_cashflow_detect_tool")
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
        mock_recurring,
        mock_goal,
        mock_what_if,
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
        mock_recurring.return_value = {"recurring_expense": []}
        mock_goal.return_value = {"feasible": True}
        mock_what_if.return_value = {"scenario_comparison": []}
        mock_kb.return_value = {"matches": []}
        mock_audit.return_value = {"trace_id": "trc_test01"}

        result = graph.run_agent("Should I invest in stock now?", "token", "user-1")
        self.assertIn("risk_profile_non_investment_v1", result["tool_calls"])
        self.assertIn("educational financial guidance only", result["response"].lower())


if __name__ == "__main__":
    unittest.main()
