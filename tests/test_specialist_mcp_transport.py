from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from app.main import app  # noqa: E402
from app.mcp import _stub_planner  # noqa: E402


def _extract_sse_json(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"No SSE data payload found in response: {body!r}")


def _extract_json(body: str) -> dict:
    body = body.strip()
    if body.startswith("{"):
        return json.loads(body)
    return _extract_sse_json(body)


def _walk_forbidden_keys(value, forbidden: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in forbidden:
                raise AssertionError(f"Found forbidden schema key {key!r} in {value!r}")
            _walk_forbidden_keys(item, forbidden)
    elif isinstance(value, list):
        for item in value:
            _walk_forbidden_keys(item, forbidden)


class SpecialistMcpTransportTests(unittest.TestCase):
    def _initialize_session(self, client: TestClient) -> tuple[str, dict]:
        initialize = client.post(
            "/mcp",
            headers={"accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
            },
        )
        self.assertEqual(200, initialize.status_code)
        self.assertIn("application/json", initialize.headers.get("content-type", ""))
        session_id = initialize.headers.get("mcp-session-id")
        self.assertTrue(session_id)
        return str(session_id), _extract_json(initialize.text)

    def test_initialize_and_tools_list_use_streamable_http(self) -> None:
        with TestClient(app) as client:
            session_id, init_payload = self._initialize_session(client)
            self.assertEqual("2025-06-18", init_payload["result"]["protocolVersion"])

            tools_list = client.post(
                "/mcp",
                headers={"accept": "application/json, text/event-stream", "mcp-session-id": session_id},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            self.assertEqual(200, tools_list.status_code)
            tools_payload = _extract_json(tools_list.text)
            tool_names = [tool["name"] for tool in tools_payload["result"]["tools"]]
            self.assertEqual(
                ["run_planner_agent_v1", "run_service_agent_v1", "run_stock_agent_v1"],
                tool_names,
            )

    def test_tools_list_schemas_are_gateway_safe(self) -> None:
        with TestClient(app) as client:
            session_id, _ = self._initialize_session(client)
            response = client.post(
                "/mcp",
                headers={"accept": "application/json, text/event-stream", "mcp-session-id": session_id or ""},
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            )
            payload = _extract_json(response.text)
            tools = payload["result"]["tools"]

        for tool in tools:
            schema = tool["inputSchema"]
            _walk_forbidden_keys(schema, {"$id", "$schema", "$ref", "$defs"})

    def test_tools_call_returns_serializable_call_tool_result(self) -> None:
        request_arguments = {
            "schema_version": "v1",
            "actor": {
                "actor_id": "usr_123",
                "user_id": "usr_123",
                "tenant_id": "tenant_a",
                "scopes": ["chat:invoke", "finance:read"],
            },
            "correlation": {
                "session_id": "chat_test",
                "request_id": "req_test",
                "trace_id": "trc_test",
                "parent_request_id": "req_root",
                "request_timestamp": "2026-03-22T00:00:00Z",
            },
            "request": {
                "prompt": "Please analyze my financial situation over the last 7 months.",
                "intent": "summary",
                "policy_flags": {"education_only": True},
                "user_context": {},
                "goals": [],
                "session_summary": "",
            },
            "routing": {
                "specialist_id": "planner",
                "tool_name": "run_planner_agent_v1",
            },
        }

        with TestClient(app) as client, patch("app.mcp._handle_planner", side_effect=lambda arguments, trace_ctx: _stub_planner(arguments)):
            session_id, _ = self._initialize_session(client)
            response = client.post(
                "/mcp",
                headers={"accept": "application/json, text/event-stream", "mcp-session-id": session_id},
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "run_planner_agent_v1", "arguments": request_arguments},
                },
            )

        self.assertEqual(200, response.status_code)
        payload = _extract_json(response.text)
        self.assertNotIn("error", payload)
        result = payload["result"]
        self.assertFalse(result["isError"])
        self.assertEqual("text", result["content"][0]["type"])
        rendered = json.loads(result["content"][0]["text"])
        self.assertEqual("planner", rendered["agent_id"])


if __name__ == "__main__":
    unittest.main()
