from __future__ import annotations

import os
from typing import Any, Dict, List, Set

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
        self.root_url = url
        self.base_url = f"{url}/rest/v1" if url else ""
        self.timeout = timeout
        self._configured = bool(url and key)
        self._schema_tables: set[str] | None = None
        self._schema_columns: dict[str, set[str]] | None = None
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
        params: Any = None,
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
        if response.text and ("application/json" in content_type or "+json" in content_type):
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
            params: list[tuple[str, Any]] = [("select", select), ("limit", page_size), ("offset", offset)]
            if order:
                params.append(("order", order))
            for key, value in filters.items():
                field, operator = (key.rsplit("__", 1) + [""])[:2] if "__" in key else (key, "")
                normalized_value = value
                if operator:
                    text_value = str(value)
                    if not text_value.startswith(f"{operator}."):
                        normalized_value = f"{operator}.{text_value}"
                params.append((field, normalized_value))
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

    def upsert_rows(self, table: str, rows: List[Dict[str, Any]], *, on_conflict: str, chunk_size: int = 500) -> None:
        if not rows:
            return
        for index in range(0, len(rows), chunk_size):
            chunk = rows[index:index + chunk_size]
            self._request(
                "POST",
                f"/{table}",
                params={"on_conflict": on_conflict},
                payload=chunk,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )

    def delete_rows(self, table: str, *, filters: Dict[str, str] | None = None) -> None:
        self._request(
            "DELETE",
            f"/{table}",
            params=filters or {},
            headers={"Prefer": "return=minimal"},
        )

    def _load_schema_metadata(self) -> None:
        if self._schema_tables is not None and self._schema_columns is not None:
            return
        spec = self._request(
            "GET",
            "/",
            headers={"Accept": "application/openapi+json"},
        )
        if not isinstance(spec, dict):
            raise SupabaseRestError("Supabase OpenAPI schema response was not a JSON object.")

        paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
        definitions = spec.get("definitions") if isinstance(spec.get("definitions"), dict) else {}

        schema_tables: set[str] = set()
        schema_columns: dict[str, set[str]] = {}
        for path, path_payload in paths.items():
            if not isinstance(path, str) or not path.startswith("/") or path == "/":
                continue
            table_name = path[1:]
            schema_tables.add(table_name)
            columns: set[str] = set()
            get_payload = path_payload.get("get") if isinstance(path_payload, dict) else None
            response_payload = get_payload.get("responses") if isinstance(get_payload, dict) else None
            ok_payload = response_payload.get("200") if isinstance(response_payload, dict) else None
            schema_payload = ok_payload.get("schema") if isinstance(ok_payload, dict) else None
            items_payload = schema_payload.get("items") if isinstance(schema_payload, dict) else None
            ref = items_payload.get("$ref") if isinstance(items_payload, dict) else None
            definition_name = str(ref).split("/")[-1] if isinstance(ref, str) and ref else ""
            definition = definitions.get(definition_name) if definition_name else None
            properties = definition.get("properties") if isinstance(definition, dict) else None
            if isinstance(properties, dict):
                columns = {str(key) for key in properties.keys()}
            schema_columns[table_name] = columns

        self._schema_tables = schema_tables
        self._schema_columns = schema_columns

    def table_exists(self, table: str) -> bool:
        self._load_schema_metadata()
        assert self._schema_tables is not None
        return str(table or "").strip() in self._schema_tables

    def table_columns(self, table: str) -> Set[str]:
        self._load_schema_metadata()
        assert self._schema_columns is not None
        return set(self._schema_columns.get(str(table or "").strip(), set()))


_client: SupabaseRestClient | None = None


def get_supabase_client() -> SupabaseRestClient:
    global _client
    if _client is None:
        timeout = int(os.getenv("SQL_TIMEOUT_SEC", str(DEFAULT_TIMEOUT)))
        _client = SupabaseRestClient(timeout=timeout)
    return _client
