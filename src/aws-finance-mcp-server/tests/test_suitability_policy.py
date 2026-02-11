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

suitability = importlib.import_module("app.finance.suitability")


class SuitabilityPolicyTests(unittest.TestCase):
    @patch("app.finance.suitability.write_decision_event")
    @patch("app.finance.suitability.get_supabase_client")
    def test_anomaly_prompt_is_allowed(self, mock_client, mock_write) -> None:
        mock_client.return_value = object()
        result = suitability.suitability_guard(
            auth_user_id="user-1",
            user_id="user-1",
            intent="invest",
            requested_action="advice",
            prompt="thang nay toi thay co giao dich la, ban kiem tra giup",
            trace_id="trc_test",
        )
        self.assertTrue(result.get("allow"))
        self.assertEqual(result.get("decision"), "allow")
        self.assertEqual(result.get("education_only"), False)
        self.assertTrue(mock_write.called)

    @patch("app.finance.suitability.write_decision_event")
    @patch("app.finance.suitability.get_supabase_client")
    def test_planning_home_goal_prompt_is_allowed(self, mock_client, mock_write) -> None:
        mock_client.return_value = object()
        result = suitability.suitability_guard(
            auth_user_id="user-1",
            user_id="user-1",
            intent="planning",
            requested_action="advice",
            prompt="toi muon mua nha 1.5 ty trong 5 nam, ke hoach tiet kiem kha thi?",
            trace_id="trc_test",
        )
        self.assertTrue(result.get("allow"))
        self.assertEqual(result.get("decision"), "allow")
        self.assertEqual(result.get("education_only"), False)
        self.assertTrue(mock_write.called)

    @patch("app.finance.suitability.write_decision_event")
    @patch("app.finance.suitability.get_supabase_client")
    def test_stock_recommendation_prompt_is_denied(self, mock_client, mock_write) -> None:
        mock_client.return_value = object()
        result = suitability.suitability_guard(
            auth_user_id="user-1",
            user_id="user-1",
            intent="invest",
            requested_action="recommend_buy",
            prompt="toi co nen mua co phieu ngan hang luc nay khong",
            trace_id="trc_test",
        )
        self.assertFalse(result.get("allow"))
        self.assertEqual(result.get("decision"), "deny_recommendation")
        self.assertEqual(result.get("education_only"), True)
        self.assertTrue(mock_write.called)


if __name__ == "__main__":
    unittest.main()
