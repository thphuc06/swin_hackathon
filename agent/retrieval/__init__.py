"""Index client interfaces and adapters for retrieval."""

from .factory import get_index_client
from .local_index import LocalIndexClient
from .opensearch_index import OpenSearchIndexClient

__all__ = ["get_index_client", "LocalIndexClient", "OpenSearchIndexClient"]
