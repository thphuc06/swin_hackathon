import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from app.services.financial_tools import (  # noqa: E402
    compute_runway_and_stress,
    forecast_cashflow_core,
)


def handler(event, context=None):
    print("Trigger worker invoked")
    print(json.dumps(event))
    detail = event.get("detail", {}) if isinstance(event, dict) else {}
    forecast = detail.get("forecast")
    if not forecast:
        forecast = forecast_cashflow_core(
            txn_agg_daily=detail.get("txn_agg_daily", []),
            seasonality=bool(detail.get("seasonality", True)),
            scenario_overrides=detail.get("scenario_overrides", {}),
            horizon_months=int(detail.get("horizon_months", 12)),
        )
    runway = compute_runway_and_stress(
        forecast=forecast,
        cash_buffer=float(detail.get("cash_buffer", 0)),
        stress_config=detail.get("stress_config", {}),
        trace_id=forecast.get("trace_id"),
    )
    risk_flags = runway.get("risk_flags", [])
    insight = "Cashflow stable."
    if "runway_below_threshold" in risk_flags:
        insight = "Runway below threshold. Reduce spend or increase buffer."
    elif "stress_scenario_negative_cash" in risk_flags:
        insight = "Stress scenario triggers negative cash. Rebalance plan."
    return {
        "status": "ok",
        "processed_at": datetime.utcnow().isoformat() + "Z",
        "trace_id": runway.get("trace_id"),
        "insight": insight,
        "runway_months": runway.get("runway_months"),
        "risk_flags": risk_flags,
    }


if __name__ == "__main__":
    sample = {
        "detail-type": "DailyAggregateUpdated",
        "detail": {
            "txn_agg_daily": [
                {"day": "2026-01-01", "total_spend": 1200000, "total_income": 1000000},
                {"day": "2026-01-02", "total_spend": 1100000, "total_income": 0},
            ],
            "cash_buffer": 3000000,
        },
    }
    handler(sample)
