from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEV_BYPASS_AUTH", "true")

for module_name in list(sys.modules.keys()):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

mcp_route = importlib.import_module("app.mcp")


class McpFinancialToolsTests(unittest.TestCase):
    def test_tools_list_contains_all_financial_tools(self) -> None:
        body = mcp_route.mcp_jsonrpc({"jsonrpc": "2.0", "id": "1", "method": "tools/list"})
        tools = body.get("result", {}).get("tools", [])
        names = {item.get("name") for item in tools}
        for tool_name in {
            "spend_analytics_v1",
            "anomaly_signals_v1",
            "cashflow_forecast_v1",
            "jar_allocation_suggest_v1",
            "risk_profile_non_investment_v1",
            "suitability_guard_v1",
            "recurring_cashflow_detect_v1",
            "goal_feasibility_v1",
            "what_if_scenario_v1",
        }:
            self.assertIn(tool_name, names)

    @patch.object(mcp_route, "spend_analytics")
    def test_tools_call_spend_allows_dynamic_day_window(self, mock_tool) -> None:
        mock_tool.return_value = {"trace_id": "trc_spend", "range": "45d"}
        payload = {
            "jsonrpc": "2.0",
            "id": "1b",
            "method": "tools/call",
            "params": {
                "name": "spend_analytics_v1",
                "arguments": {"user_id": "demo-user", "range": "45d"},
            },
        }
        body = mcp_route.mcp_jsonrpc(payload)
        self.assertIn("result", body)
        self.assertTrue(mock_tool.called)
        self.assertEqual(mock_tool.call_args.kwargs.get("range_value"), "45d")

    @patch.object(mcp_route, "recurring_cashflow_detect")
    def test_tools_call_recurring(self, mock_tool) -> None:
        mock_tool.return_value = {"trace_id": "trc_test", "fixed_cost_ratio": 0.3}
        payload = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {
                "name": "recurring_cashflow_detect_v1",
                "arguments": {"user_id": "demo-user"},
            },
        }
        body = mcp_route.mcp_jsonrpc(payload)
        self.assertIn("result", body)
        content = body["result"].get("content", [])
        self.assertTrue(content)
        self.assertIn("trc_test", content[0].get("text", ""))

    @patch.object(mcp_route, "goal_feasibility")
    def test_tools_call_goal_feasibility(self, mock_tool) -> None:
        mock_tool.return_value = {"trace_id": "trc_goal", "feasible": True}
        payload = {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {
                "name": "goal_feasibility_v1",
                "arguments": {"user_id": "demo-user", "target_amount": 1000000, "horizon_months": 6},
            },
        }
        body = mcp_route.mcp_jsonrpc(payload)
        self.assertIn("result", body)
        content = body["result"].get("content", [])
        self.assertTrue(content)
        self.assertIn("trc_goal", content[0].get("text", ""))

    @patch.object(mcp_route, "what_if_scenario")
    def test_tools_call_what_if(self, mock_tool) -> None:
        mock_tool.return_value = {"trace_id": "trc_scenario", "scenario_comparison": []}
        payload = {
            "jsonrpc": "2.0",
            "id": "4",
            "method": "tools/call",
            "params": {
                "name": "what_if_scenario_v1",
                "arguments": {"user_id": "demo-user"},
            },
        }
        body = mcp_route.mcp_jsonrpc(payload)
        self.assertIn("result", body)
        content = body["result"].get("content", [])
        self.assertTrue(content)
        self.assertIn("trc_scenario", content[0].get("text", ""))

    def test_tools_call_invalid_arguments(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": "5",
            "method": "tools/call",
            "params": {
                "name": "goal_feasibility_v1",
                "arguments": {"user_id": "demo-user", "target_amount": -1},
            },
        }
        body = mcp_route.mcp_jsonrpc(payload)
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
