from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from core.errors import ExternalAgentUnavailableError, ValidationFailedError
from core.models import StockAdvisoryRequest, StockAdvisoryResponse, StockSuitabilityCheck

logger = logging.getLogger(__name__)
_UPPERCASE_TOKEN_PATTERN = re.compile(r"\b[A-Z]{2,5}\b")
_TABLE_SYMBOL_PATTERN = re.compile(r"^\|\s*([A-Z]{2,5})\s*\|")
_NON_SYMBOL_TOKENS = {"ATC", "CK", "HOSE", "HNX", "UPCOM", "VND", "VN30", "ETF"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _append_unique(items: list[str], value: str, *, limit: int) -> None:
    text = str(value or "").strip()
    if not text or text in items or len(items) >= limit:
        return
    items.append(text)


def _extract_highlighted_symbols(text: str, *, limit: int = 8) -> list[str]:
    symbols: list[str] = []
    for line in text.splitlines():
        table_match = _TABLE_SYMBOL_PATTERN.match(line.strip())
        if table_match:
            _append_unique(symbols, table_match.group(1), limit=limit)
    for token in _UPPERCASE_TOKEN_PATTERN.findall(text):
        if token in _NON_SYMBOL_TOKENS:
            continue
        _append_unique(symbols, token, limit=limit)
    return symbols


def _extract_market_notes(text: str, *, limit: int = 6) -> list[str]:
    notes: list[str] = []
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


@dataclass(frozen=True)
class StockAgentClientConfig:
    enabled: bool
    exact_url: str
    base_url: str
    endpoint_path: str
    auth_token: str
    model_provider: str
    model: str
    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_retries: int
    backoff_factor: float
    breaker_failure_threshold: int
    breaker_reset_seconds: int
    fallback_to_local_on_error: bool = True

    @classmethod
    def from_env(cls) -> "StockAgentClientConfig":
        return cls(
            enabled=_env_bool("STOCK_AGENT_EXTERNAL_ENABLED", False),
            exact_url=str(os.getenv("STOCK_AGENT_EXTERNAL_URL") or "").strip(),
            base_url=str(os.getenv("STOCK_AGENT_EXTERNAL_BASE_URL") or "").strip(),
            endpoint_path=str(os.getenv("STOCK_AGENT_EXTERNAL_ENDPOINT_PATH") or "/v1/stock/advisory").strip()
            or "/v1/stock/advisory",
            auth_token=str(os.getenv("STOCK_AGENT_EXTERNAL_AUTH_TOKEN") or "").strip(),
            model_provider=str(os.getenv("STOCK_AGENT_EXTERNAL_MODEL_PROVIDER") or "bedrock").strip() or "bedrock",
            model=str(os.getenv("STOCK_AGENT_EXTERNAL_MODEL") or "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0").strip()
            or "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0",
            connect_timeout_seconds=_env_float("STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS", 2.0),
            read_timeout_seconds=_env_float("STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS", 8.0),
            max_retries=max(0, _env_int("STOCK_AGENT_EXTERNAL_MAX_RETRIES", 2)),
            backoff_factor=max(0.0, _env_float("STOCK_AGENT_EXTERNAL_BACKOFF_FACTOR", 0.4)),
            breaker_failure_threshold=max(1, _env_int("STOCK_AGENT_EXTERNAL_BREAKER_FAILURE_THRESHOLD", 3)),
            breaker_reset_seconds=max(5, _env_int("STOCK_AGENT_EXTERNAL_BREAKER_RESET_SECONDS", 60)),
            fallback_to_local_on_error=_env_bool("STOCK_AGENT_EXTERNAL_FALLBACK_TO_LOCAL", True),
        )


class StockAgentClient:
    def __init__(self, config: StockAgentClientConfig | None = None) -> None:
        self.config = config or StockAgentClientConfig.from_env()
        self._session = requests.Session()
        retry = Retry(
            total=self.config.max_retries,
            connect=self.config.max_retries,
            read=self.config.max_retries,
            status=self.config.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=self.config.backoff_factor,
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._consecutive_failures = 0
        self._circuit_opened_at = 0.0

    def _is_circuit_open(self) -> bool:
        if self._consecutive_failures < self.config.breaker_failure_threshold:
            return False
        elapsed = time.time() - self._circuit_opened_at
        if elapsed >= self.config.breaker_reset_seconds:
            self._consecutive_failures = 0
            self._circuit_opened_at = 0.0
            return False
        return True

    def _mark_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.config.breaker_failure_threshold and self._circuit_opened_at == 0.0:
            self._circuit_opened_at = time.time()

    def _mark_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_opened_at = 0.0

    def _endpoint(self) -> str:
        if self.config.exact_url:
            return self.config.exact_url
        if not self.config.base_url:
            return ""
        return f"{self.config.base_url.rstrip('/')}/{self.config.endpoint_path.lstrip('/')}"

    def _request_mode(self, endpoint: str) -> str:
        normalized = str(endpoint or "").strip().rstrip("/").lower()
        if normalized.endswith("/ask"):
            return "ask"
        return "legacy"

    def _request_payload(self, request: StockAdvisoryRequest, *, endpoint: str) -> Dict[str, Any]:
        if self._request_mode(endpoint) == "ask":
            return {
                "question": str(request.query or "").strip(),
                "modelProvider": self.config.model_provider,
                "model": self.config.model,
            }
        return request.to_payload()

    def _timeouts(self, endpoint: str) -> tuple[float, float]:
        connect_timeout = max(1.0, float(self.config.connect_timeout_seconds))
        read_timeout = max(1.0, float(self.config.read_timeout_seconds))
        if self._request_mode(endpoint) == "ask":
            read_timeout = max(read_timeout, 120.0)
        return connect_timeout, read_timeout

    def _response_payload(self, payload: Dict[str, Any], *, endpoint: str) -> Dict[str, Any]:
        if self._request_mode(endpoint) != "ask":
            return payload
        normalized = dict(payload)
        summary = str(
            normalized.get("summary")
            or normalized.get("answer")
            or normalized.get("message")
            or normalized.get("result")
            or ""
        ).strip()
        normalized["summary"] = summary
        normalized.setdefault("alternatives", [])
        normalized.setdefault("citations", [])
        normalized.setdefault("warnings", [])
        market_snapshot = normalized.get("market_snapshot") if isinstance(normalized.get("market_snapshot"), dict) else {}
        highlighted_symbols = _extract_highlighted_symbols(summary)
        market_notes = _extract_market_notes(summary)
        if highlighted_symbols:
            market_snapshot["highlighted_symbols"] = highlighted_symbols
        if market_notes:
            market_snapshot["market_notes"] = market_notes
        if market_snapshot:
            normalized["market_snapshot"] = market_snapshot
        if not isinstance(normalized.get("suitability_check"), dict):
            normalized["suitability_check"] = {
                "status": "warn",
                "reasons": ["education_only"],
            }
        return normalized

    def _local_fallback_response(
        self,
        request: StockAdvisoryRequest,
        *,
        reason: str,
        endpoint: str,
    ) -> StockAdvisoryResponse:
        summary = (
            "Live stock advisory data is temporarily unavailable, so this response uses "
            "education-only market guidance instead of live stock recommendations."
        )
        return StockAdvisoryResponse(
            summary=summary,
            alternatives=[
                "Review liquidity runway and emergency buffer before adding equity risk.",
                "Prefer broad diversification and position sizing over single-stock conviction.",
                "Wait for current earnings, guidance, and filings before acting on individual stocks.",
            ],
            suitability_check=StockSuitabilityCheck(
                status="warn",
                reasons=["education_only", "live_data_unavailable"],
            ),
            citations=[],
            confidence=0.0,
            warnings=[reason],
            market_snapshot={
                "fallback_used": "local_education_only",
                "fallback_reason_codes": ["stock_local_fallback"],
                "external_endpoint": endpoint,
            },
        )

    def _maybe_fallback_to_local(
        self,
        request: StockAdvisoryRequest,
        *,
        reason: str,
        endpoint: str,
    ) -> StockAdvisoryResponse | None:
        if not self.config.fallback_to_local_on_error:
            return None
        logger.warning("StockAgentClient falling back to local education-only response: %s", reason)
        return self._local_fallback_response(request, reason=reason, endpoint=endpoint)

    def advisory(
        self,
        request: StockAdvisoryRequest,
        *,
        trace_id: str,
        request_id: str,
        idempotency_key: str,
        session_id: str = "",
        request_timestamp: str = "",
        agent_name: str = "",
        schema_version: str = "",
    ) -> StockAdvisoryResponse:
        endpoint = self._endpoint()

        if not self.config.enabled:
            fallback = self._maybe_fallback_to_local(
                request,
                reason="Stock agent external integration is disabled in this environment.",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise ExternalAgentUnavailableError(
                "Stock agent external integration is disabled.",
                metadata={"trace_id": trace_id, "reason": "disabled"},
                retryable=False,
            )
        if self._is_circuit_open():
            fallback = self._maybe_fallback_to_local(
                request,
                reason="Stock agent circuit breaker is open; using education-only fallback.",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise ExternalAgentUnavailableError(
                "Stock agent circuit breaker is open.",
                metadata={"trace_id": trace_id, "reason": "circuit_open"},
            )

        if not endpoint:
            fallback = self._maybe_fallback_to_local(
                request,
                reason="Stock agent endpoint is not configured; using education-only fallback.",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise ExternalAgentUnavailableError(
                "Stock agent endpoint is not configured.",
                metadata={"trace_id": trace_id, "reason": "missing_endpoint"},
                retryable=False,
            )
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Trace-Id": trace_id,
            "X-Request-Id": request_id,
            "Idempotency-Key": idempotency_key,
        }
        if str(session_id or "").strip():
            headers["X-Session-Id"] = str(session_id).strip()
        if str(request_timestamp or "").strip():
            headers["X-Request-Timestamp"] = str(request_timestamp).strip()
        if str(agent_name or "").strip():
            headers["X-Agent-Name"] = str(agent_name).strip()
        if str(schema_version or "").strip():
            headers["X-Schema-Version"] = str(schema_version).strip()
        if self.config.auth_token:
            token = self.config.auth_token
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"

        payload = self._request_payload(request, endpoint=endpoint)
        try:
            response = self._session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self._timeouts(endpoint),
            )
            status_code = int(response.status_code or 0)
            if status_code >= 400:
                self._mark_failure()
                body_snippet = response.text[:400] if response.text else ""
                retryable = status_code in {408, 409, 425, 429, 500, 502, 503, 504}
                fallback = self._maybe_fallback_to_local(
                    request,
                    reason=f"Stock agent returned HTTP {status_code}; using education-only fallback.",
                    endpoint=endpoint,
                )
                if fallback is not None:
                    return fallback
                raise ExternalAgentUnavailableError(
                    f"Stock agent returned HTTP {status_code}.",
                    retryable=retryable,
                    metadata={
                        "trace_id": trace_id,
                        "status_code": status_code,
                        "request_id": request_id,
                        "response_body": body_snippet,
                    },
                )

            raw = response.json()
            parsed = StockAdvisoryResponse.from_payload(self._response_payload(raw, endpoint=endpoint))
            self._mark_success()
            return parsed
        except requests.Timeout as exc:
            self._mark_failure()
            fallback = self._maybe_fallback_to_local(
                request,
                reason="Stock agent request timed out; using education-only fallback.",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise ExternalAgentUnavailableError(
                "Stock agent request timed out.",
                metadata={"trace_id": trace_id, "request_id": request_id, "error": str(exc)},
            ) from exc
        except requests.RequestException as exc:
            self._mark_failure()
            fallback = self._maybe_fallback_to_local(
                request,
                reason=f"Stock agent request failed; using education-only fallback. Details: {exc}",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise ExternalAgentUnavailableError(
                "Stock agent request failed.",
                metadata={"trace_id": trace_id, "request_id": request_id, "error": str(exc)},
            ) from exc
        except ValidationFailedError as exc:
            self._mark_failure()
            fallback = self._maybe_fallback_to_local(
                request,
                reason=f"Stock agent returned an invalid payload; using education-only fallback. Details: {exc}",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise
        except ValueError as exc:
            self._mark_failure()
            fallback = self._maybe_fallback_to_local(
                request,
                reason=f"Stock agent returned invalid JSON; using education-only fallback. Details: {exc}",
                endpoint=endpoint,
            )
            if fallback is not None:
                return fallback
            raise ValidationFailedError(
                "Stock agent returned invalid JSON payload.",
                metadata={"trace_id": trace_id, "request_id": request_id, "error": str(exc)},
            ) from exc


_DEFAULT_CLIENT: StockAgentClient | None = None


def get_stock_agent_client() -> StockAgentClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = StockAgentClient()
        logger.info("Initialized StockAgentClient (enabled=%s)", _DEFAULT_CLIENT.config.enabled)
    return _DEFAULT_CLIENT

