from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

DEFAULT_TIMEOUT = 20


class SupabaseRestError(RuntimeError):
    pass


class SupabaseRestClient:
    def __init__(
        self,
        *,
        supabase_url: str | None = None,
        service_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        url = (supabase_url or os.getenv("SUPABASE_URL", "")).strip().rstrip("/")
        key = (service_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
        self.base_url = f"{url}/rest/v1" if url else ""
        self.timeout = timeout
        self._configured = bool(url and key)
        self.common_headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    @property
    def configured(self) -> bool:
        return self._configured

    def _ensure_configured(self) -> None:
        if not self.configured:
            raise SupabaseRestError(
                "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        payload: Any = None,
        headers: Dict[str, str] | None = None,
    ) -> Any:
        self._ensure_configured()
        merged_headers = dict(self.common_headers)
        if headers:
            merged_headers.update(headers)
        response = requests.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=payload,
            headers=merged_headers,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            snippet = response.text[:1200]
            raise SupabaseRestError(f"Supabase {method} {path} failed ({response.status_code}): {snippet}")
        content_type = response.headers.get("content-type", "")
        if response.text and "application/json" in content_type:
            return response.json()
        return None

    def fetch_rows(
        self,
        table: str,
        *,
        select: str = "*",
        filters: Dict[str, str] | None = None,
        order: str | None = None,
        page_size: int = 1000,
    ) -> List[Dict[str, Any]]:
        filters = filters or {}
        rows: list[Dict[str, Any]] = []
        offset = 0
        while True:
            params: Dict[str, Any] = {"select": select, "limit": page_size, "offset": offset}
            if order:
                params["order"] = order
            params.update(filters)
            page = self._request("GET", f"/{table}", params=params)
            if not isinstance(page, list):
                raise SupabaseRestError(f"Unexpected response type for table {table}")
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return rows

    def insert_rows(self, table: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        self._request(
            "POST",
            f"/{table}",
            payload=rows,
            headers={"Prefer": "return=minimal"},
        )


_client: SupabaseRestClient | None = None


def get_supabase_client() -> SupabaseRestClient:
    global _client
    if _client is None:
        timeout = int(os.getenv("SQL_TIMEOUT_SEC", str(DEFAULT_TIMEOUT)))
        _client = SupabaseRestClient(timeout=timeout)
    return _client
