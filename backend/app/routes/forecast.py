from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.auth import current_user
from app.services.finance import cashflow_forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])


class ForecastScenarioRequest(BaseModel):
    horizon: str = Field(default="weekly_12", pattern=r"^(daily_30|weekly_12)$")
    scenario_overrides: Dict[str, Any] = {}
    as_of: str | None = None
    trace_id: str | None = None


class RunwayRequest(BaseModel):
    forecast: Dict[str, Any]
    cash_buffer: float = 0
    runway_threshold_days: int = 90
    trace_id: str | None = None


def _estimate_runway_days(forecast_payload: Dict[str, Any], cash_buffer: float) -> float:
    points = forecast_payload.get("points") or []
    balance = cash_buffer
    periods = 0
    for point in points:
        periods += 1
        balance += float(point.get("p50") or 0.0)
        if balance < 0:
            break
    if not points:
        return 0.0
    first_period = str(points[0].get("period") or "")
    is_weekly = "W" in first_period
    period_days = 7 if is_weekly else 1
    return periods * period_days


@router.get("/cashflow")
def get_cashflow(range: str = "90d", user=Depends(current_user)):
    horizon = "daily_30" if range == "30d" else "weekly_12"
    return cashflow_forecast(
        auth_user_id=user.get("sub", ""),
        user_id=user.get("sub", ""),
        horizon=horizon,
    )


@router.post("/cashflow/scenario")
def forecast_scenario(payload: ForecastScenarioRequest, user=Depends(current_user)):
    return cashflow_forecast(
        auth_user_id=user.get("sub", ""),
        user_id=user.get("sub", ""),
        horizon=payload.horizon,
        scenario_overrides=payload.scenario_overrides,
        as_of=payload.as_of,
        trace_id=payload.trace_id,
    )


@router.post("/runway")
def forecast_runway(payload: RunwayRequest, user=Depends(current_user)):
    runway_days = _estimate_runway_days(payload.forecast, payload.cash_buffer)
    threshold = max(1, int(payload.runway_threshold_days))
    flags = []
    if runway_days < threshold:
        flags.append("runway_below_threshold")
    return {
        "trace_id": payload.trace_id,
        "runway_days": round(runway_days, 2),
        "risk_flags": flags,
        "disclaimer": "Educational guidance only. We do not provide investment advice.",
    }
