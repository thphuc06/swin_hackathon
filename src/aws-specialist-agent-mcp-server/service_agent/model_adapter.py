from __future__ import annotations

import os
from typing import Any, Dict, Tuple

import boto3
from botocore.config import Config

from service_agent.candidate_schema import extract_json_object
from service_agent.constants import MODEL_ID_FALLBACK, MODEL_REGION_FALLBACK

_BEDROCK_CLIENT = None


def _timeout_seconds(env_name: str, default: int) -> int:
    raw = str(os.getenv(env_name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def resolve_model_id(*env_names: str) -> str:
    for name in env_names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return MODEL_ID_FALLBACK


def _bedrock_region() -> str:
    return str(os.getenv("AWS_REGION") or MODEL_REGION_FALLBACK).strip() or MODEL_REGION_FALLBACK


def _client():
    global _BEDROCK_CLIENT
    if _BEDROCK_CLIENT is None:
        _BEDROCK_CLIENT = boto3.client(
            "bedrock-runtime",
            region_name=_bedrock_region(),
            config=Config(
                connect_timeout=_timeout_seconds("BEDROCK_CONNECT_TIMEOUT_SECONDS", 5),
                read_timeout=_timeout_seconds("BEDROCK_READ_TIMEOUT_SECONDS", 60),
                retries={"max_attempts": 1},
            ),
        )
    return _BEDROCK_CLIENT


def _extract_text(payload: Dict[str, Any]) -> str:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    message = output.get("message") if isinstance(output.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def _extract_tool_input(payload: Dict[str, Any], tool_name: str | None = None) -> Dict[str, Any] | None:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    message = output.get("message") if isinstance(output.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []
    for item in content:
        if not isinstance(item, dict):
            continue
        tool_use = item.get("toolUse") if isinstance(item.get("toolUse"), dict) else {}
        if not tool_use:
            continue
        candidate_name = str(tool_use.get("name") or "").strip()
        if tool_name and candidate_name != tool_name:
            continue
        tool_input = tool_use.get("input")
        if isinstance(tool_input, dict):
            return tool_input
    return None


def invoke_json_prompt(
    prompt: str,
    *,
    model_id: str,
    max_tokens: int,
    temperature: float = 0.1,
    system_prompt: str = "",
    tool_name: str = "",
    tool_schema: Dict[str, Any] | None = None,
    tool_description: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    request = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
    }
    if system_prompt.strip():
        request["system"] = [{"text": system_prompt.strip()}]
    if tool_name.strip() and isinstance(tool_schema, dict) and tool_schema:
        request["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool_name.strip(),
                        "description": tool_description.strip() or tool_name.strip(),
                        "inputSchema": {"json": tool_schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name.strip()}},
        }
    response = _client().converse(**request)
    tool_input = _extract_tool_input(response, tool_name.strip() or None)
    if tool_input is not None:
        payload = tool_input
    else:
        text = _extract_text(response)
        payload = extract_json_object(text)
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return payload, {
        "mode": "bedrock",
        "model_id": model_id,
        "stop_reason": str(response.get("stopReason") or ""),
        "tool_name": tool_name.strip(),
        "tool_used": tool_input is not None,
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "total_tokens": usage.get("totalTokens"),
    }
