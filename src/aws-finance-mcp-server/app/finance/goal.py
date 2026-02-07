from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from app.supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    ensure_user_scope,
    iso_utc,
    new_trace_id,
    now_utc,
    parse_bool,
    parse_datetime,
    safe_float,
)
from .data import fetch_goals, fetch_transactions_in_window, write_audit_event
from .legacy_tools import build_txn_agg_daily, evaluate_savings_goal, forecast_cashflow_core

TOOL_NAME = "goal_feasibility_v1"


def _txn_daily_input(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for row in rows:
        occurred = parse_datetime(row.get("occurred_at"))
        if not occurred:
            continue
        payload.append(
            {
                "day": occurred.date().isoformat(),
                "amount": safe_float(row.get("amount")),
                "direction": str(row.get("direction") or "debit").lower(),
            }
        )
    return payload


def _resolve_goal_target(
    *,
    goals: List[Dict[str, Any]],
    goal_id: str | None,
    target_amount: float | None,
    horizon_months: int | None,
) -> Dict[str, Any]:
    if target_amount is not None and safe_float(target_amount) > 0:
        return {
            "target_amount": safe_float(target_amount),
            "horizon_months": max(1, int(safe_float(horizon_months, 12))),
            "goal_id": goal_id,
            "goal_name": "input_target",
            "source": "input",
        }

    chosen = None
    if goal_id:
        for goal in goals:
            if str(goal.get("id") or "") == goal_id:
                chosen = goal
                break
    if chosen is None:
        for goal in goals:
            if safe_float(goal.get("target_amount")) > 0:
                chosen = goal
                break

    if chosen is None:
        raise ValueError("Missing target_amount and no goal found in DB for fallback.")

    return {
        "target_amount": safe_float(chosen.get("target_amount")),
        "horizon_months": max(1, int(safe_float(horizon_months, chosen.get("horizon_months") or 12))),
        "goal_id": str(chosen.get("id") or ""),
        "goal_name": str(chosen.get("name") or "goal"),
        "source": "db_fallback",
    }


def goal_feasibility(
    *,
    auth_user_id: str,
    user_id: str,
    target_amount: float | None = None,
    horizon_months: int | None = None,
    goal_id: str | None = None,
    seasonality: bool = True,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    start_dt = as_of_dt - timedelta(days=365)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    goals = fetch_goals(sql, user_id)

    resolved = _resolve_goal_target(
        goals=goals,
        goal_id=goal_id,
        target_amount=target_amount,
        horizon_months=horizon_months,
    )

    txn_agg_daily = build_txn_agg_daily(_txn_daily_input(txns))
    forecast = forecast_cashflow_core(
        txn_agg_daily=txn_agg_daily,
        seasonality=parse_bool(seasonality),
        scenario_overrides={},
        horizon_months=int(resolved["horizon_months"]),
        trace_id=trace,
    )
    evaluation = evaluate_savings_goal(
        target_amount=float(resolved["target_amount"]),
        horizon_months=int(resolved["horizon_months"]),
        forecast=forecast,
        trace_id=trace,
    )

    points = forecast.get("monthly_forecast") or forecast.get("forecast_points") or []
    base_total_net = sum(safe_float(point.get("p50")) for point in points)

    tool_input = {
        "user_id": user_id,
        "target_amount": resolved["target_amount"],
        "horizon_months": resolved["horizon_months"],
        "goal_id": resolved["goal_id"],
        "seasonality": parse_bool(seasonality),
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "goal_source": resolved["source"],
        "goal_id": resolved["goal_id"] or None,
        "goal_name": resolved["goal_name"],
        "target_amount": round(safe_float(resolved["target_amount"]), 2),
        "horizon_months": int(resolved["horizon_months"]),
        "required_monthly_saving": round(safe_float(evaluation.get("required_monthly_saving")), 2),
        "feasible": bool(evaluation.get("feasible")),
        "gap_amount": round(safe_float(evaluation.get("gap_amount")), 2),
        "grade": str(evaluation.get("grade") or "C"),
        "reasons": list(evaluation.get("reasons") or []),
        "metrics": dict(evaluation.get("metrics") or {}),
        "forecast_summary": {
            "base_total_net_p50": round(base_total_net, 2),
            "history_days": len(txn_agg_daily),
            "forecast_points": len(points),
        },
    }

    result = build_output(
        tool_name=TOOL_NAME,
        tool_input=tool_input,
        payload=payload,
        trace_id=trace,
        started_at=started_at,
        sql_snapshot_ts=iso_utc(),
    )
    write_audit_event(
        sql,
        user_id=user_id,
        trace_id=trace,
        event_type=TOOL_NAME,
        payload={
            "params": {
                "goal_id": resolved["goal_id"],
                "target_amount": resolved["target_amount"],
                "horizon_months": resolved["horizon_months"],
            },
            "result": {
                "feasible": bool(evaluation.get("feasible")),
                "gap_amount": round(safe_float(evaluation.get("gap_amount")), 2),
            },
        },
    )
    return result
