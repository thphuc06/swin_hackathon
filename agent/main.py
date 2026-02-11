from __future__ import annotations

import logging
import os
from typing import Any, Dict

from bedrock_agentcore import BedrockAgentCoreApp
from dotenv import load_dotenv

from graph import run_agent
from tools import initialize_kb, initialize_tool_registry

load_dotenv()

logger = logging.getLogger(__name__)
app = BedrockAgentCoreApp()
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."

# Initialize local Knowledge Base at startup (replaces OpenSearch/Bedrock KB)
try:
    kb_result = initialize_kb()
    if kb_result.get("status") == "success":
        logger.info(
            "Startup: Local KB initialized with %d files: %s",
            kb_result.get("files", 0),
            ", ".join(kb_result.get("filenames", [])),
        )
    else:
        logger.error("Startup: KB initialization failed: %s", kb_result.get("error", "unknown"))
except Exception as exc:
    logger.error("Startup: KB initialization exception: %s", exc)

# Initialize tool registry at startup (eager loading)
try:
    default_token = os.getenv("DEFAULT_USER_TOKEN", "")
    if default_token:
        registry_result = initialize_tool_registry(default_token)
        logger.info(
            "Startup: Tool registry initialized with %d tools: %s",
            registry_result.get("count", 0),
            ", ".join(registry_result.get("tools", [])),
        )
    else:
        logger.warning("Startup: DEFAULT_USER_TOKEN not set, skipping tool registry initialization")
except Exception as exc:
    logger.warning("Startup: Tool registry initialization failed: %s (will fall back to lazy loading)", exc)


def _authorization_from_context(context: Any | None) -> str:
    if context is None:
        return ""

    request_headers = getattr(context, "request_headers", None)
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if str(key).lower() == "authorization" and isinstance(value, str) and value.strip():
                return value.strip()

    request = getattr(context, "request", None)
    headers = getattr(request, "headers", None) if request is not None else None
    if headers is not None:
        value = headers.get("Authorization") or headers.get("authorization")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _resolve_user_token(payload: Dict[str, Any], context: Any | None) -> str:
    payload_token = payload.get("authorization")
    if isinstance(payload_token, str) and payload_token.strip():
        return payload_token.strip()

    context_token = _authorization_from_context(context)
    if context_token:
        return context_token

    return os.getenv("DEFAULT_USER_TOKEN", "")


@app.entrypoint
def invoke(payload: Dict[str, Any], context: Any | None = None) -> Dict[str, Any]:
    prompt = payload.get("prompt", "")
    user_token = _resolve_user_token(payload, context)
    user_id = payload.get("user_id", "demo-user")
    result = run_agent(prompt=prompt, user_token=user_token, user_id=user_id)
    response_meta = result.get("response_meta", {}) if isinstance(result.get("response_meta"), dict) else {}
    disclaimer = str(response_meta.get("disclaimer_effective") or DEFAULT_DISCLAIMER)
    return {
        "result": result["response"],
        "trace_id": result["trace_id"],
        "citations": result["citations"].get("matches", []),
        "tool_calls": result.get("tool_calls", []),
        "routing_meta": result.get("routing_meta", {}),
        "response_meta": response_meta,
        "disclaimer": disclaimer,
    }


if __name__ == "__main__":
    app.run()
