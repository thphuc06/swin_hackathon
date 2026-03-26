from __future__ import annotations

import os


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip()


VALID_APP_ENVS = {"local", "demo", "staging", "prod"}
LOCAL_APP_ENVS = {"local", "demo"}
DEPLOYED_APP_ENVS = {"staging", "prod"}


def _resolve_app_env() -> str:
    raw = env_str("APP_ENV", "").lower()
    if raw:
        if raw not in VALID_APP_ENVS:
            raise RuntimeError("APP_ENV must be one of: local, demo, staging, prod.")
        return raw

    # Preserve the source-local harness when the runtime is explicitly using the
    # lightweight local JWT path or local bypass.
    local_auth_provider = env_str("AUTH_PROVIDER", "").lower()
    if local_auth_provider == "jwt" or env_bool("AUTH_DEV_BYPASS", False):
        return "local"

    deploy_markers = (
        env_str("COGNITO_USER_POOL_ID", ""),
        env_str("COGNITO_CLIENT_ID", ""),
        env_str("COGNITO_ALLOWED_CLIENT_IDS", ""),
        env_str("AGENTCORE_GATEWAY_ENDPOINT", ""),
    )
    if any(marker for marker in deploy_markers):
        raise RuntimeError(
            "APP_ENV must be explicitly set to local, demo, staging, or prod when deployed auth/runtime settings are configured."
        )
    return "local"


APP_ENV = _resolve_app_env()
IS_DEPLOYED_ENV = APP_ENV in DEPLOYED_APP_ENVS
ALLOW_LEGACY_LOCAL_AUTH = APP_ENV in LOCAL_APP_ENVS


ORCHESTRATOR_V2_ENABLED = env_bool("ORCHESTRATOR_V2_ENABLED", True)
STOCK_AGENT_EXTERNAL_ENABLED = env_bool("STOCK_AGENT_EXTERNAL_ENABLED", False)
POLICY_ENGINE_V2_ENABLED = env_bool("POLICY_ENGINE_V2_ENABLED", True)

# Adapter switches (Phase 2).
POLICY_ADAPTER = os.getenv("POLICY_ADAPTER", "simple").strip().lower() or "simple"
POLICY_ALLOWED_TOOLS = os.getenv("POLICY_ALLOWED_TOOLS", "").strip()
CEDAR_POLICY_ENDPOINT = os.getenv("CEDAR_POLICY_ENDPOINT", "").strip()
CEDAR_POLICY_AUTH_TOKEN = os.getenv("CEDAR_POLICY_AUTH_TOKEN", "").strip()
CEDAR_POLICY_TIMEOUT_SECONDS = env_float("CEDAR_POLICY_TIMEOUT_SECONDS", 2.0)
CEDAR_POLICY_FAIL_OPEN = env_bool("CEDAR_POLICY_FAIL_OPEN", True)

RETRIEVAL_ADAPTER = os.getenv("RETRIEVAL_ADAPTER", "local").strip().lower() or "local"
OPENSEARCH_ENDPOINT = os.getenv("OPENSEARCH_ENDPOINT", "").strip()
OPENSEARCH_INDEX_NAME = os.getenv("OPENSEARCH_INDEX_NAME", "agent-kb").strip() or "agent-kb"
OPENSEARCH_API_KEY = os.getenv("OPENSEARCH_API_KEY", "").strip()
OPENSEARCH_TIMEOUT_SECONDS = env_float("OPENSEARCH_TIMEOUT_SECONDS", 3.0)
OPENSEARCH_VERIFY_TLS = env_bool("OPENSEARCH_VERIFY_TLS", True)

def _resolve_auth_provider() -> str:
    raw = env_str("AUTH_PROVIDER", "").lower()
    if not raw:
        if IS_DEPLOYED_ENV:
            raise RuntimeError("AUTH_PROVIDER must be explicitly set in staging/prod.")
        return "jwt"
    if raw not in {"jwt", "cognito"}:
        raise RuntimeError("AUTH_PROVIDER must be either 'jwt' or 'cognito'.")
    if raw == "jwt" and not ALLOW_LEGACY_LOCAL_AUTH:
        raise RuntimeError("AUTH_PROVIDER=jwt is allowed only when APP_ENV is local or demo.")
    return raw


AUTH_PROVIDER = _resolve_auth_provider()
COGNITO_USER_POOL_ID = env_str("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = env_str("COGNITO_CLIENT_ID", "")
COGNITO_REGION = env_str("COGNITO_REGION", "")
AUTH_DEV_BYPASS = env_bool("AUTH_DEV_BYPASS", False)
DEFAULT_USER_TOKEN = env_str("DEFAULT_USER_TOKEN", "")


def _validate_auth_contract() -> None:
    if DEFAULT_USER_TOKEN:
        raise RuntimeError(
            "DEFAULT_USER_TOKEN is no longer supported. Provide Authorization per request or use explicit local/demo bypass."
        )

    if AUTH_DEV_BYPASS and not ALLOW_LEGACY_LOCAL_AUTH:
        raise RuntimeError("AUTH_DEV_BYPASS is allowed only when APP_ENV is local or demo.")

    if IS_DEPLOYED_ENV and AUTH_PROVIDER != "cognito":
        raise RuntimeError("Staging/prod runtimes must use AUTH_PROVIDER=cognito.")

    if AUTH_PROVIDER == "cognito":
        missing: list[str] = []
        if not COGNITO_USER_POOL_ID:
            missing.append("COGNITO_USER_POOL_ID")
        if not COGNITO_CLIENT_ID:
            missing.append("COGNITO_CLIENT_ID")
        if missing:
            raise RuntimeError(
                f"Cognito auth is enabled but missing required settings: {', '.join(missing)}."
            )


_validate_auth_contract()


def _validate_policy_contract() -> None:
    if POLICY_ADAPTER not in {"simple", "cedar"}:
        raise RuntimeError("POLICY_ADAPTER must be either 'simple' or 'cedar'.")

    if POLICY_ADAPTER == "simple":
        if IS_DEPLOYED_ENV and not POLICY_ALLOWED_TOOLS:
            raise RuntimeError(
                "POLICY_ALLOWED_TOOLS must be explicitly set when POLICY_ADAPTER=simple in staging/prod."
            )
        return

    if IS_DEPLOYED_ENV and not CEDAR_POLICY_ENDPOINT:
        raise RuntimeError("CEDAR_POLICY_ENDPOINT must be explicitly set when POLICY_ADAPTER=cedar in staging/prod.")

    if IS_DEPLOYED_ENV and CEDAR_POLICY_FAIL_OPEN:
        raise RuntimeError("CEDAR_POLICY_FAIL_OPEN=true is forbidden when POLICY_ADAPTER=cedar in staging/prod.")


_validate_policy_contract()

OBSERVABILITY_EXPORTER = os.getenv("OBSERVABILITY_EXPORTER", "structured").strip().lower() or "structured"
CLOUDWATCH_LOG_GROUP = os.getenv("CLOUDWATCH_LOG_GROUP", "/aws/agentcore/runtime").strip()
CLOUDWATCH_LOG_STREAM = os.getenv("CLOUDWATCH_LOG_STREAM", "advisory-runtime").strip()
CLOUDWATCH_REGION = os.getenv("CLOUDWATCH_REGION", "").strip()
CLOUDWATCH_ENABLED = env_bool("CLOUDWATCH_ENABLED", False)
