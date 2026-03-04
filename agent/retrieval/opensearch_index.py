from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import requests

from core.settings import (
    OPENSEARCH_API_KEY,
    OPENSEARCH_ENDPOINT,
    OPENSEARCH_INDEX_NAME,
    OPENSEARCH_TIMEOUT_SECONDS,
    OPENSEARCH_VERIFY_TLS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenSearchConfig:
    endpoint: str
    index_name: str
    api_key: str
    timeout_seconds: float
    verify_tls: bool

    @classmethod
    def from_env(cls) -> "OpenSearchConfig":
        return cls(
            endpoint=str(OPENSEARCH_ENDPOINT or "").strip(),
            index_name=str(OPENSEARCH_INDEX_NAME or "agent-kb").strip() or "agent-kb",
            api_key=str(OPENSEARCH_API_KEY or "").strip(),
            timeout_seconds=max(0.2, float(OPENSEARCH_TIMEOUT_SECONDS or 3.0)),
            verify_tls=bool(OPENSEARCH_VERIFY_TLS),
        )


class OpenSearchIndexClient:
    """Swap-in retrieval adapter for OpenSearch-compatible APIs."""

    def __init__(self, config: OpenSearchConfig | None = None) -> None:
        self._config = config or OpenSearchConfig.from_env()
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = (
                self._config.api_key
                if self._config.api_key.lower().startswith("api-key ")
                else f"Api-Key {self._config.api_key}"
            )
        return headers

    def search(
        self,
        query: str,
        filters: Dict[str, str],
        *,
        user_token: str = "",
        trace_id: str | None = None,
        intent: str = "",
    ) -> Dict[str, Any]:
        if not self._config.endpoint:
            return {"matches": [], "source": "opensearch", "error": "endpoint_not_configured"}

        terms = []
        for key, value in (filters or {}).items():
            if str(value).strip():
                terms.append({"term": {f"metadata.{key}.keyword": str(value).strip().lower()}})

        payload = {
            "size": 6,
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": ["content^2", "title", "metadata.intent"]}}],
                    "filter": terms,
                }
            },
            "_source": ["title", "content", "metadata", "source"],
        }
        if trace_id:
            payload["ext"] = {"trace_id": trace_id}

        endpoint = f"{self._config.endpoint.rstrip('/')}/{self._config.index_name}/_search"
        try:
            response = self._session.post(
                endpoint,
                json=payload,
                headers=self._headers(),
                timeout=self._config.timeout_seconds,
                verify=self._config.verify_tls,
            )
            response.raise_for_status()
            body = response.json() if response.text else {}
            hits = (((body.get("hits") or {}).get("hits")) or []) if isinstance(body, dict) else []
            matches = []
            for item in hits:
                if not isinstance(item, dict):
                    continue
                source = item.get("_source", {}) if isinstance(item.get("_source"), dict) else {}
                metadata = source.get("metadata", {}) if isinstance(source.get("metadata"), dict) else {}
                chunk = str(source.get("content") or "").strip()
                title = str(source.get("title") or source.get("source") or "").strip()
                if not chunk:
                    continue
                matches.append(
                    {
                        "doc_id": str(item.get("_id") or ""),
                        "score": float(item.get("_score") or 0.0),
                        "citation": title,
                        "chunk": chunk[:600],
                        "doc_type": str(metadata.get("doc_type") or ""),
                        "intent": str(metadata.get("intent") or intent or ""),
                    }
                )
            return {"matches": matches, "filters": filters, "source": "opensearch"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("opensearch_search_failed trace=%s error=%s", trace_id, exc)
            return {"matches": [], "filters": filters, "source": "opensearch", "error": str(exc)}

