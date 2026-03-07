from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from config import (
    AGENTCORE_GATEWAY_ARN,
    AGENTCORE_GATEWAY_SERVER_LABEL,
    AWS_REGION,
    BEDROCK_RESPONSES_API_KEY,
    BEDROCK_RESPONSES_BASE_URL,
    BEDROCK_RESPONSES_CREATE_TIMEOUT_SECONDS,
    BEDROCK_RESPONSES_MAX_OUTPUT_TOKENS,
    BEDROCK_RESPONSES_MODEL_ID,
    BEDROCK_RESPONSES_POLL_INTERVAL_SECONDS,
    BEDROCK_RESPONSES_POLL_READ_TIMEOUT_SECONDS,
    BEDROCK_RESPONSES_RETRY_AFTER_SECONDS,
    BEDROCK_RESPONSES_SYNC_WAIT_SECONDS,
    BEDROCK_RESPONSES_TEMPERATURE,
    BEDROCK_RESPONSES_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."
_RESPONSES_PENDING_STATUSES = {"in_progress", "queued"}
_RESPONSES_TERMINAL_ERROR_STATUSES = {"failed", "incomplete", "cancelled"}
_SPEND_SUMMARY_SHORTLIST = [
    "financial-mcp-server___spend_analytics_v1",
    "financial-mcp-server___anomaly_signals_v1",
]


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
    normalized_method = str(method or "POST").upper()
    base_headers: Dict[str, str] = {}
    if normalized_method != "GET":
        base_headers["Content-Type"] = "application/json"
    aws_request = AWSRequest(
        method=normalized_method,
        url=url,
        data=body,
        headers=base_headers,
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
    seen: set[str] = set()
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type not in {"mcp_call", "tool_call", "function_call"}:
            continue
        name = str(item.get("name") or item.get("tool_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _extract_executed_tools(payload: Dict[str, Any]) -> list[str]:
    return _extract_tool_calls(payload)


def _request_with_sigv4(*, method: str, url: str, body: str = "", timeout_seconds: float) -> requests.Response:
    last_response: requests.Response | None = None
    last_error: Exception | None = None
    for service in ("bedrock-mantle",):
        headers = _aws_sigv4_headers(method=method, url=url, body=body, service=service)
        try:
            response = requests.request(
                method=method,
                url=url,
                data=body if method.upper() != "GET" else None,
                headers=headers,
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("Responses API request failed for SigV4 service '%s': %s", service, exc)
            continue
        last_response = response
        if response.status_code < 400:
            return response
        text = response.text.lower() if isinstance(response.text, str) else ""
        if response.status_code in {401, 403} and "credential should be scoped to correct service" in text:
            logger.warning("Responses API SigV4 service mismatch for '%s', retrying alternate service.", service)
            continue
        return response
    if last_error is not None:
        raise last_error
    assert last_response is not None
    return last_response


def _post_with_sigv4(url: str, body: str, *, timeout_seconds: float) -> requests.Response:
    return _request_with_sigv4(method="POST", url=url, body=body, timeout_seconds=timeout_seconds)


def _get_with_sigv4(url: str, *, timeout_seconds: float) -> requests.Response:
    return _request_with_sigv4(method="GET", url=url, body="", timeout_seconds=timeout_seconds)


def _normalize_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", stripped).strip()


def _soft_shortlist_for_prompt(prompt: str) -> tuple[str, list[str], int]:
    normalized = _normalize_text(prompt)
    spend_terms = ["tom tat", "tong hop", "chi tieu", "spend summary", "spending summary", "cashflow summary"]
    has_spend_term = any(term in normalized for term in spend_terms)
    has_30_day_term = any(token in normalized for token in ["30 ngay", "30 day", "30d", "30 days"])
    if has_spend_term and has_30_day_term:
        return "spend_summary_30d", list(_SPEND_SUMMARY_SHORTLIST), 2
    return "general_finance", [], 3


def _normalize_user_prompt(prompt: str, user_id: str, session_id: str) -> tuple[str, list[str], str, int]:
    safe_prompt = str(prompt or "").strip()
    intent_hint, shortlist, max_calls = _soft_shortlist_for_prompt(safe_prompt)
    prefix = (
        f"[runtime_context]\nuser_id={str(user_id or '').strip()}\n"
        f"session_id={str(session_id or '').strip()}\n[/runtime_context]\n\n"
    )
    policy_lines = [
        "[tool_call_policy]",
        f"- Intent hint: {intent_hint}.",
        f"- Use at most {max_calls} MCP tool calls total.",
        "- Never invoke the same MCP tool more than once per request.",
        "- Do not call the same tool again with identical arguments.",
        "- Always include `user_id` from runtime_context in every tool call arguments.",
        "- If tool execution fails or times out, provide a concise fallback answer.",
    ]
    if shortlist:
        policy_lines.append(
            "- Soft shortlist for this prompt: "
            + ", ".join(shortlist)
            + ". Prefer only these tools unless clearly insufficient."
        )
    if intent_hint == "spend_summary_30d":
        policy_lines.append(
            "- For spend_summary_30d, do not call suitability_guard_v1 or non-summary tools."
        )
        policy_lines.append(
            "- Call spend_analytics_v1 first; call anomaly_signals_v1 at most once only when anomaly warning is required."
        )
        policy_lines.append(
            "- If spend_analytics_v1 returns a valid 30-day summary, finalize the answer without retrying."
        )
    policy_lines.append("[/tool_call_policy]\n")
    tool_policy = "\n".join(policy_lines)
    return f"{prefix}{tool_policy}\n{safe_prompt}", shortlist, intent_hint, max_calls


def _resolve_wait_budget_seconds(wait_seconds: float | None) -> float:
    if wait_seconds is None:
        return float(BEDROCK_RESPONSES_SYNC_WAIT_SECONDS)
    try:
        candidate = float(wait_seconds)
    except (TypeError, ValueError):
        candidate = float(BEDROCK_RESPONSES_SYNC_WAIT_SECONDS)
    return max(1.0, min(float(BEDROCK_RESPONSES_TIMEOUT_SECONDS), candidate))


def _responses_post(endpoint: str, body: str) -> requests.Response:
    if BEDROCK_RESPONSES_API_KEY:
        return requests.post(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {BEDROCK_RESPONSES_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=float(BEDROCK_RESPONSES_CREATE_TIMEOUT_SECONDS),
        )
    return _post_with_sigv4(endpoint, body, timeout_seconds=float(BEDROCK_RESPONSES_CREATE_TIMEOUT_SECONDS))


def _responses_get(retrieve_endpoint: str, *, timeout_seconds: float | None = None) -> requests.Response:
    resolved_timeout = float(timeout_seconds) if timeout_seconds is not None else float(BEDROCK_RESPONSES_POLL_READ_TIMEOUT_SECONDS)
    if BEDROCK_RESPONSES_API_KEY:
        return requests.get(
            retrieve_endpoint,
            headers={"Authorization": f"Bearer {BEDROCK_RESPONSES_API_KEY}"},
            timeout=resolved_timeout,
        )
    return _get_with_sigv4(retrieve_endpoint, timeout_seconds=resolved_timeout)


def _poll_until_terminal_or_budget(
    *,
    endpoint: str,
    response_id: str,
    initial_payload: Dict[str, Any],
    wait_budget_seconds: float,
) -> tuple[Dict[str, Any], str, int, int, bool]:
    status = str(initial_payload.get("status") or "").strip().lower()
    if status not in _RESPONSES_PENDING_STATUSES:
        return initial_payload, status, 0, 0, False

    deadline = time.time() + wait_budget_seconds
    retrieve_endpoint = f"{endpoint.rstrip('/')}/{response_id}"
    poll_attempt_count = 0
    poll_read_timeout_count = 0
    latest_payload: Dict[str, Any] = dict(initial_payload)

    while time.time() < deadline:
        poll_attempt_count += 1
        remaining_seconds = deadline - time.time()
        if remaining_seconds <= 0:
            break
        # Do not let a single poll call exceed remaining wait budget.
        read_timeout_seconds = max(1.0, min(float(BEDROCK_RESPONSES_POLL_READ_TIMEOUT_SECONDS), remaining_seconds))
        try:
            polled = _responses_get(retrieve_endpoint, timeout_seconds=read_timeout_seconds)
        except requests.ReadTimeout:
            poll_read_timeout_count += 1
            remaining_after_timeout = deadline - time.time()
            if remaining_after_timeout <= 0:
                break
            sleep_seconds = min(float(BEDROCK_RESPONSES_POLL_INTERVAL_SECONDS), max(0.0, remaining_after_timeout))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            continue
        except requests.RequestException as exc:
            raise RuntimeError(f"Responses API polling request failed: {exc}") from exc

        if polled.status_code >= 400:
            snippet = (polled.text or "")[:400]
            raise RuntimeError(f"Responses API polling failed ({polled.status_code}): {snippet}")

        latest_payload = polled.json()
        status = str(latest_payload.get("status") or "").strip().lower()
        if status not in _RESPONSES_PENDING_STATUSES:
            return latest_payload, status, poll_attempt_count, poll_read_timeout_count, False
        remaining_after_success = deadline - time.time()
        if remaining_after_success <= 0:
            break
        sleep_seconds = min(float(BEDROCK_RESPONSES_POLL_INTERVAL_SECONDS), max(0.0, remaining_after_success))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    status = str(latest_payload.get("status") or "").strip().lower()
    timed_out = status in _RESPONSES_PENDING_STATUSES
    return latest_payload, status, poll_attempt_count, poll_read_timeout_count, timed_out


def _build_pending_text() -> str:
    return (
        "Dynamic analysis is still running with server-side tool execution. "
        "Please retry shortly to fetch the completed answer."
    )


def generate_dynamic_response(
    *,
    prompt: str,
    user_id: str,
    session_id: str,
    trace_id: str,
    request_id: str,
    response_id: str | None = None,
    wait_seconds: float | None = None,
) -> Dict[str, Any]:
    endpoint = _responses_endpoint()
    if not endpoint:
        raise RuntimeError("BEDROCK_RESPONSES_BASE_URL is not configured")
    if not AGENTCORE_GATEWAY_ARN:
        raise RuntimeError("AGENTCORE_GATEWAY_ARN is not configured")

    started = time.perf_counter()
    reason_codes: list[str] = []
    requested_response_id = str(response_id or "").strip()
    intent_hint = "poll_existing_response" if requested_response_id else ""
    shortlist_tools: list[str] = []
    payload_data: Dict[str, Any]

    if requested_response_id:
        active_response_id = requested_response_id
        payload_data = {
            "id": active_response_id,
            "status": "in_progress",
            "model": BEDROCK_RESPONSES_MODEL_ID,
            "output": [],
        }
    else:
        prompt_payload, shortlist_tools, intent_hint, max_calls = _normalize_user_prompt(
            prompt,
            user_id=user_id,
            session_id=session_id,
        )
        payload = {
            "model": BEDROCK_RESPONSES_MODEL_ID,
            "input": prompt_payload,
            "background": True,
            "parallel_tool_calls": False,
            "max_tool_calls": max(1, max_calls),
            "tools": [
                {
                    "type": "mcp",
                    "connector_id": AGENTCORE_GATEWAY_ARN,
                    "server_label": AGENTCORE_GATEWAY_SERVER_LABEL,
                    "require_approval": "never",
                    **({"allowed_tools": shortlist_tools} if shortlist_tools else {}),
                }
            ],
            "tool_choice": "auto",
            "temperature": BEDROCK_RESPONSES_TEMPERATURE,
            "max_output_tokens": BEDROCK_RESPONSES_MAX_OUTPUT_TOKENS,
            "metadata": {
                "trace_id": str(trace_id or "").strip(),
                "request_id": str(request_id or "").strip(),
                "session_id": str(session_id or "").strip(),
                "intent_hint": intent_hint,
            },
        }
        body = json.dumps(payload, ensure_ascii=True)
        created = _responses_post(endpoint, body)
        if created.status_code >= 400:
            snippet = (created.text or "")[:400]
            raise RuntimeError(f"Responses API failed ({created.status_code}): {snippet}")
        payload_data = created.json()
        active_response_id = str(payload_data.get("id") or "").strip()

    status = str(payload_data.get("status") or "").strip().lower()
    if not active_response_id:
        raise RuntimeError("Responses API did not return a response id")

    wait_budget_seconds = _resolve_wait_budget_seconds(wait_seconds)
    payload_data, status, poll_attempt_count, poll_read_timeout_count, timed_out = _poll_until_terminal_or_budget(
        endpoint=endpoint,
        response_id=active_response_id,
        initial_payload=payload_data,
        wait_budget_seconds=wait_budget_seconds,
    )
    if poll_read_timeout_count > 0:
        reason_codes.append("dynamic_poll_readtimeout_recovered")

    if status in _RESPONSES_PENDING_STATUSES and timed_out:
        reason_codes.append("dynamic_pending_async")
        latency_ms = int((time.perf_counter() - started) * 1000)
        resolved_model = str(payload_data.get("model") or BEDROCK_RESPONSES_MODEL_ID).strip() or BEDROCK_RESPONSES_MODEL_ID
        parsed_host = urlparse(endpoint).hostname or ""
        executed_tools = _extract_executed_tools(payload_data)
        logger.info(
            "responses_dynamic_pending trace=%s request=%s response_id=%s model=%s intent_hint=%s shortlist=%s executed_tools=%s poll_attempts=%s poll_read_timeouts=%s latency_ms=%s endpoint_host=%s",
            trace_id,
            request_id,
            active_response_id,
            resolved_model,
            intent_hint,
            ",".join(shortlist_tools),
            ",".join(executed_tools),
            poll_attempt_count,
            poll_read_timeout_count,
            latency_ms,
            parsed_host,
        )
        return {
            "status": "pending",
            "text": _build_pending_text(),
            "tool_calls": _extract_tool_calls(payload_data),
            "executed_tools": executed_tools,
            "response_id": active_response_id,
            "model_id": resolved_model,
            "latency_ms": latency_ms,
            "reason_codes": sorted(set(reason_codes)),
            "retry_after_seconds": int(BEDROCK_RESPONSES_RETRY_AFTER_SECONDS),
            "poll_attempt_count": poll_attempt_count,
            "poll_read_timeout_count": poll_read_timeout_count,
            "intent_hint": intent_hint,
            "shortlist_tools": shortlist_tools,
            "raw": payload_data,
        }

    if status in _RESPONSES_TERMINAL_ERROR_STATUSES:
        err_obj = payload_data.get("error") if isinstance(payload_data.get("error"), dict) else {}
        err_message = str(err_obj.get("message") or "").strip()
        if not err_message:
            err_message = str(payload_data.get("status") or "unknown error").strip()
        raise RuntimeError(f"Responses API returned {status}: {err_message[:400]}")

    text = _extract_response_text(payload_data)
    tool_calls = _extract_tool_calls(payload_data)
    executed_tools = _extract_executed_tools(payload_data)
    latency_ms = int((time.perf_counter() - started) * 1000)
    resolved_model = str(payload_data.get("model") or BEDROCK_RESPONSES_MODEL_ID).strip() or BEDROCK_RESPONSES_MODEL_ID

    if requested_response_id:
        reason_codes.append("dynamic_async_completed")

    if not text:
        text = (
            "I could not produce a complete answer from dynamic tool execution. "
            "Please rephrase your request and try again."
        )
    if DEFAULT_DISCLAIMER.lower() not in text.lower():
        text = f"{text}\n\nDisclaimer: {DEFAULT_DISCLAIMER}"

    parsed_host = urlparse(endpoint).hostname or ""
    logger.info(
        "responses_dynamic_terminal trace=%s request=%s response_id=%s terminal_status=%s model=%s intent_hint=%s shortlist=%s executed_tools=%s poll_attempts=%s poll_read_timeouts=%s latency_ms=%s endpoint_host=%s",
        trace_id,
        request_id,
        active_response_id,
        status,
        resolved_model,
        intent_hint,
        ",".join(shortlist_tools),
        ",".join(executed_tools),
        poll_attempt_count,
        poll_read_timeout_count,
        latency_ms,
        parsed_host,
    )

    return {
        "status": "completed",
        "text": text,
        "tool_calls": tool_calls,
        "executed_tools": executed_tools,
        "response_id": active_response_id,
        "model_id": resolved_model,
        "latency_ms": latency_ms,
        "reason_codes": sorted(set(reason_codes)),
        "retry_after_seconds": int(BEDROCK_RESPONSES_RETRY_AFTER_SECONDS),
        "poll_attempt_count": poll_attempt_count,
        "poll_read_timeout_count": poll_read_timeout_count,
        "intent_hint": intent_hint,
        "shortlist_tools": shortlist_tools,
        "raw": payload_data,
    }
