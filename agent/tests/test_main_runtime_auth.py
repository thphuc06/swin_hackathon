from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

# Avoid startup registry init network calls during test import.
os.environ["DEFAULT_USER_TOKEN"] = ""

import main  # noqa: E402


class MainRuntimeAuthTests(unittest.TestCase):
    def test_resolve_user_token_prefers_payload_authorization(self) -> None:
        context = types.SimpleNamespace(request_headers={"Authorization": "Bearer context-token"}, request=None)
        token = main._resolve_user_token({"authorization": "Bearer payload-token"}, context)
        self.assertEqual(token, "Bearer payload-token")

    def test_resolve_user_token_reads_context_request_headers(self) -> None:
        context = types.SimpleNamespace(request_headers={"authorization": "Bearer context-token"}, request=None)
        token = main._resolve_user_token({}, context)
        self.assertEqual(token, "Bearer context-token")

    def test_resolve_user_token_reads_context_request_headers_fallback(self) -> None:
        request = types.SimpleNamespace(headers={"Authorization": "Bearer request-token"})
        context = types.SimpleNamespace(request_headers=None, request=request)
        token = main._resolve_user_token({}, context)
        self.assertEqual(token, "Bearer request-token")

    def test_resolve_user_token_falls_back_to_default_token(self) -> None:
        context = types.SimpleNamespace(request_headers=None, request=None)
        with patch.dict(os.environ, {"DEFAULT_USER_TOKEN": "fallback-token"}, clear=False):
            token = main._resolve_user_token({}, context)
        self.assertEqual(token, "fallback-token")

    @patch("main.run_agent")
    def test_invoke_uses_resolved_context_token(self, mock_run_agent) -> None:
        mock_run_agent.return_value = {
            "response": "ok",
            "trace_id": "trc_test",
            "citations": {"matches": []},
            "tool_calls": [],
            "routing_meta": {},
            "response_meta": {},
        }
        payload = {"prompt": "hello", "user_id": "u-1"}
        context = types.SimpleNamespace(request_headers={"Authorization": "Bearer context-token"}, request=None)

        out = main.invoke(payload, context)

        self.assertEqual(out["result"], "ok")
        self.assertEqual(mock_run_agent.call_count, 1)
        self.assertEqual(mock_run_agent.call_args.kwargs.get("user_token"), "Bearer context-token")


if __name__ == "__main__":
    unittest.main()
