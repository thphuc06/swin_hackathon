from __future__ import annotations

import os
import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List

from app.services.supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    daterange_start,
    ensure_user_scope,
    iso_utc,
    new_trace_id,
    now_utc,
    parse_datetime,
    safe_float,
)
from .data import fetch_transactions_in_window, write_audit_event
from .oss_adapters import darts_forecast_points

TOOL_NAME = "cashflow_forecast_v1"
MODEL_NAME = "deterministic_weekday_baseline_v1"


def _build_daily_series(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    daily: Dict[str, Dict[str, float]] = defaultdict(lambda: {"income": 0.0, "spend": 0.0})
    for row in rows:
        occurred = parse_datetime(row.get("occurred_at"))
        if not occurred:
            continue
        day_key = occurred.date().isoformat()
        amount = safe_float(row.get("amount"))
        direction = str(row.get("direction") or "debit").lower()
        if direction == "credit":
            daily[day_key]["income"] += amount
        else:
            daily[day_key]["spend"] += amount
    return daily


def _parse_overrides(payload: Dict[str, Any] | None) -> Dict[str, float]:
    raw = payload or {}
    return {
        "income_delta_pct": safe_float(raw.get("income_delta_pct")),
        "spend_delta_pct": safe_float(raw.get("spend_delta_pct")),
        "income_delta_abs": safe_float(raw.get("income_delta_abs")),
        "spend_delta_abs": safe_float(raw.get("spend_delta_abs")),
    }


def cashflow_forecast(
    *,
    auth_user_id: str,
    user_id: str,
    horizon: str = "weekly_12",
    scenario_overrides: Dict[str, Any] | None = None,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    history_start = daterange_start(as_of_dt, 180)
    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=history_start, end_at=as_of_dt)
    daily = _build_daily_series(txns)
    day_keys = sorted(daily.keys())

    weekday_income: Dict[int, List[float]] = defaultdict(list)
    weekday_spend: Dict[int, List[float]] = defaultdict(list)
    net_history: List[float] = []
    net_aligned: List[float] = []
    aligned_day_keys: List[str] = []
    for day_key in day_keys:
        dt = parse_datetime(day_key)
        if not dt:
            continue
        income = daily[day_key]["income"]
        spend = daily[day_key]["spend"]
        weekday = dt.weekday()
        weekday_income[weekday].append(income)
        weekday_spend[weekday].append(spend)
        net = income - spend
        net_history.append(net)
        net_aligned.append(net)
        aligned_day_keys.append(day_key)

    base_income = {idx: (statistics.fmean(vals) if vals else 0.0) for idx, vals in weekday_income.items()}
    base_spend = {idx: (statistics.fmean(vals) if vals else 0.0) for idx, vals in weekday_spend.items()}
    for idx in range(7):
        base_income.setdefault(idx, statistics.fmean(net_history) if net_history else 0.0)
        base_spend.setdefault(idx, 0.0)

    net_std = statistics.pstdev(net_history) if len(net_history) > 1 else max(500_000.0, abs(net_history[0]) * 0.2 if net_history else 1_000_000.0)
    overrides = _parse_overrides(scenario_overrides)

    points = []
    if horizon == "daily_30":
        horizon_days = 30
        for step in range(1, horizon_days + 1):
            point_dt = (as_of_dt + timedelta(days=step)).replace(hour=0, minute=0, second=0, microsecond=0)
            weekday = point_dt.weekday()
            income_est = max(0.0, base_income[weekday] * (1 + overrides["income_delta_pct"]) + overrides["income_delta_abs"])
            spend_est = max(0.0, base_spend[weekday] * (1 + overrides["spend_delta_pct"]) + overrides["spend_delta_abs"])
            p50 = income_est - spend_est
            band = max(300_000.0, net_std * 1.28)
            points.append(
                {
                    "period": point_dt.date().isoformat(),
                    "income_estimate": round(income_est, 2),
                    "spend_estimate": round(spend_est, 2),
                    "p10": round(p50 - band, 2),
                    "p50": round(p50, 2),
                    "p90": round(p50 + band, 2),
                }
            )
        granularity = "daily"
    else:
        horizon_weeks = 12
        weekly_income_base = statistics.fmean(base_income.values()) * 7 if base_income else 0.0
        weekly_spend_base = statistics.fmean(base_spend.values()) * 7 if base_spend else 0.0
        band = max(800_000.0, net_std * 2.56)
        for step in range(1, horizon_weeks + 1):
            point_dt = (as_of_dt + timedelta(days=step * 7)).replace(hour=0, minute=0, second=0, microsecond=0)
            income_est = max(0.0, weekly_income_base * (1 + overrides["income_delta_pct"]) + overrides["income_delta_abs"] * 7)
            spend_est = max(0.0, weekly_spend_base * (1 + overrides["spend_delta_pct"]) + overrides["spend_delta_abs"] * 7)
            p50 = income_est - spend_est
            points.append(
                {
                    "period": f"{point_dt.year}-W{point_dt.isocalendar().week:02d}",
                    "income_estimate": round(income_est, 2),
                    "spend_estimate": round(spend_est, 2),
                    "p10": round(p50 - band, 2),
                    "p50": round(p50, 2),
                    "p90": round(p50 + band, 2),
                }
            )
        granularity = "weekly"

    use_darts = os.getenv("USE_DARTS_FORECAST", "true").strip().lower() in {"1", "true", "yes", "on"}
    darts_result = {"available": False, "engine": "darts_exponential_smoothing"}
    active_model = MODEL_NAME
    if use_darts:
        darts_result = darts_forecast_points(aligned_day_keys, net_aligned, horizon=horizon)
        if darts_result.get("available") and darts_result.get("ready"):
            external_points = darts_result.get("points", [])
            for idx, point in enumerate(points):
                if idx >= len(external_points):
                    break
                point["p10"] = float(external_points[idx].get("p10", point["p10"]))
                point["p50"] = float(external_points[idx].get("p50", point["p50"]))
                point["p90"] = float(external_points[idx].get("p90", point["p90"]))
            active_model = "darts_exponential_smoothing_v1"

    p10_avg = statistics.fmean([p["p10"] for p in points]) if points else 0.0
    p50_avg = statistics.fmean([p["p50"] for p in points]) if points else 0.0
    p90_avg = statistics.fmean([p["p90"] for p in points]) if points else 0.0

    tool_input = {
        "user_id": user_id,
        "horizon": horizon,
        "as_of": iso_utc(as_of_dt),
        "scenario_overrides": overrides,
    }
    payload = {
        "horizon": horizon,
        "granularity": granularity,
        "points": points,
        "confidence_band": {
            "p10_avg": round(p10_avg, 2),
            "p50_avg": round(p50_avg, 2),
            "p90_avg": round(p90_avg, 2),
        },
        "model_meta": {
            "model": active_model,
            "history_days": len(day_keys),
            "net_std": round(net_std, 2),
            "low_history": len(day_keys) < 30,
        },
        "assumptions": [
            "Baseline computed from SQL transactions grouped by weekday.",
            "Confidence bands are deterministic from historical net volatility.",
        ],
        "external_engines": {
            "darts_exponential_smoothing": darts_result,
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
        payload={"params": tool_input, "result": {"points": len(points)}},
    )
    return result
