from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from config import (
    AGENTCORE_GATEWAY_ARN,
    AWS_REGION,
    BEDROCK_RESPONSES_API_KEY,
    BEDROCK_RESPONSES_BASE_URL,
    BEDROCK_RESPONSES_MAX_OUTPUT_TOKENS,
    BEDROCK_RESPONSES_MODEL_ID,
    BEDROCK_RESPONSES_TEMPERATURE,
    BEDROCK_RESPONSES_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."


def _responses_endpoint() -> str:
    base = str(BEDROCK_RESPONSES_BASE_URL or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/responses"):
        return base
    if base.endswith("/v1") or base.endswith("/openai/v1"):
        return f"{base}/responses"
    return f"{base}/openai/v1/responses"


def _aws_sigv4_headers(*, method: str, url: str, body: str, service: str) -> Dict[str, str]:
    session = boto3.Session(region_name=AWS_REGION)
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials are not available for SigV4 signing")
    frozen = credentials.get_frozen_credentials()
    aws_request = AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(frozen, service, AWS_REGION).add_auth(aws_request)
    return {str(key): str(value) for key, value in aws_request.headers.items()}


def _extract_response_text(payload: Dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if not isinstance(output, list):
        return ""

    chunks: List[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _extract_tool_calls(payload: Dict[str, Any]) -> list[str]:
    output = payload.get("output")
    if not isinstance(output, list):
        return []

    names: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if "tool" not in item_type and "mcp" not in item_type:
            continue
        for key in ("name", "tool_name", "id", "connector_id"):
            value = str(item.get(key) or "").strip()
            if not value:
                continue
            if key == "connector_id":
                value = value.split("/")[-1] or value
            names.append(value)
            break

    deduped: list[str] = []
    seen: set[str] = set()
    for item in names:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _post_with_sigv4(url: str, body: str) -> requests.Response:
    last_response: requests.Response | None = None
    for service in ("bedrock", "bedrock-mantle"):
        headers = _aws_sigv4_headers(method="POST", url=url, body=body, service=service)
        response = requests.post(url, data=body, headers=headers, timeout=BEDROCK_RESPONSES_TIMEOUT_SECONDS)
        last_response = response
        if response.status_code < 400:
            return response
        text = response.text.lower() if isinstance(response.text, str) else ""
        if response.status_code in {401, 403} and "credential should be scoped to correct service" in text:
            logger.warning("Responses API SigV4 service mismatch for '%s', retrying alternate service.", service)
            continue
        return response
    assert last_response is not None
    return last_response


def _normalize_user_prompt(prompt: str, user_id: str, session_id: str) -> str:
    safe_prompt = str(prompt or "").strip()
    prefix = (
        f"[runtime_context]\nuser_id={str(user_id or '').strip()}\n"
        f"session_id={str(session_id or '').strip()}\n[/runtime_context]\n\n"
    )
    return f"{prefix}{safe_prompt}"


def generate_dynamic_response(
    *,
    prompt: str,
    user_id: str,
    session_id: str,
    trace_id: str,
    request_id: str,
) -> Dict[str, Any]:
    endpoint = _responses_endpoint()
    if not endpoint:
        raise RuntimeError("BEDROCK_RESPONSES_BASE_URL is not configured")
    if not AGENTCORE_GATEWAY_ARN:
        raise RuntimeError("AGENTCORE_GATEWAY_ARN is not configured")

    started = time.perf_counter()
    payload = {
        "model": BEDROCK_RESPONSES_MODEL_ID,
        "input": _normalize_user_prompt(prompt, user_id=user_id, session_id=session_id),
        "tools": [
            {
                "type": "mcp",
                "connector_id": AGENTCORE_GATEWAY_ARN,
                "require_approval": "never",
            }
        ],
        "tool_choice": "auto",
        "temperature": BEDROCK_RESPONSES_TEMPERATURE,
        "max_output_tokens": BEDROCK_RESPONSES_MAX_OUTPUT_TOKENS,
        "metadata": {
            "trace_id": str(trace_id or "").strip(),
            "request_id": str(request_id or "").strip(),
            "session_id": str(session_id or "").strip(),
        },
    }
    body = json.dumps(payload, ensure_ascii=True)

    if BEDROCK_RESPONSES_API_KEY:
        response = requests.post(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {BEDROCK_RESPONSES_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=BEDROCK_RESPONSES_TIMEOUT_SECONDS,
        )
    else:
        response = _post_with_sigv4(endpoint, body)

    if response.status_code >= 400:
        snippet = (response.text or "")[:400]
        raise RuntimeError(f"Responses API failed ({response.status_code}): {snippet}")

    data = response.json()
    text = _extract_response_text(data)
    tool_calls = _extract_tool_calls(data)
    latency_ms = int((time.perf_counter() - started) * 1000)
    resolved_model = str(data.get("model") or BEDROCK_RESPONSES_MODEL_ID).strip() or BEDROCK_RESPONSES_MODEL_ID
    response_id = str(data.get("id") or "").strip()

    if not text:
        text = (
            "I could not produce a complete answer from dynamic tool execution. "
            "Please rephrase your request and try again."
        )
    if DEFAULT_DISCLAIMER.lower() not in text.lower():
        text = f"{text}\n\nDisclaimer: {DEFAULT_DISCLAIMER}"

    parsed_host = urlparse(endpoint).hostname or ""
    logger.info(
        "responses_dynamic_success trace=%s request=%s model=%s tools=%s latency_ms=%s endpoint_host=%s",
        trace_id,
        request_id,
        resolved_model,
        ",".join(tool_calls),
        latency_ms,
        parsed_host,
    )

    return {
        "text": text,
        "tool_calls": tool_calls,
        "response_id": response_id,
        "model_id": resolved_model,
        "latency_ms": latency_ms,
        "raw": data,
    }
