from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


class LocalMockToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_gateway = os.environ.get("AGENTCORE_GATEWAY_ENDPOINT")
        self._prev_backend_api_base = os.environ.get("BACKEND_API_BASE")
        self._prev_use_local_mocks = os.environ.get("USE_LOCAL_MOCKS")

    def tearDown(self) -> None:
        if self._prev_gateway is None:
            os.environ.pop("AGENTCORE_GATEWAY_ENDPOINT", None)
        else:
            os.environ["AGENTCORE_GATEWAY_ENDPOINT"] = self._prev_gateway

        if self._prev_backend_api_base is None:
            os.environ.pop("BACKEND_API_BASE", None)
        else:
            os.environ["BACKEND_API_BASE"] = self._prev_backend_api_base

        if self._prev_use_local_mocks is None:
            os.environ.pop("USE_LOCAL_MOCKS", None)
        else:
            os.environ["USE_LOCAL_MOCKS"] = self._prev_use_local_mocks

        import config
        import tools

        importlib.reload(config)
        importlib.reload(tools)

    def _reload_tools(self, backend_api_base: str, use_local_mocks: bool, gateway: str = ""):
        os.environ["BACKEND_API_BASE"] = backend_api_base
        os.environ["USE_LOCAL_MOCKS"] = "true" if use_local_mocks else "false"
        os.environ["AGENTCORE_GATEWAY_ENDPOINT"] = gateway

        import config
        import tools

        importlib.reload(config)
        return importlib.reload(tools)

    def test_localhost_without_gateway_uses_mock_when_enabled(self) -> None:
        tools = self._reload_tools("http://localhost:8010", True, "")
        result = tools.forecast_cashflow("token", "90d", user_id="user-1")
        self.assertEqual(result.get("trace_id"), "trc_mocked01")

    def test_gateway_call_used_when_mocks_disabled(self) -> None:
        tools = self._reload_tools("http://localhost:8010", False, "https://gateway.example.com/mcp")
        expected = {"trace_id": "trc_real01", "points": []}

        with patch("tools._call_gateway_tool", return_value=expected) as mocked_call:
            result = tools.cashflow_forecast_tool("token", "user-1", "weekly_12")
            self.assertEqual(result, expected)
            mocked_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
