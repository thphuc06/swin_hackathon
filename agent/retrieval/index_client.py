from __future__ import annotations

from typing import Any, Dict, Protocol


class RetrievalIndexClient(Protocol):
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

