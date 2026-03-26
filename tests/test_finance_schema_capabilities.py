from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src/aws-specialist-agent-mcp-server"))

from planner_agent.finance import data as finance_data  # noqa: E402


UTC = timezone.utc


class _FakeClient:
    def __init__(self, *, existing_tables=None, columns=None) -> None:
        self.existing_tables = set(existing_tables or [])
        self.columns = columns or {}
        self.fetch_calls = []
        self.insert_calls = []

    def table_exists(self, table: str) -> bool:
        return table in self.existing_tables

    def table_columns(self, table: str):
        return set(self.columns.get(table, set()))

    def fetch_rows(self, table: str, **kwargs):
        self.fetch_calls.append((table, kwargs))
        return []

    def insert_rows(self, table: str, rows):
        self.insert_calls.append((table, rows))


class FinanceSchemaCapabilityTests(unittest.TestCase):
    def test_fetch_transactions_pushes_time_window_into_db_filters(self) -> None:
        client = _FakeClient(
            columns={
                "transactions": {
                    "id",
                    "user_id",
                    "jar_id",
                    "category_id",
                    "amount",
                    "currency",
                    "counterparty",
                    "raw_narrative",
                    "user_note",
                    "channel",
                    "occurred_at",
                    "created_at",
                    "direction",
                }
            }
        )
        start_at = datetime(2025, 1, 1, tzinfo=UTC)
        end_at = datetime(2025, 1, 31, 23, 59, 59, tzinfo=UTC)

        finance_data.fetch_transactions_in_window(
            client,
            user_id="user-123",
            start_at=start_at,
            end_at=end_at,
        )

        table, kwargs = client.fetch_calls[0]
        self.assertEqual("transactions", table)
        self.assertEqual("eq.user-123", kwargs["filters"]["user_id"])
        self.assertEqual("2025-01-01T00:00:00Z", kwargs["filters"]["occurred_at__gte"])
        self.assertEqual("2025-01-31T23:59:59Z", kwargs["filters"]["occurred_at__lte"])

    def test_missing_audit_tables_are_treated_as_optional_capabilities(self) -> None:
        client = _FakeClient(existing_tables=set())
        start_at = datetime(2025, 1, 1, tzinfo=UTC)
        end_at = datetime(2025, 1, 31, tzinfo=UTC)

        rows = finance_data.fetch_audit_events(
            client,
            user_id="user-123",
            start_at=start_at,
            end_at=end_at,
        )
        finance_data.write_audit_event(
            client,
            user_id="user-123",
            trace_id="trc_123",
            event_type="spend_analytics_v1",
            payload={"ok": True},
        )
        finance_data.write_decision_event(
            client,
            user_id="user-123",
            trace_id="trc_123",
            decision_type="suitability_guard_v1",
            decision="allow",
            payload={"ok": True},
        )

        self.assertEqual([], rows)
        self.assertEqual([], client.fetch_calls)
        self.assertEqual([], client.insert_calls)


if __name__ == "__main__":
    unittest.main()
