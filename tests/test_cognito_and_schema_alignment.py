from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))


def _install_jose_stub():
    existing = sys.modules.get("jose")
    if existing is not None and hasattr(existing, "jwt"):
        return existing.jwt
    jose_module = types.ModuleType("jose")
    jose_module.jwt = types.SimpleNamespace(
        get_unverified_header=lambda token: {},
        decode=lambda *args, **kwargs: {},
    )
    sys.modules["jose"] = jose_module
    return jose_module.jwt


def _load_module(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_runtime_auth_module():
    _install_jose_stub()
    for name in ("infra.auth.cognito_provider", "infra.auth", "core.settings", "core"):
        sys.modules.pop(name, None)
    return importlib.import_module("infra.auth.cognito_provider")


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


class CognitoAccessTokenAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jose_jwt = _install_jose_stub()
        with temp_env(
            APP_ENV="local",
            DEV_BYPASS_AUTH="false",
            AUTH_DEV_BYPASS="false",
            AGENTCORE_RUNTIME_ARN=None,
            COGNITO_USER_POOL_ID=None,
            COGNITO_CLIENT_ID=None,
            COGNITO_ALLOWED_CLIENT_IDS=None,
            COGNITO_SERVICE_CLIENT_IDS=None,
        ):
            self.backend_auth = _load_module("test_backend_auth", "backend/app/services/auth.py")
            self.specialist_auth = _load_module("test_specialist_auth", "src/aws-specialist-agent-mcp-server/app/auth.py")

    def test_all_services_accept_access_tokens_from_allowed_clients(self) -> None:
        claims = {
            "sub": "user-123",
            "token_use": "access",
            "client_id": "cli-client",
            "scope": "openid profile",
        }
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="cognito",
            DEV_BYPASS_AUTH="false",
            AUTH_DEV_BYPASS="false",
            AWS_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            COGNITO_ALLOWED_CLIENT_IDS="frontend-client,cli-client",
            COGNITO_SERVICE_CLIENT_IDS="service-client",
            POLICY_ADAPTER="simple",
            POLICY_ALLOWED_TOOLS="spend_analytics_v1",
        ):
            runtime_auth = _load_runtime_auth_module()
            with patch.object(self.backend_auth, "_jwks", return_value={"keys": [{"kid": "kid-1"}]}):
                with patch.object(self.backend_auth.jwt, "get_unverified_header", return_value={"kid": "kid-1"}):
                    with patch.object(self.backend_auth.jwt, "decode", return_value=dict(claims)):
                        backend_claims = self.backend_auth.verify_jwt("Bearer access-token")

            with patch.object(self.specialist_auth, "_jwks", return_value={"keys": [{"kid": "kid-1"}]}):
                with patch.object(self.specialist_auth.jwt, "get_unverified_header", return_value={"kid": "kid-1"}):
                    with patch.object(self.specialist_auth.jwt, "decode", return_value=dict(claims)):
                        specialist_claims = self.specialist_auth.verify_jwt("Bearer access-token")

            with patch.object(runtime_auth, "_jwks", return_value={"keys": [{"kid": "kid-1"}]}):
                with patch.object(self.jose_jwt, "get_unverified_header", return_value={"kid": "kid-1"}):
                    with patch.object(self.jose_jwt, "decode", return_value=dict(claims)):
                        runtime_result = runtime_auth.CognitoAuthProvider().verify("Bearer access-token")

        self.assertEqual("cli-client", backend_claims["client_id"])
        self.assertEqual("access", backend_claims["token_use"])
        self.assertEqual("cli-client", specialist_claims["client_id"])
        self.assertEqual("user", specialist_claims["caller_type"])
        self.assertTrue(runtime_result.authenticated)
        self.assertEqual("user-123", runtime_result.subject)
        self.assertEqual("cli-client", runtime_result.claims["client_id"])
        self.assertEqual("access", runtime_result.claims["token_use"])

    def test_all_services_reject_id_tokens(self) -> None:
        claims = {
            "sub": "user-123",
            "token_use": "id",
            "aud": "frontend-client",
        }
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="cognito",
            DEV_BYPASS_AUTH="false",
            AUTH_DEV_BYPASS="false",
            AWS_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            COGNITO_ALLOWED_CLIENT_IDS="frontend-client",
            POLICY_ADAPTER="simple",
            POLICY_ALLOWED_TOOLS="spend_analytics_v1",
        ):
            runtime_auth = _load_runtime_auth_module()
            with patch.object(self.backend_auth, "_jwks", return_value={"keys": [{"kid": "kid-1"}]}):
                with patch.object(self.backend_auth.jwt, "get_unverified_header", return_value={"kid": "kid-1"}):
                    with patch.object(self.backend_auth.jwt, "decode", return_value=dict(claims)):
                        with self.assertRaises(HTTPException) as backend_exc:
                            self.backend_auth.verify_jwt("Bearer id-token")

            with patch.object(self.specialist_auth, "_jwks", return_value={"keys": [{"kid": "kid-1"}]}):
                with patch.object(self.specialist_auth.jwt, "get_unverified_header", return_value={"kid": "kid-1"}):
                    with patch.object(self.specialist_auth.jwt, "decode", return_value=dict(claims)):
                        with self.assertRaises(HTTPException) as specialist_exc:
                            self.specialist_auth.verify_jwt("Bearer id-token")

            with patch.object(runtime_auth, "_jwks", return_value={"keys": [{"kid": "kid-1"}]}):
                with patch.object(self.jose_jwt, "get_unverified_header", return_value={"kid": "kid-1"}):
                    with patch.object(self.jose_jwt, "decode", return_value=dict(claims)):
                        runtime_result = runtime_auth.CognitoAuthProvider().verify("Bearer id-token")

        self.assertIn("AccessToken", str(backend_exc.exception.detail))
        self.assertIn("AccessToken", str(specialist_exc.exception.detail))
        self.assertFalse(runtime_result.authenticated)
        self.assertEqual("expected_access_token", runtime_result.reason)

    def test_runtime_core_settings_fail_fast_when_staging_uses_jwt_provider(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="jwt",
            AUTH_DEV_BYPASS="false",
            COGNITO_USER_POOL_ID=None,
            COGNITO_CLIENT_ID=None,
            COGNITO_ALLOWED_CLIENT_IDS=None,
            POLICY_ADAPTER="simple",
            POLICY_ALLOWED_TOOLS="spend_analytics_v1",
        ):
            for name in ("core.settings", "core"):
                sys.modules.pop(name, None)
            with self.assertRaises(RuntimeError):
                importlib.import_module("core.settings")

    def test_backend_and_specialist_fail_fast_when_deployed_bypass_is_enabled(self) -> None:
        with temp_env(
            APP_ENV="staging",
            AUTH_PROVIDER="cognito",
            DEV_BYPASS_AUTH="true",
            AWS_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="frontend-client",
            COGNITO_ALLOWED_CLIENT_IDS="frontend-client",
        ):
            with self.assertRaises(RuntimeError):
                _load_module("test_backend_auth_invalid", "backend/app/services/auth.py")
            with self.assertRaises(RuntimeError):
                _load_module("test_specialist_auth_invalid", "src/aws-specialist-agent-mcp-server/app/auth.py")


class GatewaySchemaFlatteningTests(unittest.TestCase):
    TOOL_SCHEMA_NAMES = (
        "run_planner_agent_v1.input.json",
        "run_planner_agent_v1.output.json",
        "run_stock_agent_v1.input.json",
        "run_stock_agent_v1.output.json",
    )
    BLOCKED_KEYS = {"$ref", "$defs", "$anchor", "$dynamicRef", "$dynamicAnchor"}

    def _load_json(self, relative_path: str):
        return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))

    def _contains_blocked_key(self, value) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in self.BLOCKED_KEYS:
                    return True
                if self._contains_blocked_key(item):
                    return True
            return False
        if isinstance(value, list):
            return any(self._contains_blocked_key(item) for item in value)
        return False

    def test_tool_schemas_are_flattened_in_both_directories(self) -> None:
        for name in self.TOOL_SCHEMA_NAMES:
            specialist_schema = self._load_json(f"src/aws-specialist-agent-mcp-server/schemas/{name}")
            agent_schema = self._load_json(f"agent/subagents/schemas/{name}")
            self.assertFalse(self._contains_blocked_key(specialist_schema), msg=name)
            self.assertFalse(self._contains_blocked_key(agent_schema), msg=name)
            self.assertEqual(specialist_schema, agent_schema, msg=name)


if __name__ == "__main__":
    unittest.main()
