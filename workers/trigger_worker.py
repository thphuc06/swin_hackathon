from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

WORKERS_DIR = Path(__file__).resolve().parent
if str(WORKERS_DIR) not in sys.path:
    sys.path.append(str(WORKERS_DIR))

from mcp_client import call_finance_tool  # noqa: E402


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_net_series(forecast: Dict[str, Any]) -> list[float]:
    points = forecast.get("monthly_forecast")
    if not isinstance(points, list):
        points = forecast.get("points", [])
    if not isinstance(points, list):
        return []

    series: list[float] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        if point.get("p50") is not None:
            series.append(_safe_float(point.get("p50"), 0.0))
            continue
        if point.get("net_cashflow") is not None:
            series.append(_safe_float(point.get("net_cashflow"), 0.0))
            continue
        income = _safe_float(point.get("income_estimate"), 0.0)
        spend = _safe_float(point.get("spend_estimate"), 0.0)
        series.append(income - spend)
    return series


def _compute_runway_months(series: Iterable[float], cash_buffer: float) -> tuple[int, list[str]]:
    cash = cash_buffer
    runway_periods = 0
    risk_flags: list[str] = []

    for net in series:
        runway_periods += 1
        cash += _safe_float(net, 0.0)
        if cash < 0:
            risk_flags.append("runway_below_threshold")
            break
    if not risk_flags and cash < cash_buffer * 0.2:
        risk_flags.append("stress_scenario_negative_cash")
    return runway_periods, risk_flags


def handler(event, context=None):  # noqa: ANN001
    print("Trigger worker invoked")
    print(json.dumps(event))

    detail = event.get("detail", {}) if isinstance(event, dict) else {}
    user_id = str(detail.get("user_id") or "demo-user")
    trace_id = str(detail.get("trace_id") or f"trc_wrk_{uuid.uuid4().hex[:8]}")

    forecast = detail.get("forecast")
    errors: list[str] = []
    if not isinstance(forecast, dict) or not forecast:
        horizon_months = max(1, min(24, _safe_int(detail.get("horizon_months"), 12)))
        horizon = "daily_30" if horizon_months == 1 else "weekly_12"
        try:
            forecast = call_finance_tool(
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
            forecast = {"points": [], "trace_id": trace_id}

    net_series = _extract_net_series(forecast if isinstance(forecast, dict) else {})
    runway_months, risk_flags = _compute_runway_months(net_series, _safe_float(detail.get("cash_buffer"), 0.0))

    insight = "Cashflow stable."
    if "runway_below_threshold" in risk_flags:
        insight = "Runway below threshold. Reduce spend or increase buffer."
    elif "stress_scenario_negative_cash" in risk_flags:
        insight = "Stress scenario indicates tightening liquidity. Rebalance your plan."

    return {
        "status": "ok",
        "processed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trace_id": str((forecast or {}).get("trace_id") or trace_id),
        "insight": insight,
        "runway_months": runway_months,
        "risk_flags": risk_flags,
        "errors": errors,
    }


if __name__ == "__main__":
    sample = {
        "detail-type": "DailyAggregateUpdated",
        "detail": {"user_id": "demo-user", "cash_buffer": 3_000_000},
    }
    print(handler(sample))
