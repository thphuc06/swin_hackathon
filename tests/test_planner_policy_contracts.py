from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))

from planner_agent.agent import run_planner
from planner_agent.policy import (
    PLANNER_DEFAULT_SCENARIO_HORIZON_MONTHS,
    build_tool_plan,
    normalize_planner_intent,
    planner_policy_snapshot,
)
from planner_agent.tool_router import PlannerContext
from planner_agent.contracts import ActorInfo, CorrelationInfo, SpecialistRequestEnvelope


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


def _request(intent: str) -> SpecialistRequestEnvelope:
    return SpecialistRequestEnvelope.model_validate(
        {
            "schema_version": "v1",
            "actor": {"actor_id": "usr_123", "user_id": "usr_123", "tenant_id": "tenant_a", "scopes": ["finance:read"]},
            "correlation": {
                "session_id": "usr_123:default",
                "request_id": "req_abc",
                "trace_id": "trc_xyz",
                "parent_request_id": "req_root",
                "request_timestamp": "2026-03-14T12:00:00Z",
            },
            "request": {
                "prompt": "Create a monthly budget plan",
                "intent": intent,
                "policy_flags": {"education_only": True},
                "user_context": {},
                "goals": [],
                "session_summary": "",
            },
            "routing": {"specialist_id": "planner", "tool_name": "run_planner_agent_v1"},
        }
    )


class PlannerPolicyContractTests(unittest.TestCase):
    def test_planner_policy_snapshot_and_unknown_intent_contract(self) -> None:
        self.assertEqual(
            [
                {"intent": "summary", "owner": "platform-planner", "classification": "policy"},
                {"intent": "planning", "owner": "platform-planner", "classification": "policy"},
                {"intent": "risk", "owner": "platform-planner", "classification": "policy"},
                {"intent": "scenario", "owner": "platform-planner", "classification": "policy"},
                {"intent": "invest", "owner": "platform-planner", "classification": "policy"},
                {"intent": "out_of_scope", "owner": "platform-planner", "classification": "policy"},
            ],
            planner_policy_snapshot(),
        )
        self.assertEqual("summary", normalize_planner_intent("custom_intent"))

    def test_scenario_policy_owns_default_horizon(self) -> None:
        request = _request("scenario")
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
        plan = build_tool_plan(request, context)
        self.assertEqual("what_if_scenario_v1", plan[-1][0])
        self.assertEqual(PLANNER_DEFAULT_SCENARIO_HORIZON_MONTHS, plan[-1][1]["horizon_months"])

    def test_run_planner_consumes_policy_layer(self) -> None:
        class FakeSupabaseClient:
            configured = True

        request = _request("planning")
        calls = []

        def fake_invoke(context, tool_name, **kwargs):
            calls.append((tool_name, kwargs))
            return {"total_spend": 100.0, "net_cashflow": 25.0, "budget_drift": []}

        custom_plan = [("spend_analytics_v1", {"range": "77d"})]
        with temp_env(APP_ENV="local", PLANNER_EXECUTION_MODE="deterministic", PLANNER_MODEL_ID="", BEDROCK_MODEL_ID=""):
            with patch("planner_agent.agent.get_supabase_client", return_value=FakeSupabaseClient()):
                with patch("planner_agent.agent.build_tool_plan", return_value=custom_plan):
                    with patch("planner_agent.agent.invoke_finance_tool", side_effect=fake_invoke):
                        result = run_planner(request)

        self.assertEqual("ok", result["status"])
        self.assertEqual([("spend_analytics_v1", {"range": "77d"})], calls)


if __name__ == "__main__":
    unittest.main()
