from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

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


def _load_module(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimePolicyAndConfigContractTests(unittest.TestCase):
    def test_deployed_simple_policy_requires_explicit_allow_list(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="cognito",
            AUTH_DEV_BYPASS="false",
            AWS_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            POLICY_ADAPTER="simple",
            POLICY_ALLOWED_TOOLS=None,
        ):
            for name in ("core.settings", "core"):
                sys.modules.pop(name, None)
            with self.assertRaises(RuntimeError):
                importlib.import_module("core.settings")

    def test_deployed_cedar_policy_forbids_fail_open(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="cognito",
            AUTH_DEV_BYPASS="false",
            AWS_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            POLICY_ADAPTER="cedar",
            CEDAR_POLICY_ENDPOINT="https://cedar.example/authorize",
            CEDAR_POLICY_FAIL_OPEN="true",
        ):
            for name in ("core.settings", "core"):
                sys.modules.pop(name, None)
            with self.assertRaises(RuntimeError):
                importlib.import_module("core.settings")

    def test_deployed_orchestrator_config_requires_explicit_runtime_boundary(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AWS_REGION="us-east-1",
            AGENTCORE_GATEWAY_ENDPOINT=None,
            BACKEND_API_BASE=None,
        ):
            sys.modules.pop("config", None)
            with self.assertRaises(RuntimeError):
                importlib.import_module("config")


class BackendRuntimeBoundaryTests(unittest.TestCase):
    def test_deployed_backend_requires_runtime_arn(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AGENTCORE_RUNTIME_ARN=None,
            AGENTCORE_LOCAL_URL=None,
            AWS_REGION="us-east-1",
            DEV_BYPASS_AUTH="false",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            COGNITO_ALLOWED_CLIENT_IDS="frontend-client",
        ):
            saved = {name: sys.modules.get(name) for name in ("app", "app.services", "app.services.auth")}
            try:
                for name in list(sys.modules):
                    if name == "app" or name.startswith("app."):
                        sys.modules.pop(name, None)
                app_pkg = types.ModuleType("app")
                app_pkg.__path__ = []  # type: ignore[attr-defined]
                services_pkg = types.ModuleType("app.services")
                services_pkg.__path__ = []  # type: ignore[attr-defined]
                auth_module = types.ModuleType("app.services.auth")
                auth_module.current_user = lambda *args, **kwargs: {}  # type: ignore[attr-defined]
                sys.modules["app"] = app_pkg
                sys.modules["app.services"] = services_pkg
                sys.modules["app.services.auth"] = auth_module
                chat = _load_module("test_backend_chat_route", "backend/app/routes/chat.py")
                with self.assertRaises(HTTPException) as exc:
                    chat._validate_runtime_target_config()
            finally:
                for name in list(sys.modules):
                    if name == "app" or name.startswith("app."):
                        sys.modules.pop(name, None)
                for name, module in saved.items():
                    if module is not None:
                        sys.modules[name] = module
        self.assertEqual(500, exc.exception.status_code)


class RuntimeModeBoundaryTests(unittest.TestCase):
    def test_deployed_runtime_cannot_disable_strands(self) -> None:
        with temp_env(APP_ENV="staging", USE_STRANDS_ORCHESTRATOR="false"):
            if "strands_orchestrator.config" in sys.modules:
                module = importlib.reload(sys.modules["strands_orchestrator.config"])
            else:
                module = importlib.import_module("strands_orchestrator.config")
            with self.assertRaises(RuntimeError):
                module.use_strands_orchestrator()

    def test_deployed_runtime_cannot_disable_specialist_delegation(self) -> None:
        with temp_env(APP_ENV="staging", ENABLE_SPECIALIST_DELEGATION="false"):
            if "strands_orchestrator.config" in sys.modules:
                module = importlib.reload(sys.modules["strands_orchestrator.config"])
            else:
                module = importlib.import_module("strands_orchestrator.config")
            with self.assertRaises(RuntimeError):
                module.enable_specialist_delegation()


class PlannerRuntimeBoundaryTests(unittest.TestCase):
    def test_planner_requires_aws_region_in_deployed_mode(self) -> None:
        with temp_env(APP_ENV="staging", AWS_REGION=None):
            planner_agent = _load_module("test_planner_agent_boundary", "src/aws-specialist-agent-mcp-server/planner_agent/agent.py")
            with self.assertRaises(RuntimeError):
                planner_agent._bedrock_region()


if __name__ == "__main__":
    unittest.main()
