from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from planner_agent.contracts import ActorInfo, CorrelationInfo
from planner_agent.tool_router import PlannerContext, invoke_finance_tool
from stock.adapter import run_stock
from strands_orchestrator.config import enable_specialist_delegation, use_strands_orchestrator


@contextmanager
def temp_env(**updates):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _request_envelope() -> dict:
    return {
        "schema_version": "v1",
        "actor": {
            "actor_id": "usr_123",
            "user_id": "usr_123",
            "tenant_id": "tenant_a",
            "scopes": ["chat:invoke", "finance:read"],
        },
        "correlation": {
            "session_id": "usr_123:default",
            "request_id": "req_abc",
            "trace_id": "trc_xyz",
            "parent_request_id": "req_root",
            "request_timestamp": "2026-03-14T12:00:00Z",
        },
        "request": {
            "prompt": "Create a monthly budget plan",
            "intent": "planning",
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


def _install_jose_stub() -> None:
    if "jose" in sys.modules:
        return
    jose_module = types.ModuleType("jose")
    jose_module.jwt = types.SimpleNamespace(
        get_unverified_header=lambda token: {},
        decode=lambda *args, **kwargs: {},
    )
    sys.modules["jose"] = jose_module


def _import_specialist_mcp_module():
    _install_jose_stub()
    if "app.mcp" in sys.modules:
        return importlib.reload(sys.modules["app.mcp"])
    return importlib.import_module("app.mcp")


class DefaultPathHardeningTests(unittest.TestCase):
    def test_default_config_favors_strands_and_specialist_delegation(self) -> None:
        with temp_env(USE_STRANDS_ORCHESTRATOR=None, ENABLE_SPECIALIST_DELEGATION=None):
            self.assertTrue(use_strands_orchestrator())
            self.assertTrue(enable_specialist_delegation())

    def test_planner_external_path_is_opt_in_only(self) -> None:
        mcp = _import_specialist_mcp_module()
        envelope = _request_envelope()

        with temp_env(SPECIALIST_MCP_STUB_MODE=None, PLANNER_AGENT_EXTERNAL_ENABLED=None):
            with patch.object(mcp, "run_planner", return_value={"status": "ok"}) as planner_mock:
                with patch.object(mcp, "_call_external_planner", return_value={"status": "ok"}) as external_mock:
                    result = mcp._handle_planner(envelope, trace_ctx={})

        self.assertEqual({"status": "ok"}, result)
        planner_mock.assert_called_once_with(envelope)
        external_mock.assert_not_called()

    def test_planner_external_path_requires_explicit_opt_in(self) -> None:
        mcp = _import_specialist_mcp_module()
        envelope = _request_envelope()

        with temp_env(SPECIALIST_MCP_STUB_MODE="false", PLANNER_AGENT_EXTERNAL_ENABLED="true"):
            with patch.object(mcp, "run_planner", return_value={"status": "ok"}) as planner_mock:
                with patch.object(mcp, "_call_external_planner", return_value={"status": "external"}) as external_mock:
                    result = mcp._handle_planner(envelope, trace_ctx={"trace_id": "trc_xyz"})

        self.assertEqual({"status": "external"}, result)
        external_mock.assert_called_once()
        planner_mock.assert_not_called()

    def test_conflicting_deprecated_planner_shims_fail_clearly(self) -> None:
        mcp = _import_specialist_mcp_module()
        envelope = _request_envelope()

        with temp_env(SPECIALIST_MCP_STUB_MODE="true", PLANNER_AGENT_EXTERNAL_ENABLED="true"):
            with self.assertRaises(RuntimeError):
                mcp._handle_planner(envelope, trace_ctx={})

    def test_finance_dispatch_uses_direct_imported_python_functions(self) -> None:
        context = PlannerContext(
            actor=ActorInfo(actor_id="usr_123", user_id="usr_123", tenant_id="tenant_a", scopes=["finance:read"]),
            correlation=CorrelationInfo(
                session_id="usr_123:default",
                request_id="req_abc",
                trace_id="trc_xyz",
                parent_request_id="req_root",
                request_timestamp="2026-03-14T12:00:00Z",
            ),
            trace_context={"trace_id": "trc_xyz"},
            supabase_client=object(),
        )

        with patch("planner_agent.tool_router.spend_analytics", return_value={"ok": True}) as spend_mock:
            result = invoke_finance_tool(context, "spend_analytics_v1", range="30d")

        self.assertEqual({"ok": True}, result)
        spend_mock.assert_called_once()
        self.assertIs(spend_mock.call_args.kwargs["client"], context.supabase_client)
        self.assertEqual("usr_123", spend_mock.call_args.kwargs["auth_user_id"])

    def test_external_stock_mode_requires_url_and_default_mode_does_not(self) -> None:
        envelope = _request_envelope()
        envelope["routing"] = {"specialist_id": "stock", "tool_name": "run_stock_agent_v1"}
        envelope["request"]["user_context"] = {"risk_profile": {"risk_band": "moderate"}}

        with temp_env(STOCK_AGENT_EXTERNAL_ENABLED="true", STOCK_AGENT_EXTERNAL_BASE_URL=None):
            with self.assertRaises(RuntimeError):
                run_stock(envelope)


if __name__ == "__main__":
    unittest.main()
