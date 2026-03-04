from __future__ import annotations

from typing import Any, Dict

from tools import kb_retrieve


class LocalIndexClient:
    """Cheap MVP retrieval adapter backed by local KB files."""

    def search(
        self,
        query: str,
        filters: Dict[str, str],
        *,
        user_token: str = "",
        trace_id: str | None = None,
        intent: str = "",
    ) -> Dict[str, Any]:
        return kb_retrieve(query, filters, user_token, trace_id=trace_id, intent=intent)


_DEFAULT_INDEX = LocalIndexClient()


def get_local_index_client() -> LocalIndexClient:
    return _DEFAULT_INDEX

