from __future__ import annotations

import logging
import os
import uuid
from typing import Generator, Optional

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.auth import current_user

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)
_SSE_REPLACEMENT_RATIO_WARN_THRESHOLD = 0.02
_MOJIBAKE_REPAIR_MIN_DELTA = 0.05
_MOJIBAKE_MARKERS = ("\u00c3", "\u00c2", "\u00e1\u00bb", "\ufffd")


class ChatRequest(BaseModel):
    prompt: str


def _mojibake_score(text: str) -> float:
    if not text:
        return 0.0
    marker_hits = sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)
    replacement_ratio = text.count("\ufffd") / max(1, len(text))
    marker_ratio = marker_hits / max(1, len(text))
    return min(1.0, (marker_ratio * 2.5) + replacement_ratio)


def _repair_mojibake_text(text: str) -> tuple[str, bool, str]:
    candidate_text = str(text or "")
    baseline_score = _mojibake_score(candidate_text)
    if baseline_score == 0.0:
        return candidate_text, False, ""

    best_text = candidate_text
    best_score = baseline_score
    best_strategy = ""
    strategies = (
        ("latin1_to_utf8", "latin-1"),
        ("cp1252_to_utf8", "cp1252"),
    )
    for strategy_name, source_encoding in strategies:
        try:
            repaired = candidate_text.encode(source_encoding).decode("utf-8")
        except UnicodeError:
            continue
        repaired_score = _mojibake_score(repaired)
        if repaired_score + _MOJIBAKE_REPAIR_MIN_DELTA < best_score:
            best_text = repaired
            best_score = repaired_score
            best_strategy = strategy_name
    return best_text, bool(best_strategy), best_strategy


def _repair_sse_data_line(line: str) -> tuple[str, bool, str]:
    if not line.startswith("data:"):
        return line, False, ""
    payload = line[5:]
    repaired_payload, repaired, strategy = _repair_mojibake_text(payload)
    if not repaired:
        return line, False, ""
    return f"data:{repaired_payload}", True, strategy


def _stream_local(prompt: str) -> Generator[str, None, None]:
    yield f"data: Simulated advisory for: {prompt}\n\n"
    yield "data: Disclaimer: Educational guidance only.\n\n"
    yield f"data: Trace: trc_{uuid.uuid4().hex[:8]}\n\n"


def _invoke_agentcore(
    prompt: str,
    bearer_token: Optional[str],
    user_id: Optional[str],
) -> Generator[str, None, None]:
    agent_arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    region = os.getenv("AWS_REGION", "us-east-1")
    payload = {"prompt": prompt}
    if bearer_token:
        payload["authorization"] = bearer_token
    if user_id:
        payload["user_id"] = user_id
    if agent_arn:
        try:
            escaped_arn = requests.utils.quote(agent_arn, safe="")
            url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped_arn}/invocations"
            headers = {
                "Content-Type": "application/json",
                "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()),
            }
            if bearer_token:
                headers["Authorization"] = bearer_token

            response = requests.post(
                url,
                params={"qualifier": "DEFAULT"},
                headers=headers,
                json=payload,
                timeout=100,
                stream=True,
            )
            if response.status_code >= 400:
                snippet = response.text[:500]
                yield f"data: Error: AgentCore returned {response.status_code} {response.reason}\n\n"
                if snippet:
                    yield f"data: Details: {snippet}\n\n"
                return

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                payload = response.json()
                result = payload.get("result") or payload.get("response", "")
                result, repaired, strategy = _repair_mojibake_text(str(result))
                if repaired:
                    logger.warning("agentcore_json_mojibake_repaired strategy=%s", strategy)
                trace_id = payload.get("trace_id", "")
                citations = payload.get("citations", [])
                disclaimer = payload.get("disclaimer", "")
                tool_calls = payload.get("tool_calls", [])
                response_meta = payload.get("response_meta", {})
                mode = ""
                fallback = ""
                reason_codes = ""
                if isinstance(response_meta, dict):
                    mode = str(response_meta.get("mode") or "").strip()
                    fallback = str(response_meta.get("fallback_used") or "").strip()
                    raw_reason_codes = response_meta.get("reason_codes")
                    if isinstance(raw_reason_codes, list):
                        reason_codes = ", ".join([str(item).strip() for item in raw_reason_codes if str(item).strip()])
                yield f"data: {result}\n\n"
                yield "data: RuntimeSource: aws_runtime\n\n"
                if mode:
                    yield f"data: ResponseMode: {mode}\n\n"
                if fallback:
                    yield f"data: ResponseFallback: {fallback}\n\n"
                if reason_codes:
                    yield f"data: ResponseReasonCodes: {reason_codes}\n\n"
                if trace_id:
                    yield f"data: Trace: {trace_id}\n\n"
                if citations:
                    cite_text = ", ".join([c.get("citation", "") for c in citations])
                    yield f"data: Citations: {cite_text}\n\n"
                if isinstance(tool_calls, list) and tool_calls:
                    tools_text = ", ".join([str(item).strip() for item in tool_calls if str(item).strip()])
                    if tools_text:
                        yield f"data: Tools: {tools_text}\n\n"
                if disclaimer:
                    yield f"data: Disclaimer: {disclaimer}\n\n"
                return

            total_chars = 0
            replacement_chars = 0
            for line in response.iter_lines(chunk_size=1):
                if line:
                    decoded = line.decode("utf-8", errors="replace")
                    total_chars += len(decoded)
                    replacement_chars += decoded.count("\ufffd")
                    if decoded.startswith("data:"):
                        decoded, repaired, strategy = _repair_sse_data_line(decoded)
                        if repaired:
                            logger.warning("agentcore_sse_mojibake_repaired strategy=%s", strategy)
                        yield decoded + "\n"
            if total_chars > 0:
                replacement_ratio = replacement_chars / max(1, total_chars)
                if replacement_ratio > _SSE_REPLACEMENT_RATIO_WARN_THRESHOLD:
                    logger.warning(
                        "sse_decode_replacement_detected ratio=%.4f replacements=%s total_chars=%s",
                        replacement_ratio,
                        replacement_chars,
                        total_chars,
                    )
            return
        except requests.RequestException as exc:
            yield f"data: Error: AgentCore request failed: {exc}\n\n"
            return

    # Fallback to local agentcore app for MVP streaming
    local_url = os.getenv("AGENTCORE_LOCAL_URL", "http://localhost:8080/invocations")
    try:
        response = requests.post(
            local_url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        yield f"data: {payload.get('result', '')}\n\n"
        yield "data: RuntimeSource: local_agent\n\n"
        response_meta = payload.get("response_meta", {})
        mode = ""
        fallback = ""
        reason_codes = ""
        if isinstance(response_meta, dict):
            mode = str(response_meta.get("mode") or "").strip()
            fallback = str(response_meta.get("fallback_used") or "").strip()
            raw_reason_codes = response_meta.get("reason_codes")
            if isinstance(raw_reason_codes, list):
                reason_codes = ", ".join([str(item).strip() for item in raw_reason_codes if str(item).strip()])
        if mode:
            yield f"data: ResponseMode: {mode}\n\n"
        if fallback:
            yield f"data: ResponseFallback: {fallback}\n\n"
        if reason_codes:
            yield f"data: ResponseReasonCodes: {reason_codes}\n\n"
        yield f"data: Trace: {payload.get('trace_id', '')}\n\n"
        citations = payload.get("citations", [])
        if citations:
            cite_text = ", ".join([c.get("citation", "") for c in citations])
            yield f"data: Citations: {cite_text}\n\n"
        tool_calls = payload.get("tool_calls", [])
        if isinstance(tool_calls, list) and tool_calls:
            tools_text = ", ".join([str(item).strip() for item in tool_calls if str(item).strip()])
            if tools_text:
                yield f"data: Tools: {tools_text}\n\n"
        yield f"data: Disclaimer: {payload.get('disclaimer', '')}\n\n"
    except requests.RequestException as exc:
        yield f"data: Error: Local agentcore request failed: {exc}\n\n"


@router.post("/stream")
def stream_chat(
    payload: ChatRequest,
    user=Depends(current_user),
    authorization: Optional[str] = Header(None),
):
    agent_arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    if agent_arn and not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for AgentCore Runtime (JWT required).",
        )
    return StreamingResponse(
        _invoke_agentcore(payload.prompt, authorization, user.get("sub") if user else None),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
