from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.services.finance import (
    compute_runway_and_stress,
    evaluate_house_affordability,
    evaluate_investment_capacity,
    evaluate_savings_goal,
    forecast_cashflow_core,
    ingest_statement_vn,
)


class FinancialToolsTests(unittest.TestCase):
    def test_ingest_statement_missing_columns_returns_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "statement.csv"
            csv_path.write_text("date,counterparty\n2026-01-01,Landlord\n", encoding="utf-8")
            result = ingest_statement_vn(file_ref=str(csv_path))
            self.assertIn("parse_warnings", result)
            self.assertIn("missing_amount_column", result["parse_warnings"])
            self.assertEqual(result["transactions"], [])

    def test_forecast_has_p10_p50_p90_and_low_history(self) -> None:
        daily = [{"day": "2026-01-01", "total_spend": 500_000, "total_income": 1_000_000}]
        result = forecast_cashflow_core(txn_agg_daily=daily, horizon_months=3)
        self.assertTrue(result["model_meta"]["low_history"])
        self.assertEqual(len(result["forecast_points"]), 3)
        for point in result["forecast_points"]:
            self.assertIn("p10", point)
            self.assertIn("p50", point)
            self.assertIn("p90", point)

    def test_runway_flags_when_threshold_breached(self) -> None:
        forecast = {
            "monthly_forecast": [
                {"month": "2026-01", "income_estimate": 1_000_000, "spend_estimate": 2_000_000, "p50": -1_000_000},
                {"month": "2026-02", "income_estimate": 1_000_000, "spend_estimate": 2_000_000, "p50": -1_000_000},
            ]
        }
        result = compute_runway_and_stress(
            forecast=forecast,
            cash_buffer=500_000,
            stress_config={"runway_threshold_months": 6},
        )
        self.assertIn("runway_below_threshold", result["risk_flags"])

    def test_house_affordability_returns_metrics(self) -> None:
        result = evaluate_house_affordability(
            house_price=3_000_000_000,
            down_payment=900_000_000,
            interest_rate=10.0,
            loan_years=20,
            fees=60_000_000,
            monthly_income=45_000_000,
            existing_debt_payment=5_000_000,
            cash_buffer=200_000_000,
        )
        self.assertIn("monthly_payment", result["metrics"])
        self.assertIn("DTI", result["metrics"])
        self.assertIn("safe_price_range", result["metrics"])

    def test_investment_capacity_is_education_only(self) -> None:
        forecast = forecast_cashflow_core(
            txn_agg_daily=[
                {"day": "2026-01-01", "total_spend": 500_000, "total_income": 2_000_000},
                {"day": "2026-01-02", "total_spend": 400_000, "total_income": 0},
                {"day": "2026-01-03", "total_spend": 300_000, "total_income": 0},
            ],
            horizon_months=6,
        )
        result = evaluate_investment_capacity(
            risk_profile="balanced",
            emergency_target=20_000_000,
            forecast=forecast,
            cash_buffer=30_000_000,
        )
        self.assertTrue(result["education_only"])
        self.assertIn("education_only=true", result["guardrail_notes"])

    def test_savings_goal_feasibility(self) -> None:
        forecast = {
            "monthly_forecast": [
                {"p50": 30_000_000},
                {"p50": 30_000_000},
                {"p50": 30_000_000},
            ]
        }
        result = evaluate_savings_goal(
            target_amount=60_000_000,
            horizon_months=3,
            forecast=forecast,
        )
        self.assertTrue(result["feasible"])
        self.assertEqual(result["gap_amount"], 0)


if __name__ == "__main__":
    unittest.main()
