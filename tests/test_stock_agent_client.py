from __future__ import annotations

import sys
import unittest
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from agents.stock_agent_client import StockAgentClient, StockAgentClientConfig
from core.models import StockAdvisoryRequest


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> dict:
        return dict(self._payload)


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    def post(self, endpoint, *, json, headers, timeout):
        self.calls.append(
            {
                "endpoint": endpoint,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self._response


class _TimeoutSession:
    def post(self, endpoint, *, json, headers, timeout):
        raise requests.Timeout("simulated timeout")


class StockAgentClientTests(unittest.TestCase):
    def test_advisory_supports_session_metadata_and_ask_endpoint(self) -> None:
        client = StockAgentClient(
            StockAgentClientConfig(
                enabled=True,
                exact_url="https://example.com/ask",
                base_url="",
                endpoint_path="/v1/stock/advisory",
                auth_token="",
                model_provider="bedrock",
                model="bedrock:test-model",
                connect_timeout_seconds=2.0,
                read_timeout_seconds=8.0,
                max_retries=0,
                backoff_factor=0.0,
                breaker_failure_threshold=3,
                breaker_reset_seconds=60,
            )
        )
        fake_session = _FakeSession(
            _FakeResponse(
                status_code=200,
                payload={
                    "answer": "Vietnam banking stocks look mixed.",
                    "citations": ["market-playbook.md"],
                    "warnings": ["Education only."],
                },
            )
        )
        client._session = fake_session

        response = client.advisory(
            StockAdvisoryRequest(user_id="usr_123", query="What about Vietnam bank stocks?"),
            trace_id="trc_stock",
            request_id="req_stock",
            idempotency_key="idem_stock",
            session_id="sess_stock",
            request_timestamp="2026-03-26T10:00:00Z",
            agent_name="orchestrator",
            schema_version="v1",
        )

        self.assertEqual("Vietnam banking stocks look mixed.", response.summary)
        self.assertEqual(["market-playbook.md"], response.citations)
        self.assertEqual(["Education only."], response.warnings)
        self.assertEqual("warn", response.suitability_check.status)
        self.assertEqual(["education_only"], response.suitability_check.reasons)
        self.assertEqual("https://example.com/ask", fake_session.calls[0]["endpoint"])
        self.assertEqual(
            {
                "question": "What about Vietnam bank stocks?",
                "modelProvider": "bedrock",
                "model": "bedrock:test-model",
            },
            fake_session.calls[0]["json"],
        )
        self.assertEqual((2.0, 120.0), fake_session.calls[0]["timeout"])
        self.assertEqual("sess_stock", fake_session.calls[0]["headers"]["X-Session-Id"])
        self.assertEqual("2026-03-26T10:00:00Z", fake_session.calls[0]["headers"]["X-Request-Timestamp"])
        self.assertEqual("orchestrator", fake_session.calls[0]["headers"]["X-Agent-Name"])
        self.assertEqual("v1", fake_session.calls[0]["headers"]["X-Schema-Version"])

    def test_advisory_parses_symbols_and_market_notes_from_ask_answer(self) -> None:
        client = StockAgentClient(
            StockAgentClientConfig(
                enabled=True,
                exact_url="https://example.com/ask",
                base_url="",
                endpoint_path="/v1/stock/advisory",
                auth_token="",
                model_provider="bedrock",
                model="bedrock:test-model",
                connect_timeout_seconds=2.0,
                read_timeout_seconds=8.0,
                max_retries=0,
                backoff_factor=0.0,
                breaker_failure_threshold=3,
                breaker_reset_seconds=60,
            )
        )
        fake_session = _FakeSession(
            _FakeResponse(
                status_code=200,
                payload={
                    "answer": (
                        "## Cap nhat thi truong\n\n"
                        "| Mã CK | Giá |\n"
                        "|-------|-----|\n"
                        "| VCB   | 58.400 |\n"
                        "| TCB   | 30.800 |\n\n"
                        "**Điểm nhấn phiên:**\n"
                        "- Ngan hang giao dich soi dong\n"
                        "- Cong nghe giu nhip tang truong\n"
                    ),
                    "success": True,
                },
            )
        )
        client._session = fake_session

        response = client.advisory(
            StockAdvisoryRequest(user_id="usr_123", query="What is happening in Vietnam stocks today?"),
            trace_id="trc_stock",
            request_id="req_stock",
            idempotency_key="idem_stock",
        )

        self.assertIn("VCB", response.market_snapshot["highlighted_symbols"])
        self.assertIn("TCB", response.market_snapshot["highlighted_symbols"])
        self.assertTrue(response.market_snapshot["market_notes"])

    def test_advisory_times_out_to_local_education_only_fallback(self) -> None:
        client = StockAgentClient(
            StockAgentClientConfig(
                enabled=True,
                exact_url="https://example.com/ask",
                base_url="",
                endpoint_path="/v1/stock/advisory",
                auth_token="",
                model_provider="bedrock",
                model="bedrock:test-model",
                connect_timeout_seconds=2.0,
                read_timeout_seconds=8.0,
                max_retries=0,
                backoff_factor=0.0,
                breaker_failure_threshold=3,
                breaker_reset_seconds=60,
                fallback_to_local_on_error=True,
            )
        )
        client._session = _TimeoutSession()

        response = client.advisory(
            StockAdvisoryRequest(user_id="usr_123", query="Any bank stocks to watch?"),
            trace_id="trc_stock",
            request_id="req_stock",
            idempotency_key="idem_stock",
        )

        self.assertIn("education-only", response.summary.lower())
        self.assertTrue(any("timed out" in warning.lower() for warning in response.warnings))
        self.assertEqual("warn", response.suitability_check.status)
        self.assertEqual(
            ["stock_local_fallback"],
            response.market_snapshot["fallback_reason_codes"],
        )


if __name__ == "__main__":
    unittest.main()
