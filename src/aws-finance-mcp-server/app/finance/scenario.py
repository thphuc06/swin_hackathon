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
from .data import fetch_transactions_in_window, write_audit_event
from .legacy_tools import build_txn_agg_daily, forecast_cashflow_core, simulate_what_if

TOOL_NAME = "what_if_scenario_v1"


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


def _default_variants() -> List[Dict[str, Any]]:
    return [
        {
            "name": "cut_discretionary_spend_15pct",
            "scenario_overrides": {"spend_delta_pct": -0.15},
        },
        {
            "name": "increase_income_10pct",
            "scenario_overrides": {"income_delta_pct": 0.10},
        },
        {
            "name": "balanced_income_up5_spend_down10",
            "scenario_overrides": {"income_delta_pct": 0.05, "spend_delta_pct": -0.10},
        },
    ]


def what_if_scenario(
    *,
    auth_user_id: str,
    user_id: str,
    horizon_months: int = 12,
    seasonality: bool = True,
    goal: str = "maximize_savings",
    base_scenario_overrides: Dict[str, Any] | None = None,
    variants: List[Dict[str, Any]] | None = None,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    start_dt = as_of_dt - timedelta(days=365)
    horizon = max(1, min(24, int(horizon_months or 12)))
    seasonality_flag = parse_bool(seasonality)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    txn_agg_daily = build_txn_agg_daily(_txn_daily_input(txns))

    base_overrides = dict(base_scenario_overrides or {})
    variant_rows = list(variants or _default_variants())
    base_scenario = {
        "txn_agg_daily": txn_agg_daily,
        "seasonality": seasonality_flag,
        "horizon_months": horizon,
        "scenario_overrides": base_overrides,
    }

    comparison_result = simulate_what_if(
        base_scenario=base_scenario,
        variants=variant_rows,
        goal=goal,
        trace_id=trace,
    )

    base_forecast = forecast_cashflow_core(
        txn_agg_daily=txn_agg_daily,
        seasonality=seasonality_flag,
        scenario_overrides=base_overrides,
        horizon_months=horizon,
        trace_id=trace,
    )
    base_points = base_forecast.get("monthly_forecast") or base_forecast.get("forecast_points") or []
    base_total_net = sum(safe_float(point.get("p50")) for point in base_points)

    tool_input = {
        "user_id": user_id,
        "horizon_months": horizon,
        "seasonality": seasonality_flag,
        "goal": goal,
        "base_scenario_overrides": base_overrides,
        "variants": variant_rows,
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "scenario_comparison": list(comparison_result.get("scenario_comparison") or []),
        "best_variant_by_goal": str(comparison_result.get("best_variant_by_goal") or "base"),
        "base_total_net_p50": round(base_total_net, 2),
        "base_scenario": {
            "horizon_months": horizon,
            "seasonality": seasonality_flag,
            "overrides": base_overrides,
        },
        "variants_used": [str(item.get("name") or "") for item in variant_rows],
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
                "horizon_months": horizon,
                "seasonality": seasonality_flag,
                "variants_count": len(variant_rows),
            },
            "result": {
                "best_variant_by_goal": payload["best_variant_by_goal"],
                "base_total_net_p50": payload["base_total_net_p50"],
            },
        },
    )
    return result
