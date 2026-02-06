import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from app.services.financial_tools import (  # noqa: E402
    detect_recurring_cashflow,
    forecast_cashflow_core,
    normalize_and_categorize_txn,
)


def handler(event, context=None):
    print("Aggregation worker invoked")
    print(json.dumps(event))
    detail = event.get("detail", {}) if isinstance(event, dict) else {}
    txns = detail.get("transactions", [])
    rules = detail.get("rules_counterparty_map", [])
    horizon = int(detail.get("horizon_months", 12))

    normalize_result = normalize_and_categorize_txn(
        transactions=txns,
        rules_counterparty_map=rules,
    )
    recurring_result = detect_recurring_cashflow(
        normalized_txn=normalize_result.get("normalized_txn", []),
        lookback_months=int(detail.get("lookback_months", 6)),
        trace_id=normalize_result.get("trace_id"),
    )
    daily = detail.get("txn_agg_daily", [])
    forecast_result = forecast_cashflow_core(
        txn_agg_daily=daily,
        seasonality=bool(detail.get("seasonality", True)),
        scenario_overrides=detail.get("scenario_overrides", {}),
        horizon_months=horizon,
        trace_id=normalize_result.get("trace_id"),
    )
    return {
        "status": "ok",
        "processed_at": datetime.utcnow().isoformat() + "Z",
        "trace_id": normalize_result.get("trace_id"),
        "signals": {
            "recurring_income_count": len(recurring_result.get("recurring_income", [])),
            "recurring_expense_count": len(recurring_result.get("recurring_expense", [])),
            "fixed_cost_ratio": recurring_result.get("fixed_cost_ratio", 0),
            "forecast_months": len(forecast_result.get("monthly_forecast", [])),
            "low_history": forecast_result.get("model_meta", {}).get("low_history", True),
        },
    }


if __name__ == "__main__":
    sample = {
        "detail-type": "TransactionCreated",
        "detail": {
            "transactions": [
                {"date": "2026-01-01", "amount": 1200000, "direction": "credit", "counterparty": "Salary"},
                {"date": "2026-01-03", "amount": 450000, "direction": "debit", "counterparty": "Rent"},
            ],
            "txn_agg_daily": [
                {"day": "2026-01-01", "total_spend": 450000, "total_income": 1200000},
            ],
        },
    }
    handler(sample)
