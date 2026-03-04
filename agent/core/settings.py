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


ORCHESTRATOR_V2_ENABLED = env_bool("ORCHESTRATOR_V2_ENABLED", True)
STOCK_AGENT_EXTERNAL_ENABLED = env_bool("STOCK_AGENT_EXTERNAL_ENABLED", True)
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

AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "jwt").strip().lower() or "jwt"
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "").strip()
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "").strip()
COGNITO_REGION = os.getenv("COGNITO_REGION", "").strip()
AUTH_DEV_BYPASS = env_bool("AUTH_DEV_BYPASS", False)

OBSERVABILITY_EXPORTER = os.getenv("OBSERVABILITY_EXPORTER", "structured").strip().lower() or "structured"
CLOUDWATCH_LOG_GROUP = os.getenv("CLOUDWATCH_LOG_GROUP", "/aws/agentcore/runtime").strip()
CLOUDWATCH_LOG_STREAM = os.getenv("CLOUDWATCH_LOG_STREAM", "advisory-runtime").strip()
CLOUDWATCH_REGION = os.getenv("CLOUDWATCH_REGION", "").strip()
CLOUDWATCH_ENABLED = env_bool("CLOUDWATCH_ENABLED", False)
