from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, status_code: int, payload, content_type: str = "application/json") -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {"content-type": content_type}
        self.text = "" if payload is None else str(payload)

    def json(self):
        return self._payload


class SupabaseRestContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module(
            "test_specialist_supabase_rest",
            "src/aws-specialist-agent-mcp-server/planner_agent/finance/supabase_rest.py",
        )

    def test_table_metadata_is_loaded_from_openapi(self) -> None:
        openapi = {
            "paths": {
                "/transactions": {
                    "get": {
                        "responses": {
                            "200": {
                                "schema": {
                                    "items": {"$ref": "#/definitions/transactions"}
                                }
                            }
                        }
                    }
                }
            },
            "definitions": {
                "transactions": {
                    "properties": {
                        "id": {},
                        "user_id": {},
                        "occurred_at": {},
                    }
                }
            },
        }

        with patch.object(
            self.module.requests,
            "request",
            return_value=_FakeResponse(200, openapi, "application/openapi+json"),
        ):
            client = self.module.SupabaseRestClient(
                supabase_url="https://example.supabase.co",
                service_key="secret",
            )
            self.assertTrue(client.table_exists("transactions"))
            self.assertFalse(client.table_exists("audit_event_log"))
            self.assertEqual({"id", "user_id", "occurred_at"}, client.table_columns("transactions"))

    def test_fetch_rows_supports_duplicate_field_filters_via_suffix_operators(self) -> None:
        captured = {}

        def _fake_request(method, url, params=None, json=None, headers=None, timeout=None):
            captured["method"] = method
            captured["url"] = url
            captured["params"] = list(params or [])
            return _FakeResponse(200, [])

        with patch.object(self.module.requests, "request", side_effect=_fake_request):
            client = self.module.SupabaseRestClient(
                supabase_url="https://example.supabase.co",
                service_key="secret",
            )
            client.fetch_rows(
                "transactions",
                filters={
                    "user_id": "eq.user-123",
                    "occurred_at__gte": "2025-01-01T00:00:00Z",
                    "occurred_at__lte": "2025-01-31T23:59:59Z",
                },
            )

        self.assertEqual("GET", captured["method"])
        self.assertIn(("user_id", "eq.user-123"), captured["params"])
        self.assertIn(("occurred_at", "gte.2025-01-01T00:00:00Z"), captured["params"])
        self.assertIn(("occurred_at", "lte.2025-01-31T23:59:59Z"), captured["params"])

    def test_upsert_and_delete_rows_use_postgrest_contract(self) -> None:
        calls = []

        def _fake_request(method, url, params=None, json=None, headers=None, timeout=None):
            calls.append((method, url, params, headers, json))
            return _FakeResponse(200, None, "application/json")

        with patch.object(self.module.requests, "request", side_effect=_fake_request):
            client = self.module.SupabaseRestClient(
                supabase_url="https://example.supabase.co",
                service_key="secret",
            )
            client.upsert_rows("transactions", [{"id": "txn-1"}], on_conflict="id")
            client.delete_rows("transactions", filters={"user_id": "eq.user-123"})

        self.assertEqual("POST", calls[0][0])
        self.assertEqual({"on_conflict": "id"}, calls[0][2])
        self.assertIn("resolution=merge-duplicates", calls[0][3]["Prefer"])
        self.assertEqual("DELETE", calls[1][0])
        self.assertEqual({"user_id": "eq.user-123"}, calls[1][2])


if __name__ == "__main__":
    unittest.main()
