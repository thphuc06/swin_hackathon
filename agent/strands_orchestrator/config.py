from __future__ import annotations

import os

VALID_APP_ENVS = {"local", "demo", "staging", "prod"}
DEPLOYED_APP_ENVS = {"staging", "prod"}


def _app_env() -> str:
    raw = str(os.getenv("APP_ENV") or "").strip().lower()
    if not raw:
        return "local"
    if raw not in VALID_APP_ENVS:
        raise RuntimeError("APP_ENV must be one of: local, demo, staging, prod.")
    return raw


def use_strands_orchestrator() -> bool:
    # Deprecated opt-out shim: the Strands orchestrator is the default runtime path.
    raw = os.getenv("USE_STRANDS_ORCHESTRATOR", "true")
    enabled = raw.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled and _app_env() in DEPLOYED_APP_ENVS:
        raise RuntimeError("USE_STRANDS_ORCHESTRATOR=false is not supported in staging/prod.")
    return enabled


def graph_timeout_seconds() -> float:
    raw = os.getenv("STRANDS_GRAPH_TIMEOUT_SECONDS")
    if raw is None:
        return 60.0
    try:
        return max(1.0, float(raw.strip()))
    except ValueError:
        return 60.0


def enable_specialist_delegation() -> bool:
    # Specialist-first delegation is part of the default architecture and should stay enabled.
    raw = os.getenv("ENABLE_SPECIALIST_DELEGATION", "true")
    enabled = raw.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled and _app_env() in DEPLOYED_APP_ENVS:
        raise RuntimeError("ENABLE_SPECIALIST_DELEGATION=false is not supported in staging/prod.")
    return enabled


def enable_service_hidden_context_calls() -> bool:
    raw = os.getenv("SERVICE_HIDDEN_CONTEXT_CALLS", "true")
    enabled = raw.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled and _app_env() in DEPLOYED_APP_ENVS:
        raise RuntimeError("SERVICE_HIDDEN_CONTEXT_CALLS=false is not supported in staging/prod.")
    return enabled


def enable_service_hidden_stock_calls() -> bool:
    raw = os.getenv("SERVICE_HIDDEN_STOCK_CALLS", "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}
