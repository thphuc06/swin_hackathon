from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


class LocalMockToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_backend_api_base = os.environ.get("BACKEND_API_BASE")
        self._prev_use_local_mocks = os.environ.get("USE_LOCAL_MOCKS")

    def tearDown(self) -> None:
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

    def _reload_tools(self, backend_api_base: str, use_local_mocks: bool):
        os.environ["BACKEND_API_BASE"] = backend_api_base
        os.environ["USE_LOCAL_MOCKS"] = "true" if use_local_mocks else "false"

        import config
        import tools

        importlib.reload(config)
        return importlib.reload(tools)

    def test_localhost_uses_mock_when_enabled(self) -> None:
        tools = self._reload_tools("http://localhost:8010", True)

        with patch("tools._request_json") as mocked_request:
            result = tools.forecast_cashflow("token", "90d")
            self.assertEqual(result.get("trace_id"), "trc_mocked01")
            mocked_request.assert_not_called()

    def test_localhost_calls_backend_when_disabled(self) -> None:
        tools = self._reload_tools("http://localhost:8010", False)
        expected = {"trace_id": "trc_real01", "forecast_points": []}

        with patch("tools._request_json", return_value=expected) as mocked_request:
            result = tools.forecast_cashflow("token", "90d")
            self.assertEqual(result, expected)
            mocked_request.assert_called_once()

    def test_backend_error_raises_when_local_mocks_disabled(self) -> None:
        tools = self._reload_tools("http://localhost:8010", False)
        with patch("tools._request_json", side_effect=requests.RequestException("boom")):
            with self.assertRaises(RuntimeError):
                tools.forecast_cashflow("token", "90d")


if __name__ == "__main__":
    unittest.main()
