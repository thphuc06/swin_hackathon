from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from core.errors import ExternalAgentUnavailableError, ValidationFailedError
from core.models import StockAdvisoryRequest, StockAdvisoryResponse

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class StockAgentClientConfig:
    enabled: bool
    base_url: str
    endpoint_path: str
    auth_token: str
    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_retries: int
    backoff_factor: float
    breaker_failure_threshold: int
    breaker_reset_seconds: int

    @classmethod
    def from_env(cls) -> "StockAgentClientConfig":
        return cls(
            enabled=_env_bool("STOCK_AGENT_EXTERNAL_ENABLED", False),
            base_url=str(os.getenv("STOCK_AGENT_EXTERNAL_BASE_URL") or "").strip(),
            endpoint_path=str(os.getenv("STOCK_AGENT_EXTERNAL_ENDPOINT_PATH") or "/v1/stock/advisory").strip()
            or "/v1/stock/advisory",
            auth_token=str(os.getenv("STOCK_AGENT_EXTERNAL_AUTH_TOKEN") or "").strip(),
            connect_timeout_seconds=_env_float("STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS", 2.0),
            read_timeout_seconds=_env_float("STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS", 8.0),
            max_retries=max(0, _env_int("STOCK_AGENT_EXTERNAL_MAX_RETRIES", 2)),
            backoff_factor=max(0.0, _env_float("STOCK_AGENT_EXTERNAL_BACKOFF_FACTOR", 0.4)),
            breaker_failure_threshold=max(1, _env_int("STOCK_AGENT_EXTERNAL_BREAKER_FAILURE_THRESHOLD", 3)),
            breaker_reset_seconds=max(5, _env_int("STOCK_AGENT_EXTERNAL_BREAKER_RESET_SECONDS", 60)),
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

    def advisory(
        self,
        request: StockAdvisoryRequest,
        *,
        trace_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> StockAdvisoryResponse:
        if not self.config.enabled:
            raise ExternalAgentUnavailableError(
                "Stock agent external integration is disabled.",
                metadata={"trace_id": trace_id, "reason": "disabled"},
                retryable=False,
            )
        if not self.config.base_url:
            raise ExternalAgentUnavailableError(
                "Stock agent base URL is not configured.",
                metadata={"trace_id": trace_id, "reason": "missing_base_url"},
                retryable=False,
            )
        if self._is_circuit_open():
            raise ExternalAgentUnavailableError(
                "Stock agent circuit breaker is open.",
                metadata={"trace_id": trace_id, "reason": "circuit_open"},
            )

        endpoint = f"{self.config.base_url.rstrip('/')}/{self.config.endpoint_path.lstrip('/')}"
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Trace-Id": trace_id,
            "X-Request-Id": request_id,
            "Idempotency-Key": idempotency_key,
        }
        if self.config.auth_token:
            token = self.config.auth_token
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"

        payload = request.to_payload()
        try:
            response = self._session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=(self.config.connect_timeout_seconds, self.config.read_timeout_seconds),
            )
            status_code = int(response.status_code or 0)
            if status_code >= 400:
                self._mark_failure()
                body_snippet = response.text[:400] if response.text else ""
                retryable = status_code in {408, 409, 425, 429, 500, 502, 503, 504}
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
            parsed = StockAdvisoryResponse.from_payload(raw)
            self._mark_success()
            return parsed
        except requests.Timeout as exc:
            self._mark_failure()
            raise ExternalAgentUnavailableError(
                "Stock agent request timed out.",
                metadata={"trace_id": trace_id, "request_id": request_id, "error": str(exc)},
            ) from exc
        except requests.RequestException as exc:
            self._mark_failure()
            raise ExternalAgentUnavailableError(
                "Stock agent request failed.",
                metadata={"trace_id": trace_id, "request_id": request_id, "error": str(exc)},
            ) from exc
        except ValidationFailedError:
            self._mark_failure()
            raise
        except ValueError as exc:
            self._mark_failure()
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

