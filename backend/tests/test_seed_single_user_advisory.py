from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts.seed_single_user_advisory import (  # noqa: E402
    _build_entities,
    _build_income_and_salary_transactions,
    _evaluate_checks,
    _month_window,
    _reshape_timestamps,
    _salary_from_debit,
    _select_sparkov_rows,
    SparkovRow,
)


UTC = timezone.utc


def _write_sparkov_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "trans_num",
        "trans_date_trans_time",
        "merchant",
        "category",
        "amt",
        "city",
        "state",
        "is_fraud",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class SingleUserSeederTests(unittest.TestCase):
    def test_select_rows_is_deterministic_and_excludes_fraud(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            train_path = Path(tmpdir) / "fraudTrain.csv"
            test_path = Path(tmpdir) / "fraudTest.csv"
            rows_train: list[dict[str, str]] = []
            rows_test: list[dict[str, str]] = []
            for idx in range(40):
                row = {
                    "trans_num": f"txn_{idx:04d}",
                    "trans_date_trans_time": f"2024-01-{(idx % 28) + 1:02d} 09:15:00",
                    "merchant": f"Merchant {idx % 5}",
                    "category": "grocery_pos",
                    "amt": f"{10 + idx * 0.5:.2f}",
                    "city": "HCM",
                    "state": "VN",
                    "is_fraud": "1" if idx % 13 == 0 else "0",
                }
                if idx < 20:
                    rows_train.append(row)
                else:
                    rows_test.append(row)
            _write_sparkov_csv(train_path, rows_train)
            _write_sparkov_csv(test_path, rows_test)

            selected_a, stats_a = _select_sparkov_rows([train_path, test_path], target_rows=12, seed=2026)
            selected_b, stats_b = _select_sparkov_rows([train_path, test_path], target_rows=12, seed=2026)

            self.assertEqual([row.trans_num for row in selected_a], [row.trans_num for row in selected_b])
            self.assertEqual(stats_a["nonfraud_rows"], stats_b["nonfraud_rows"])
            self.assertTrue(all(row.trans_num not in {"txn_0000", "txn_0013", "txn_0026", "txn_0039"} for row in selected_a))

    def test_month_window_and_remap_keep_rows_in_range(self) -> None:
        now_utc = datetime(2026, 2, 7, 12, 0, 0, tzinfo=UTC)
        start, end, _ = _month_window(12, now_utc)
        rows = [
            SparkovRow("a", datetime(2019, 1, 1, 10, 0, tzinfo=UTC), Decimal("1.0"), "M1", "travel", "A", "B"),
            SparkovRow("b", datetime(2020, 1, 1, 10, 0, tzinfo=UTC), Decimal("2.0"), "M2", "home", "A", "B"),
            SparkovRow("c", datetime(2021, 1, 1, 10, 0, tzinfo=UTC), Decimal("3.0"), "M3", "home", "A", "B"),
        ]
        remapped = _reshape_timestamps(rows, start, end)
        self.assertEqual(len(remapped), 3)
        for _, mapped_ts in remapped:
            self.assertGreaterEqual(mapped_ts, start)
            self.assertLessEqual(mapped_ts, end)
        self.assertLessEqual(remapped[0][1], remapped[-1][1])

    def test_salary_and_income_events_use_month_count(self) -> None:
        now_utc = datetime(2026, 2, 7, 12, 0, 0, tzinfo=UTC)
        _, _, month_starts = _month_window(12, now_utc)
        debit_rows = []
        for idx, month_start in enumerate(month_starts):
            debit_rows.append(
                {
                    "occurred_at": month_start.replace(day=12, hour=12, minute=0, second=0).isoformat().replace("+00:00", "Z"),
                    "amount": 10_000_000 + idx * 500_000,
                }
            )
        salary_amount, multiplier = _salary_from_debit(debit_rows, month_starts)
        self.assertGreaterEqual(salary_amount, 8_000_000)
        self.assertGreaterEqual(multiplier, 0.75)
        self.assertLessEqual(multiplier, 1.25)

        mapping = {
            "category_to_bucket": {"travel": {"jar": "Goals", "category": "Travel", "channel": "card_online"}},
            "fallback": {"jar": "Misc", "category": "Other", "channel": "other"},
        }
        _, _, jar_name_to_id, category_name_to_id = _build_entities(
            seed_user_id="user_demo",
            now_utc=now_utc,
            category_mapping=mapping,
        )
        source_rows, income_event_rows, salary_tx_rows = _build_income_and_salary_transactions(
            seed_user_id="user_demo",
            currency="VND",
            month_starts=month_starts,
            salary_amount=salary_amount,
            jar_name_to_id=jar_name_to_id,
            category_name_to_id=category_name_to_id,
            now_utc=now_utc,
        )
        self.assertEqual(len(source_rows), 1)
        self.assertEqual(len(income_event_rows), 12)
        self.assertEqual(len(salary_tx_rows), 12)
        for event in income_event_rows:
            dt = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
            self.assertEqual(dt.day, 5)
            self.assertEqual(dt.hour, 9)

    def test_evaluate_checks_passes_with_valid_payload(self) -> None:
        now_utc = datetime(2026, 2, 7, 12, 0, 0, tzinfo=UTC)
        tx_rows = []
        for month in range(1, 13):
            debit_dt = datetime(2025 if month <= 11 else 2026, month if month <= 11 else 1, 12, 9, 0, tzinfo=UTC)
            credit_dt = datetime(2025 if month <= 11 else 2026, month if month <= 11 else 1, 5, 9, 0, tzinfo=UTC)
            tx_rows.append(
                {
                    "id": f"d_{month}",
                    "user_id": "user_demo",
                    "jar_id": "jar_1",
                    "category_id": "cat_1",
                    "amount": 900_000 + month * 80_000,
                    "counterparty": "Shop",
                    "raw_narrative": "POS Shop",
                    "direction": "debit",
                    "occurred_at": debit_dt.isoformat().replace("+00:00", "Z"),
                }
            )
            tx_rows.append(
                {
                    "id": f"c_{month}",
                    "user_id": "user_demo",
                    "jar_id": "jar_1",
                    "category_id": "cat_1",
                    "amount": 1_200_000,
                    "counterparty": "Payroll Employer",
                    "raw_narrative": "SALARY CREDIT",
                    "direction": "credit",
                    "occurred_at": credit_dt.isoformat().replace("+00:00", "Z"),
                }
            )

        validation = _evaluate_checks(
            transactions=tx_rows,
            jar_ids={"jar_1"},
            category_ids={"cat_1"},
            seed_user_id="user_demo",
            months=12,
            expected_debit_rows=12,
            expected_credit_rows=12,
        )
        self.assertTrue(validation["summary"]["all_pass"])


if __name__ == "__main__":
    unittest.main()
