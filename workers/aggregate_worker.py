from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

WORKERS_DIR = Path(__file__).resolve().parent
if str(WORKERS_DIR) not in sys.path:
    sys.path.append(str(WORKERS_DIR))

from mcp_client import call_finance_tool  # noqa: E402


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fallback_forecast(horizon: str, trace_id: str) -> Dict[str, Any]:
    points = []
    count = 30 if horizon == "daily_30" else 12
    for idx in range(count):
        points.append(
            {
                "period": f"p{idx + 1}",
                "income_estimate": 0.0,
                "spend_estimate": 0.0,
                "p50": 0.0,
            }
        )
    return {"points": points, "model_meta": {"low_history": True}, "trace_id": trace_id}


def handler(event, context=None):  # noqa: ANN001
    print("Aggregation worker invoked")
    print(json.dumps(event))

    detail = event.get("detail", {}) if isinstance(event, dict) else {}
    user_id = str(detail.get("user_id") or "demo-user")
    trace_id = str(detail.get("trace_id") or f"trc_wrk_{uuid.uuid4().hex[:8]}")
    lookback_months = max(3, min(24, _safe_int(detail.get("lookback_months"), 6)))
    horizon_months = max(1, min(24, _safe_int(detail.get("horizon_months"), 12)))
    horizon = "daily_30" if horizon_months == 1 else "weekly_12"

    recurring_result: Dict[str, Any] = {}
    forecast_result: Dict[str, Any] = {}
    errors: list[str] = []

    try:
        recurring_result = call_finance_tool(
            "recurring_cashflow_detect_v1",
            {
                "user_id": user_id,
                "lookback_months": lookback_months,
                "trace_id": trace_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"recurring_tool_failed:{type(exc).__name__}")
        recurring_result = {
            "trace_id": trace_id,
            "recurring_income": [],
            "recurring_expense": [],
            "fixed_cost_ratio": 0.0,
        }

    try:
        forecast_result = call_finance_tool(
            "cashflow_forecast_v1",
            {
                "user_id": user_id,
                "horizon": horizon,
                "seasonality": bool(detail.get("seasonality", True)),
                "scenario_overrides": detail.get("scenario_overrides", {}) or {},
                "trace_id": trace_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"forecast_tool_failed:{type(exc).__name__}")
        forecast_result = _fallback_forecast(horizon, trace_id)

    monthly_forecast = forecast_result.get("monthly_forecast")
    if not isinstance(monthly_forecast, list):
        monthly_forecast = forecast_result.get("points", [])
        if not isinstance(monthly_forecast, list):
            monthly_forecast = []

    return {
        "status": "ok",
        "processed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trace_id": trace_id,
        "signals": {
            "recurring_income_count": len(recurring_result.get("recurring_income", [])),
            "recurring_expense_count": len(recurring_result.get("recurring_expense", [])),
            "fixed_cost_ratio": recurring_result.get("fixed_cost_ratio", 0.0),
            "forecast_periods": len(monthly_forecast),
            "low_history": bool((forecast_result.get("model_meta") or {}).get("low_history", True)),
        },
        "errors": errors,
    }


if __name__ == "__main__":
    sample = {
        "detail-type": "TransactionCreated",
        "detail": {"user_id": "demo-user", "lookback_months": 6, "horizon_months": 12},
    }
    print(handler(sample))
