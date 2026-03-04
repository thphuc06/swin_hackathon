from __future__ import annotations

from typing import Any, Dict, Protocol

from .models import StockAdvisoryRequest, StockAdvisoryResponse


class IndexClient(Protocol):
    def search(
        self,
        query: str,
        filters: Dict[str, str],
        *,
        user_token: str = "",
        trace_id: str | None = None,
        intent: str = "",
    ) -> Dict[str, Any]:
        ...


class PolicyEngine(Protocol):
    def authorize_tool_call(self, tool_name: str, *, context: Dict[str, Any]) -> Dict[str, Any]:
        ...


class MemoryStore(Protocol):
    def get_session(self, session_id: str) -> Dict[str, Any]:
        ...

    def put_session(self, session_id: str, value: Dict[str, Any], *, ttl_seconds: int) -> None:
        ...


class ExternalStockAgent(Protocol):
    def advisory(
        self,
        request: StockAdvisoryRequest,
        *,
        trace_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> StockAdvisoryResponse:
        ...

