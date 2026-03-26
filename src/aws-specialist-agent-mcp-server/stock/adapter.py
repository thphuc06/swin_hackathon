from __future__ import annotations

import os
import logging
import re
from typing import Any, Dict, List

import requests

from planner_agent.contracts import SpecialistRequestEnvelope

SCHEMA_VERSION = "v1"
AGENT_ID = "stock"
TOOL_NAME = "run_stock_agent_v1"
DEFAULT_MODEL_PROVIDER = "bedrock"
DEFAULT_MODEL = "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0"

logger = logging.getLogger(__name__)
_UPPERCASE_TOKEN_PATTERN = re.compile(r"\b[A-Z]{2,5}\b")
_TABLE_SYMBOL_PATTERN = re.compile(r"^\|\s*([A-Z]{2,5})\s*\|")
_NON_SYMBOL_TOKENS = {"ATC", "CK", "HOSE", "HNX", "UPCOM", "VND", "VN30", "ETF"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _stock_exact_url() -> str:
    return str(os.getenv("STOCK_AGENT_EXTERNAL_URL") or "").strip()


def _stock_endpoint_path() -> str:
    return str(os.getenv("STOCK_AGENT_EXTERNAL_ENDPOINT_PATH") or "/ask").strip() or "/ask"


def _stock_url() -> str:
    exact = _stock_exact_url()
    if exact:
        return exact
    base = str(os.getenv("STOCK_AGENT_EXTERNAL_BASE_URL") or "").strip()
    path = _stock_endpoint_path()
    if not base:
        return ""
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _stock_request_mode(url: str) -> str:
    normalized = str(url or "").strip().rstrip("/").lower()
    if normalized.endswith("/ask"):
        return "ask"
    return "legacy"


def _stock_model_provider() -> str:
    return str(os.getenv("STOCK_AGENT_EXTERNAL_MODEL_PROVIDER") or DEFAULT_MODEL_PROVIDER).strip() or DEFAULT_MODEL_PROVIDER


def _stock_model() -> str:
    return str(os.getenv("STOCK_AGENT_EXTERNAL_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _stock_headers(correlation: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = str(os.getenv("STOCK_AGENT_EXTERNAL_AUTH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    if str(correlation.get("trace_id") or "").strip():
        headers["X-Trace-Id"] = str(correlation.get("trace_id") or "").strip()
    if str(correlation.get("request_id") or "").strip():
        headers["X-Request-Id"] = str(correlation.get("request_id") or "").strip()
    if str(correlation.get("session_id") or "").strip():
        headers["X-Session-Id"] = str(correlation.get("session_id") or "").strip()
    return headers


def _append_unique(items: List[str], value: str, *, limit: int) -> None:
    text = str(value or "").strip()
    if not text or text in items or len(items) >= limit:
        return
    items.append(text)


def _extract_highlighted_symbols(text: str, *, limit: int = 8) -> List[str]:
    symbols: List[str] = []
    for line in text.splitlines():
        table_match = _TABLE_SYMBOL_PATTERN.match(line.strip())
        if table_match:
            _append_unique(symbols, table_match.group(1), limit=limit)
    for token in _UPPERCASE_TOKEN_PATTERN.findall(text):
        if token in _NON_SYMBOL_TOKENS:
            continue
        _append_unique(symbols, token, limit=limit)
    return symbols


def _extract_market_notes(text: str, *, limit: int = 6) -> List[str]:
    notes: List[str] = []
    in_highlights = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if "điểm nhấn" in lowered or "diem nhan" in lowered:
            in_highlights = True
            continue
        if in_highlights and (line.startswith("- ") or line.startswith("* ")):
            _append_unique(notes, line[2:].strip(), limit=limit)
            continue
        if in_highlights and line and not line.startswith("|") and not line.startswith("**"):
            in_highlights = False
        if line.startswith("Thị trường") or line.startswith("Thi truong"):
            _append_unique(notes, line, limit=limit)
    return notes



def _legacy_external_payload(request: SpecialistRequestEnvelope) -> Dict[str, Any]:
    user_context = request.request.user_context or {}
    risk_profile = user_context.get("risk_profile") if isinstance(user_context.get("risk_profile"), dict) else {}
    liquidity = user_context.get("liquidity_constraints") if isinstance(user_context.get("liquidity_constraints"), dict) else {}
    return {
        "user_id": request.actor.user_id,
        "query": request.request.prompt,
        "risk_profile": {
            "risk_band": str(risk_profile.get("risk_band") or "unknown"),
            "horizon_months": int(risk_profile.get("horizon_months") or 0),
            "liquidity_need": str(liquidity.get("liquidity_need") or ""),
        },
        "constraints": {
            "education_only": bool(request.request.policy_flags.get("education_only", False)),
            "suitability_required": True,
        },
        "context_snapshot": {
            "net_cashflow": float(user_context.get("net_cashflow") or 0.0),
            "runway_months": float(user_context.get("runway_months") or 0.0),
            "anomaly_flags": list(user_context.get("anomaly_flags") or []),
        },
    }


def _ask_external_payload(request: SpecialistRequestEnvelope) -> Dict[str, Any]:
    return {
        "question": str(request.request.prompt or "").strip(),
        "modelProvider": _stock_model_provider(),
        "model": _stock_model(),
    }


def _external_payload(request: SpecialistRequestEnvelope, *, url: str) -> Dict[str, Any]:
    if _stock_request_mode(url) == "ask":
        return _ask_external_payload(request)
    return _legacy_external_payload(request)


def _stock_timeout_seconds(url: str) -> float:
    timeout_seconds = max(1.0, _env_float("STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS", 10.0))
    if _stock_request_mode(url) == "ask":
        return max(timeout_seconds, 120.0)
    return timeout_seconds


def _normalize_string_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_citations(raw: Any) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return citations
    for item in raw:
        if isinstance(item, dict):
            source_id = str(item.get("source_id") or item.get("id") or item.get("title") or "").strip()
            if not source_id:
                continue
            citations.append(
                {
                    "source_id": source_id,
                    "title": str(item.get("title") or source_id),
                    "snippet": str(item.get("snippet") or "").strip() or None,
                    "url": str(item.get("url") or "").strip() or None,
                }
            )
            continue
        text = str(item).strip()
        if text:
            citations.append({"source_id": text, "title": text})
    return citations


def _normalize_warnings(raw: Any) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return warnings
    for item in raw:
        if isinstance(item, dict):
            code = str(item.get("code") or "stock_external_warning").strip() or "stock_external_warning"
            message = str(item.get("message") or item.get("detail") or "").strip()
            if not message:
                continue
            severity = str(item.get("severity") or "warn").strip().lower() or "warn"
            warnings.append({"code": code, "message": message, "severity": severity})
            continue
        message = str(item).strip()
        if message:
            warnings.append({"code": "stock_external_warning", "message": message, "severity": "warn"})
    return warnings


def _extract_summary(payload: Dict[str, Any]) -> str:
    for key in ("answer", "summary", "message", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Stock specialist returned an empty summary."


def _map_external_response(
    request: SpecialistRequestEnvelope,
    payload: Dict[str, Any],
    *,
    request_mode: str,
) -> Dict[str, Any]:
    recommendations: List[Dict[str, Any]] = []
    summary = _extract_summary(payload)
    risk_band = str(((request.request.user_context or {}).get("risk_profile") or {}).get("risk_band") or "unknown")
    highlighted_symbols = _extract_highlighted_symbols(summary)
    extracted_market_notes = _extract_market_notes(summary)
    raw_recommendations = payload.get("recommendations") if isinstance(payload.get("recommendations"), list) else []
    for item in raw_recommendations:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("symbol") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        rationale = str(item.get("rationale") or item.get("reason") or "").strip()
        if ticker and action in {"buy", "hold", "avoid"} and rationale:
            recommendations.append(
                {
                    "ticker": ticker,
                    "action": action,
                    "rationale": rationale,
                    "risk_level": str(item.get("risk_level") or risk_band),
                }
            )

    alternatives = []
    for item in payload.get("alternatives", []) if isinstance(payload.get("alternatives"), list) else []:
        if isinstance(item, dict):
            ticker = str(item.get("ticker") or item.get("symbol") or "").strip()
            rationale = str(item.get("rationale") or item.get("reason") or "Alternative returned by the external stock service.").strip()
            if ticker and rationale:
                alternatives.append({"ticker": ticker, "rationale": rationale})
            continue
        ticker = str(item or "").strip()
        if ticker:
            alternatives.append({"ticker": ticker, "rationale": "Alternative returned by the external stock service."})
    if not alternatives:
        for ticker in highlighted_symbols:
            alternatives.append(
                {
                    "ticker": ticker,
                    "rationale": "Highlighted in the latest external market snapshot.",
                }
            )

    raw_suitability = payload.get("suitability_check") if isinstance(payload.get("suitability_check"), dict) else {}
    if not raw_suitability and isinstance(payload.get("suitability"), dict):
        raw_suitability = payload.get("suitability")
    if not raw_suitability and request_mode == "ask":
        raw_suitability = {
            "status": "warn",
            "reasons": ["education_only"],
        }
    raw_status = str(raw_suitability.get("status") or "").strip().lower()
    status = "unknown"
    if raw_status == "pass":
        status = "pass"
    elif raw_status == "warn":
        status = "warn"
    elif raw_status == "deny":
        status = "fail"
    elif raw_status in {"fail", "blocked"}:
        status = "fail"

    warnings = _normalize_warnings(payload.get("warnings"))
    citations = _normalize_citations(payload.get("citations"))
    market_notes = _normalize_string_list(payload.get("market_notes"))
    if not market_notes:
        market_notes = extracted_market_notes
    if not market_notes:
        market_notes = ["Stock specialist response came from the optional external compatibility path."]
    success = payload.get("success")
    envelope_status = "ok"
    errors: List[Dict[str, Any]] = []
    if success is False:
        envelope_status = "error"
        errors.append(
            {
                "code": "stock_external_unsuccessful",
                "message": summary,
                "retryable": False,
            }
        )
        if not warnings:
            warnings.append(
                {
                    "code": "stock_external_unsuccessful",
                    "message": "External stock service reported unsuccessful completion.",
                    "severity": "warn",
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "agent_id": AGENT_ID,
        "agent_version": str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0"),
        "tool_name": TOOL_NAME,
        "status": envelope_status,
        "correlation": request.correlation.model_dump(),
        "result": {
            "summary": summary,
            "recommendations": recommendations,
            "alternatives": alternatives,
            "suitability": {
                "status": status,
                "reason": ", ".join(str(item).strip() for item in raw_suitability.get("reasons", []) if str(item).strip()),
            },
            "market_notes": market_notes,
            "citations": citations,
            "warnings": warnings,
        },
        "summary": summary,
        "warnings": warnings,
        "errors": errors,
    }


def _local_placeholder_response(request: SpecialistRequestEnvelope, *, message: str) -> Dict[str, Any]:
    warning = {
        "code": "stock_external_warning",
        "message": message,
        "severity": "warn",
    }
    summary = (
        "Live stock advisory data is temporarily unavailable, so this response uses "
        "education-only market guidance instead of live stock recommendations."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "agent_id": AGENT_ID,
        "agent_version": str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0"),
        "tool_name": TOOL_NAME,
        "status": "partial",
        "correlation": request.correlation.model_dump(),
        "result": {
            "summary": summary,
            "recommendations": [],
            "alternatives": [
                {
                    "ticker": "GENERAL",
                    "rationale": "Review liquidity runway and emergency buffer before taking equity risk.",
                },
                {
                    "ticker": "GENERAL",
                    "rationale": "Prefer diversified exposure and disciplined position sizing over single-name conviction.",
                },
            ],
            "suitability": {
                "status": "unknown",
                "reason": "education_only, live_data_unavailable",
            },
            "market_notes": [
                "Live stock compatibility hosting is unavailable or unhealthy, so only education-only guidance is shown.",
            ],
            "citations": [],
            "warnings": [warning],
        },
        "summary": summary,
        "warnings": [warning],
        "errors": [
            {
                "code": "stock_external_unavailable",
                "message": message,
                "retryable": True,
            }
        ],
    }


def run_stock(payload: Dict[str, Any] | SpecialistRequestEnvelope) -> Dict[str, Any]:
    request = payload if isinstance(payload, SpecialistRequestEnvelope) else SpecialistRequestEnvelope.model_validate(payload)
    if not _env_bool("STOCK_AGENT_EXTERNAL_ENABLED", False):
        return _local_placeholder_response(
            request,
            message="Stock external hosting is disabled in this environment.",
        )
    url = _stock_url()
    if not url:
        return _local_placeholder_response(
            request,
            message="STOCK_AGENT_EXTERNAL_URL or STOCK_AGENT_EXTERNAL_BASE_URL must be configured to call the App Runner.",
        )
    try:
        response = requests.post(
            url,
            json=_external_payload(request, url=url),
            headers=_stock_headers(request.correlation.model_dump()),
            timeout=_stock_timeout_seconds(url),
        )
    except requests.Timeout as exc:
        return _local_placeholder_response(
            request,
            message="Stock external service request timed out. Using education-only fallback.",
        )
    except requests.RequestException as exc:
        return _local_placeholder_response(
            request,
            message=f"Stock external service request failed. Using education-only fallback. Details: {exc}",
        )

    if int(response.status_code or 0) >= 400:
        body_snippet = (response.text or "")[:400].strip()
        detail = f" Stock external service response: {body_snippet}" if body_snippet else ""
        return _local_placeholder_response(
            request,
            message=f"Stock external service returned HTTP {response.status_code}.{detail} Using education-only fallback.",
        )

    try:
        data = response.json()
    except ValueError as exc:
        return _local_placeholder_response(
            request,
            message="Stock external service returned invalid JSON. Using education-only fallback.",
        )
    if not isinstance(data, dict):
        return _local_placeholder_response(
            request,
            message="Stock external service returned a non-object JSON payload. Using education-only fallback.",
        )
    return _map_external_response(request, data, request_mode=_stock_request_mode(url))
