from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

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
VALID_APP_ENVS = {"local", "demo", "staging", "prod"}
DEPLOYED_APP_ENVS = {"staging", "prod"}
_SESSION_CONTEXT_TTL_SECONDS = max(300, int(str(os.getenv("CHAT_SESSION_CONTEXT_TTL_SECONDS") or "7200").strip() or "7200"))
_SESSION_PLANNER_CONTEXT: Dict[str, Dict[str, Any]] = {}
_SESSION_CONTEXT_LOCK = threading.RLock()


class ChatRequest(BaseModel):
    prompt: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:8]}"


def _resolve_app_env() -> str:
    raw = str(os.getenv("APP_ENV") or "").strip().lower()
    if not raw:
        return "local"
    if raw not in VALID_APP_ENVS:
        raise RuntimeError("APP_ENV must be one of: local, demo, staging, prod.")
    return raw


def _is_deployed_backend() -> bool:
    return _resolve_app_env() in DEPLOYED_APP_ENVS


def _resolve_runtime_region() -> str:
    region = str(os.getenv("AWS_REGION") or "").strip()
    if region:
        return region
    if _is_deployed_backend():
        raise RuntimeError("AWS_REGION must be explicitly set for deployed backend runtime invocation.")
    return "us-east-1"


def _resolve_local_runtime_url() -> str:
    return str(os.getenv("AGENTCORE_LOCAL_URL") or "").strip()


def _validate_runtime_target_config() -> None:
    agent_arn = str(os.getenv("AGENTCORE_RUNTIME_ARN") or "").strip()
    if agent_arn:
        _resolve_runtime_region()
        return

    if _is_deployed_backend():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AGENTCORE_RUNTIME_ARN must be explicitly set when APP_ENV is staging or prod.",
        )

    if not _resolve_local_runtime_url():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AGENTCORE_LOCAL_URL must be explicitly set for local or demo backend mode.",
        )


def _default_session_id(user_sub: Optional[str], trace_id: str) -> str:
    _ = user_sub
    _ = trace_id
    # Use an opaque session id by default so callers without X-Session-Id do not
    # accidentally collide with prior user-scoped sessions.
    return f"chat_{uuid.uuid4().hex}"


def _prune_session_context_locked(now_ts: float | None = None) -> None:
    now_ts = float(now_ts if now_ts is not None else time.time())
    stale_session_ids = [
        session_id
        for session_id, entry in _SESSION_PLANNER_CONTEXT.items()
        if now_ts - float(entry.get("updated_at") or 0.0) > _SESSION_CONTEXT_TTL_SECONDS
    ]
    for session_id in stale_session_ids:
        _SESSION_PLANNER_CONTEXT.pop(session_id, None)


def _planner_context_from_runtime_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    top_level = payload.get("planner_context") if isinstance(payload.get("planner_context"), dict) else {}
    planner_summary = str(top_level.get("planner_summary") or "").strip()
    planner_contract = (
        top_level.get("planner_standardized_contract")
        if isinstance(top_level.get("planner_standardized_contract"), dict)
        else {}
    )

    if not planner_summary or not planner_contract:
        agent_outputs = payload.get("agent_outputs") if isinstance(payload.get("agent_outputs"), dict) else {}
        planner_output = agent_outputs.get("planner") if isinstance(agent_outputs.get("planner"), dict) else {}
        if not planner_summary:
            planner_summary = str(
                planner_output.get("summary")
                or ((planner_output.get("result") or {}).get("summary") if isinstance(planner_output.get("result"), dict) else "")
                or ""
            ).strip()
        if not planner_contract:
            planner_contract = (
                planner_output.get("standardized_contract")
                if isinstance(planner_output.get("standardized_contract"), dict)
                else {}
            )

    planner_context: Dict[str, Any] = {}
    if planner_summary:
        planner_context["planner_summary"] = planner_summary
    if planner_contract:
        planner_context["planner_standardized_contract"] = planner_contract
    return planner_context


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = str(item.get("message") or item.get("title") or item.get("source_id") or item.get("ticker") or "").strip()
            else:
                text = str(item or "").strip()
            if text and text not in items:
                items.append(text)
        return items
    text = str(value or "").strip()
    return [text] if text else []


def _stock_context_from_runtime_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    top_level = payload.get("stock_context") if isinstance(payload.get("stock_context"), dict) else {}
    if top_level:
        return dict(top_level)

    agent_outputs = payload.get("agent_outputs") if isinstance(payload.get("agent_outputs"), dict) else {}
    stock_output = agent_outputs.get("stock") if isinstance(agent_outputs.get("stock"), dict) else {}
    if not stock_output:
        return {}

    result = stock_output.get("result") if isinstance(stock_output.get("result"), dict) else {}
    suitability = result.get("suitability") if isinstance(result.get("suitability"), dict) else {}
    warnings = stock_output.get("warnings") if isinstance(stock_output.get("warnings"), list) else result.get("warnings")
    alternatives = result.get("alternatives") if isinstance(result.get("alternatives"), list) else []
    recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
    citations = result.get("citations") if isinstance(result.get("citations"), list) else []

    warning_flags: list[str] = []
    for item in warnings if isinstance(warnings, list) else []:
        if isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            message = str(item.get("message") or "").strip()
            for part in (code, message):
                if part and part not in warning_flags:
                    warning_flags.append(part)
        else:
            text = str(item or "").strip()
            if text and text not in warning_flags:
                warning_flags.append(text)

    market_notes = _text_list(result.get("market_notes"))
    if not market_notes:
        for item in alternatives[:3]:
            if not isinstance(item, dict):
                continue
            rationale = str(item.get("rationale") or "").strip()
            if rationale and rationale not in market_notes:
                market_notes.append(rationale)

    cited_symbols: list[str] = []
    for collection in (recommendations, alternatives, citations):
        for item in collection:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("ticker") or item.get("symbol") or item.get("source_id") or "").strip()
            if symbol and symbol not in cited_symbols:
                cited_symbols.append(symbol)

    suitability_status = str(suitability.get("status") or (stock_output.get("policy") or {}).get("suitability") or "").strip()
    market_tone = str(result.get("market_tone") or stock_output.get("market_tone") or "").strip()
    if not market_tone:
        lowered_summary = str(result.get("summary") or stock_output.get("summary") or "").strip().lower()
        if suitability_status.lower() in {"warn", "fail", "deny", "blocked"} or warning_flags:
            market_tone = "cautious"
        elif suitability_status.lower() == "pass":
            market_tone = "constructive"
        elif any(marker in lowered_summary for marker in ("risk", "volatile", "uncertain", "cautious")):
            market_tone = "cautious"

    stock_context: Dict[str, Any] = {}
    summary = str(result.get("summary") or stock_output.get("summary") or "").strip()
    if summary:
        stock_context["summary"] = summary
    if suitability_status:
        stock_context["suitability_status"] = suitability_status
    if market_tone:
        stock_context["market_tone"] = market_tone
    if market_notes:
        stock_context["market_notes"] = market_notes
    if warning_flags:
        stock_context["warning_flags"] = warning_flags
    if cited_symbols:
        stock_context["cited_symbols"] = cited_symbols
    if stock_context:
        stock_context["source"] = str(stock_output.get("tool_name") or stock_output.get("agent_id") or "backend_session.stock").strip()
    return stock_context


def _service_payload_from_runtime_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    top_level = payload.get("service_payload") if isinstance(payload.get("service_payload"), dict) else {}
    if top_level:
        return top_level

    agent_outputs = payload.get("agent_outputs") if isinstance(payload.get("agent_outputs"), dict) else {}
    service_output = agent_outputs.get("service") if isinstance(agent_outputs.get("service"), dict) else {}
    return service_output if isinstance(service_output, dict) else {}


def _store_planner_context(session_id: str, payload: Dict[str, Any]) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    planner_context = _planner_context_from_runtime_payload(payload)
    stock_context = _stock_context_from_runtime_payload(payload)
    if not planner_context and not stock_context:
        return
    with _SESSION_CONTEXT_LOCK:
        _prune_session_context_locked()
        existing = _SESSION_PLANNER_CONTEXT.get(normalized_session_id) if normalized_session_id else None
        existing_planner = existing.get("planner_context") if isinstance(existing, dict) and isinstance(existing.get("planner_context"), dict) else {}
        existing_stock = existing.get("stock_context") if isinstance(existing, dict) and isinstance(existing.get("stock_context"), dict) else {}
        _SESSION_PLANNER_CONTEXT[normalized_session_id] = {
            "updated_at": time.time(),
            "planner_context": planner_context or existing_planner,
            "stock_context": stock_context or existing_stock,
        }


def _load_planner_context(session_id: str) -> Dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return {}
    with _SESSION_CONTEXT_LOCK:
        _prune_session_context_locked()
        entry = _SESSION_PLANNER_CONTEXT.get(normalized_session_id) if normalized_session_id else None
        if not isinstance(entry, dict):
            return {}
        planner_context = entry.get("planner_context") if isinstance(entry.get("planner_context"), dict) else {}
        return dict(planner_context)


def _load_stock_context(session_id: str) -> Dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return {}
    with _SESSION_CONTEXT_LOCK:
        _prune_session_context_locked()
        entry = _SESSION_PLANNER_CONTEXT.get(normalized_session_id) if normalized_session_id else None
        if not isinstance(entry, dict):
            return {}
        stock_context = entry.get("stock_context") if isinstance(entry.get("stock_context"), dict) else {}
        return dict(stock_context)


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


def _format_sse_data_event(payload: str) -> str:
    text = str(payload or "")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines:
        lines = [""]
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _stream_local(prompt: str) -> Generator[str, None, None]:
    yield f"data: Simulated advisory for: {prompt}\n\n"
    yield "data: Disclaimer: Educational guidance only.\n\n"
    yield f"data: Trace: trc_{uuid.uuid4().hex[:8]}\n\n"


def _invoke_agentcore(
    prompt: str,
    bearer_token: Optional[str],
    user_id: Optional[str],
    *,
    trace_id: str,
    session_id: str,
    request_timestamp: str,
) -> Generator[str, None, None]:
    agent_arn = str(os.getenv("AGENTCORE_RUNTIME_ARN") or "").strip()
    payload = {
        "prompt": prompt,
        "trace_id": trace_id,
        "session_id": session_id,
        "request_timestamp": request_timestamp,
    }
    cached_planner_context = _load_planner_context(session_id)
    if cached_planner_context:
        payload["planner_context"] = cached_planner_context
    cached_stock_context = _load_stock_context(session_id)
    if cached_stock_context:
        payload["stock_context"] = cached_stock_context
    if bearer_token:
        payload["authorization"] = bearer_token
    if user_id:
        payload["user_id"] = user_id
    if agent_arn:
        try:
            region = _resolve_runtime_region()
            escaped_arn = requests.utils.quote(agent_arn, safe="")
            url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped_arn}/invocations"
            headers = {
                "Content-Type": "application/json",
                "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()),
                "X-Trace-Id": trace_id,
                "X-Session-Id": session_id,
                "X-Request-Timestamp": request_timestamp,
            }
            if bearer_token:
                headers["Authorization"] = bearer_token

            response = requests.post(
                url,
                params={"qualifier": "DEFAULT"},
                headers=headers,
                json=payload,
                timeout=180,
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
                _store_planner_context(session_id, payload)
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
                yield _format_sse_data_event(result)
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
                service_payload = _service_payload_from_runtime_payload(payload)
                if isinstance(service_payload, dict) and service_payload:
                    yield f"data: ServiceEnvelopePayload: {json.dumps(service_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                roadmap_payload = payload.get("roadmap_payload")
                if not isinstance(roadmap_payload, dict):
                    service_output = service_payload
                    roadmap_payload = service_output.get("roadmap_contract") if isinstance(service_output.get("roadmap_contract"), dict) else {}
                if isinstance(roadmap_payload, dict) and roadmap_payload:
                    yield f"data: RoadmapPayload: {json.dumps(roadmap_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
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

    local_url = _resolve_local_runtime_url()
    if not local_url:
        raise RuntimeError("AGENTCORE_LOCAL_URL must be explicitly set for local or demo backend mode.")
    try:
        response = requests.post(
            local_url,
            headers={
                "Content-Type": "application/json",
                "X-Trace-Id": trace_id,
                "X-Session-Id": session_id,
                "X-Request-Timestamp": request_timestamp,
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        _store_planner_context(session_id, payload)
        yield _format_sse_data_event(str(payload.get("result", "")))
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
        service_payload = _service_payload_from_runtime_payload(payload)
        if isinstance(service_payload, dict) and service_payload:
            yield f"data: ServiceEnvelopePayload: {json.dumps(service_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        roadmap_payload = payload.get("roadmap_payload")
        if not isinstance(roadmap_payload, dict):
            service_output = service_payload
            roadmap_payload = service_output.get("roadmap_contract") if isinstance(service_output.get("roadmap_contract"), dict) else {}
        if isinstance(roadmap_payload, dict) and roadmap_payload:
            yield f"data: RoadmapPayload: {json.dumps(roadmap_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        yield f"data: Disclaimer: {payload.get('disclaimer', '')}\n\n"
    except requests.RequestException as exc:
        yield f"data: Error: Local agentcore request failed: {exc}\n\n"


@router.post("/stream")
def stream_chat(
    payload: ChatRequest,
    user=Depends(current_user),
    authorization: Optional[str] = Header(None),
    x_trace_id: Optional[str] = Header(None),
    x_session_id: Optional[str] = Header(None),
):
    _validate_runtime_target_config()
    agent_arn = str(os.getenv("AGENTCORE_RUNTIME_ARN") or "").strip()
    if agent_arn and not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for AgentCore Runtime (JWT required).",
        )
    trace_id = str(x_trace_id or "").strip() or _new_trace_id()
    session_id = str(x_session_id or "").strip() or _default_session_id(user.get("sub") if user else None, trace_id)
    request_timestamp = _utc_now_iso()
    logger.info("chat_request trace_id=%s session_id=%s", trace_id, session_id)
    return StreamingResponse(
        _invoke_agentcore(
            payload.prompt,
            authorization,
            user.get("sub") if user else None,
            trace_id=trace_id,
            session_id=session_id,
            request_timestamp=request_timestamp,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
