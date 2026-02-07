from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.auth import current_user
from app.services.finance import (
    cashflow_forecast,
    evaluate_house_affordability,
    evaluate_investment_capacity,
    evaluate_savings_goal,
    simulate_what_if,
)
from app.services.store import store

router = APIRouter(prefix="/decision", tags=["decision"])


class DecisionResponse(BaseModel):
    metrics: Dict[str, Any]
    grade: str
    reasons: List[str]
    guardrails: List[str]
    trace_id: str
    audit: Dict[str, Any]


class SavingsGoalRequest(BaseModel):
    target_amount: float = Field(gt=0)
    horizon_months: int = Field(gt=0, le=360)
    forecast: Dict[str, Any] | None = None
    trace_id: str | None = None


class HouseAffordabilityRequest(BaseModel):
    house_price: float = Field(gt=0)
    down_payment: float = Field(ge=0)
    interest_rate: float = Field(ge=0)
    loan_years: int = Field(gt=0, le=40)
    fees: float | Dict[str, Any] = 0
    monthly_income: float = Field(default=0, ge=0)
    existing_debt_payment: float = Field(default=0, ge=0)
    cash_buffer: float = Field(default=0, ge=0)
    forecast: Dict[str, Any] | None = None
    trace_id: str | None = None


class InvestmentCapacityRequest(BaseModel):
    risk_profile: str = "balanced"
    emergency_target: float = Field(default=0, ge=0)
    cash_buffer: float = Field(default=0, ge=0)
    forecast: Dict[str, Any] | None = None
    trace_id: str | None = None


class WhatIfRequest(BaseModel):
    base_scenario: Dict[str, Any]
    variants: List[Dict[str, Any]] = []
    goal: str | None = None
    trace_id: str | None = None


def _default_forecast(user_id: str, trace_id: str | None = None) -> Dict[str, Any]:
    forecast = cashflow_forecast(
        auth_user_id=user_id,
        user_id=user_id,
        horizon="weekly_12",
        trace_id=trace_id,
    )
    weekly_points = forecast.get("points", [])
    monthly_points = []
    for idx, point in enumerate(weekly_points[:12]):
        monthly_points.append(
            {
                "month": f"m{idx+1}",
                "income_estimate": point.get("income_estimate", 0),
                "spend_estimate": point.get("spend_estimate", 0),
                "p10": point.get("p10", 0),
                "p50": point.get("p50", 0),
                "p90": point.get("p90", 0),
            }
        )
    return {"monthly_forecast": monthly_points, "trace_id": forecast.get("trace_id")}


@router.post("/savings-goal", response_model=DecisionResponse)
def decision_savings_goal(payload: SavingsGoalRequest, user=Depends(current_user)):
    forecast = payload.forecast or _default_forecast(user.get("sub"), payload.trace_id)
    result = evaluate_savings_goal(
        target_amount=payload.target_amount,
        horizon_months=payload.horizon_months,
        forecast=forecast,
        trace_id=payload.trace_id,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "evaluate_savings_goal",
        "payload": result.get("audit", {}),
    })
    return result


@router.post("/house-affordability", response_model=DecisionResponse)
def decision_house(payload: HouseAffordabilityRequest, user=Depends(current_user)):
    forecast = payload.forecast or _default_forecast(user.get("sub"), payload.trace_id)
    derived_income = payload.monthly_income
    if not derived_income:
        points = forecast.get("monthly_forecast") or []
        if points:
            derived_income = sum(point.get("income_estimate", 0) for point in points[:3]) / min(3, len(points))
    result = evaluate_house_affordability(
        house_price=payload.house_price,
        down_payment=payload.down_payment,
        interest_rate=payload.interest_rate,
        loan_years=payload.loan_years,
        fees=payload.fees,
        monthly_income=derived_income,
        existing_debt_payment=payload.existing_debt_payment,
        cash_buffer=payload.cash_buffer,
        trace_id=payload.trace_id,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "evaluate_house_affordability",
        "payload": result.get("audit", {}),
    })
    return result


@router.post("/investment-capacity", response_model=DecisionResponse)
def decision_investment(payload: InvestmentCapacityRequest, user=Depends(current_user)):
    forecast = payload.forecast or _default_forecast(user.get("sub"), payload.trace_id)
    result = evaluate_investment_capacity(
        risk_profile=payload.risk_profile,
        emergency_target=payload.emergency_target,
        forecast=forecast,
        cash_buffer=payload.cash_buffer,
        trace_id=payload.trace_id,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "evaluate_investment_capacity",
        "payload": result.get("audit", {}),
    })
    return result


@router.post("/what-if")
def decision_what_if(payload: WhatIfRequest, user=Depends(current_user)):
    base_scenario = dict(payload.base_scenario)
    base_scenario.setdefault("txn_agg_daily", [])
    result = simulate_what_if(
        base_scenario=base_scenario,
        variants=payload.variants,
        goal=payload.goal,
        trace_id=payload.trace_id,
    )
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": result.get("trace_id"),
        "tool_name": "simulate_what_if",
        "payload": result.get("audit", {}),
    })
    return result
