from __future__ import annotations

import importlib
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"))


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


class RuntimeAuthContractTests(unittest.TestCase):
    def test_deployed_runtime_forbids_default_user_token(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="cognito",
            AUTH_DEV_BYPASS="false",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            POLICY_ADAPTER="simple",
            POLICY_ALLOWED_TOOLS="spend_analytics_v1",
            DEFAULT_USER_TOKEN="Bearer ambient-token",
        ):
            for name in ("core.settings", "core"):
                sys.modules.pop(name, None)
            with self.assertRaises(RuntimeError):
                importlib.import_module("core.settings")


class SpecialistFinanceScopeContractTests(unittest.TestCase):
    def test_demo_principal_is_not_special_cased_anymore(self) -> None:
        from planner_agent.finance.common import ensure_user_scope, reset_auth_context, set_auth_context

        token = set_auth_context({})
        try:
            with self.assertRaises(PermissionError):
                ensure_user_scope("demo-user", "seeded-user-id")
        finally:
            reset_auth_context(token)

    def test_service_principal_can_cross_user_scope(self) -> None:
        from planner_agent.finance.common import ensure_user_scope, reset_auth_context, set_auth_context

        token = set_auth_context({"caller_type": "service"})
        try:
            ensure_user_scope("service-principal", "target-user")
        finally:
            reset_auth_context(token)


if __name__ == "__main__":
    unittest.main()
