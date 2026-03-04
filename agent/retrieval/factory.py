from __future__ import annotations

from core.settings import RETRIEVAL_ADAPTER

from .local_index import LocalIndexClient
from .opensearch_index import OpenSearchIndexClient


_CACHED_CLIENT = None


def get_index_client():
    global _CACHED_CLIENT
    if _CACHED_CLIENT is not None:
        return _CACHED_CLIENT
    adapter = str(RETRIEVAL_ADAPTER or "local").strip().lower()
    if adapter == "opensearch":
        _CACHED_CLIENT = OpenSearchIndexClient()
    else:
        _CACHED_CLIENT = LocalIndexClient()
    return _CACHED_CLIENT

