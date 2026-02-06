from __future__ import annotations

import math
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.auth import current_user
from app.services.financial_tools import (
    build_txn_agg_daily,
    compute_runway_and_stress,
    forecast_cashflow_core,
)
from app.services.store import store

router = APIRouter(prefix="/forecast", tags=["forecast"])


class DailyAggPoint(BaseModel):
    day: str
    total_spend: float = 0
    total_income: float = 0


class ForecastScenarioRequest(BaseModel):
    txn_agg_daily: List[DailyAggPoint] | None = None
    seasonality: bool = True
    scenario_overrides: Dict[str, Any] = {}
    horizon_months: int = Field(default=12, ge=1, le=24)
    trace_id: str | None = None


class RunwayRequest(BaseModel):
    forecast: Dict[str, Any]
    cash_buffer: float = 0
    stress_config: Dict[str, Any] = {}
    trace_id: str | None = None


class ForecastResponse(BaseModel):
    forecast_points: List[Dict[str, Any]]
    confidence_band: Dict[str, Any]
    assumptions: List[str]
    trace_id: str
    model_meta: Dict[str, Any]
    monthly_forecast: List[Dict[str, Any]]
    audit: Dict[str, Any]


def _build_user_daily_agg(user_id: str) -> list[Dict[str, Any]]:
    txns = [tx for tx in store.transactions if tx.get("user_id") == user_id]
    if txns:
        return build_txn_agg_daily(txns)
    return [
        {"day": "2026-01-01", "total_spend": 600000, "total_income": 1400000},
        {"day": "2026-01-02", "total_spend": 450000, "total_income": 0},
        {"day": "2026-01-03", "total_spend": 500000, "total_income": 0},
        {"day": "2026-01-04", "total_spend": 700000, "total_income": 2500000},
        {"day": "2026-01-05", "total_spend": 550000, "total_income": 0},
    ]


def _range_to_horizon(range_value: str) -> int:
    value = (range_value or "90d").strip().lower()
    if value.endswith("d"):
        try:
            days = int(value[:-1])
            return max(1, min(24, math.ceil(days / 30)))
        except ValueError:
            return 3
    if value.endswith("m"):
        try:
            months = int(value[:-1])
            return max(1, min(24, months))
        except ValueError:
            return 3
    return 3


@router.get("/cashflow", response_model=ForecastResponse)
def get_cashflow(range: str = "90d", user=Depends(current_user)):
    horizon = _range_to_horizon(range)
    daily = _build_user_daily_agg(user.get("sub"))
    result = forecast_cashflow_core(
        txn_agg_daily=daily,
        horizon_months=horizon,
        seasonality=True,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "forecast_cashflow_core",
        "payload": result.get("audit", {}),
    })
    return result


@router.post("/cashflow/scenario", response_model=ForecastResponse)
def forecast_scenario(payload: ForecastScenarioRequest, user=Depends(current_user)):
    daily = [point.model_dump() for point in payload.txn_agg_daily] if payload.txn_agg_daily else _build_user_daily_agg(user.get("sub"))
    result = forecast_cashflow_core(
        txn_agg_daily=daily,
        seasonality=payload.seasonality,
        scenario_overrides=payload.scenario_overrides,
        horizon_months=payload.horizon_months,
        trace_id=payload.trace_id,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "forecast_cashflow_core",
        "payload": result.get("audit", {}),
    })
    return result


@router.post("/runway")
def forecast_runway(payload: RunwayRequest, user=Depends(current_user)):
    result = compute_runway_and_stress(
        forecast=payload.forecast,
        cash_buffer=payload.cash_buffer,
        stress_config=payload.stress_config,
        trace_id=payload.trace_id,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "compute_runway_and_stress",
        "payload": result.get("audit", {}),
    })
    return result
