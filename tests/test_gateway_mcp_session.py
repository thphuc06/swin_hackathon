from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

import tools


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data: dict | None = None, headers: dict | None = None, text: str | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}
        self.text = text if text is not None else ("" if json_data is None else __import__("json").dumps(self._json_data))

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            error = requests.exceptions.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error


class GatewayMcpSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        tools._reset_gateway_session()

    def tearDown(self) -> None:
        tools._reset_gateway_session()

    def test_gateway_jsonrpc_initializes_mcp_session_before_tools_list(self) -> None:
        responses = [
            _FakeResponse(
                json_data={
                    "jsonrpc": "2.0",
                    "id": "init-1",
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "gateway", "version": "1"},
                    },
                },
                headers={"mcp-session-id": "sess_123"},
            ),
            _FakeResponse(status_code=202, json_data=None, text=""),
            _FakeResponse(json_data={"jsonrpc": "2.0", "id": "tools-1", "result": {"tools": [{"name": "run_planner_agent_v1"}]}}),
        ]

        with patch.object(tools, "AGENTCORE_GATEWAY_ENDPOINT", "https://example.com/mcp"), patch(
            "tools.requests.post", side_effect=responses
        ) as post_mock:
            result = tools._gateway_jsonrpc(
                {"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"},
                "Bearer token_abc",
                call_id="call_tools",
            )

        self.assertEqual({"tools": [{"name": "run_planner_agent_v1"}]}, result["result"])
        self.assertEqual(3, post_mock.call_count)

        first_headers = post_mock.call_args_list[0].kwargs["headers"]
        second_headers = post_mock.call_args_list[1].kwargs["headers"]
        third_headers = post_mock.call_args_list[2].kwargs["headers"]

        self.assertEqual("initialize", post_mock.call_args_list[0].kwargs["json"]["method"])
        self.assertEqual("notifications/initialized", post_mock.call_args_list[1].kwargs["json"]["method"])
        self.assertEqual("tools/list", post_mock.call_args_list[2].kwargs["json"]["method"])
        self.assertNotIn("mcp-session-id", first_headers)
        self.assertEqual("sess_123", second_headers["mcp-session-id"])
        self.assertEqual("sess_123", third_headers["mcp-session-id"])
        self.assertEqual("2025-06-18", third_headers["mcp-protocol-version"])

    def test_gateway_jsonrpc_reuses_existing_mcp_session(self) -> None:
        init_responses = [
            _FakeResponse(
                json_data={"jsonrpc": "2.0", "id": "init-1", "result": {"protocolVersion": "2025-06-18"}},
                headers={"mcp-session-id": "sess_reuse"},
            ),
            _FakeResponse(status_code=202, json_data=None, text=""),
            _FakeResponse(json_data={"jsonrpc": "2.0", "id": "tools-1", "result": {"tools": []}}),
            _FakeResponse(json_data={"jsonrpc": "2.0", "id": "call-2", "result": {"content": []}}),
        ]

        with patch.object(tools, "AGENTCORE_GATEWAY_ENDPOINT", "https://example.com/mcp"), patch(
            "tools.requests.post", side_effect=init_responses
        ) as post_mock:
            tools._gateway_jsonrpc({"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"}, "Bearer token_abc")
            tools._gateway_jsonrpc(
                {"jsonrpc": "2.0", "id": "call-2", "method": "tools/call", "params": {"name": "x", "arguments": {}}},
                "Bearer token_abc",
            )

        self.assertEqual(4, post_mock.call_count)
        second_call_headers = post_mock.call_args_list[3].kwargs["headers"]
        self.assertEqual("sess_reuse", second_call_headers["mcp-session-id"])
        self.assertEqual("2025-06-18", second_call_headers["mcp-protocol-version"])

    def test_gateway_jsonrpc_falls_back_to_sessionless_gateway_mode(self) -> None:
        responses = [
            _FakeResponse(
                json_data={"jsonrpc": "2.0", "id": "init-1", "result": {"protocolVersion": "2025-03-26"}},
                headers={},
            ),
            _FakeResponse(json_data={"jsonrpc": "2.0", "id": "tools-1", "result": {"tools": []}}),
            _FakeResponse(json_data={"jsonrpc": "2.0", "id": "call-2", "result": {"content": []}}),
        ]

        with patch.object(tools, "AGENTCORE_GATEWAY_ENDPOINT", "https://example.com/mcp"), patch(
            "tools.requests.post", side_effect=responses
        ) as post_mock:
            tools._gateway_jsonrpc({"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"}, "Bearer token_abc")
            tools._gateway_jsonrpc(
                {"jsonrpc": "2.0", "id": "call-2", "method": "tools/call", "params": {"name": "x", "arguments": {}}},
                "Bearer token_abc",
            )

        self.assertEqual(3, post_mock.call_count)
        tool_headers = post_mock.call_args_list[1].kwargs["headers"]
        second_call_headers = post_mock.call_args_list[2].kwargs["headers"]
        self.assertNotIn("mcp-session-id", tool_headers)
        self.assertNotIn("mcp-session-id", second_call_headers)
        self.assertEqual("2025-03-26", second_call_headers["mcp-protocol-version"])


if __name__ == "__main__":
    unittest.main()
