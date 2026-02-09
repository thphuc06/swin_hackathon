from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List

from app.supabase_rest import SupabaseRestClient, get_supabase_client

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
from .data import (
    fetch_categories,
    fetch_income_sources,
    fetch_transactions_in_window,
    write_audit_event,
)
from .oss_adapters import ruptures_pelt_change_points, pyod_ecod_outlier, river_adwin_drift

TOOL_NAME = "anomaly_signals_v1"


def _median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def _mad(values: List[float], median_value: float) -> float:
    deviations = [abs(v - median_value) for v in values]
    return statistics.median(deviations) if deviations else 0.0


def anomaly_signals(
    *,
    auth_user_id: str,
    user_id: str,
    lookback_days: int = 90,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    lookback = max(30, min(365, int(lookback_days or 90)))
    start_dt = daterange_start(as_of_dt, lookback)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    categories = fetch_categories(sql, user_id)
    income_sources = fetch_income_sources(sql, user_id)
    category_name_by_id = {str(item.get("id")): str(item.get("name") or "Unknown") for item in categories}

    daily_spend: Dict[str, float] = defaultdict(float)
    daily_income: Dict[str, float] = defaultdict(float)
    recent_30_category_spend: Dict[str, float] = defaultdict(float)
    prior_60_category_spend: Dict[str, float] = defaultdict(float)

    recent_cutoff = as_of_dt - timedelta(days=29)
    prior_cutoff = as_of_dt - timedelta(days=89)

    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred:
            continue
        day_key = occurred.date().isoformat()
        amount = safe_float(tx.get("amount"))
        direction = str(tx.get("direction") or "debit").lower()
        category_id = str(tx.get("category_id") or "")

        if direction == "credit":
            daily_income[day_key] += amount
            continue

        daily_spend[day_key] += amount
        if occurred >= recent_cutoff:
            recent_30_category_spend[category_id] += amount
        elif occurred >= prior_cutoff:
            prior_60_category_spend[category_id] += amount

    day_keys = sorted(set(daily_spend.keys()) | set(daily_income.keys()))
    spend_series = [daily_spend.get(day, 0.0) for day in day_keys]
    river_result = river_adwin_drift(spend_series)
    pyod_result = pyod_ecod_outlier(spend_series)
    ruptures_result = ruptures_pelt_change_points(day_keys, spend_series, penalty=3.0)

    median_spend = _median(spend_series)
    mad_spend = _mad(spend_series, median_spend)
    robust_sigma = mad_spend * 1.4826 if mad_spend > 0 else 0.0
    recent_spend_avg = statistics.fmean(spend_series[-7:]) if spend_series else 0.0
    z_score = 0.0
    if robust_sigma > 0:
        z_score = (recent_spend_avg - median_spend) / robust_sigma

    daily_income_series = [daily_income.get(day, 0.0) for day in day_keys]
    recent_income_avg = statistics.fmean(daily_income_series[-30:]) if daily_income_series else 0.0
    prior_income_avg = statistics.fmean(daily_income_series[-90:-30]) if len(daily_income_series) > 30 else 0.0
    income_drop_pct = 0.0
    if prior_income_avg > 0:
        income_drop_pct = max(0.0, (prior_income_avg - recent_income_avg) / prior_income_avg)

    total_recent_category = sum(recent_30_category_spend.values())
    total_prior_category = sum(prior_60_category_spend.values())
    category_spikes = []
    for category_id, recent_value in recent_30_category_spend.items():
        prior_value = prior_60_category_spend.get(category_id, 0.0) / 2.0
        recent_share = (recent_value / total_recent_category) if total_recent_category > 0 else 0.0
        prior_share = (prior_value / total_prior_category) if total_prior_category > 0 else 0.0
        delta_share = recent_share - prior_share
        if delta_share >= 0.12 and recent_value >= 1_000_000:
            category_spikes.append(
                {
                    "category_id": category_id,
                    "category_name": category_name_by_id.get(category_id, "Unknown"),
                    "recent_amount": round(recent_value, 2),
                    "baseline_amount": round(prior_value, 2),
                    "delta_share": round(delta_share, 4),
                }
            )

    category_spikes.sort(key=lambda item: item["delta_share"], reverse=True)

    cash_buffer_proxy = sum(safe_float(item.get("monthly_amount")) for item in income_sources)
    net_series = [daily_income.get(day, 0.0) - daily_spend.get(day, 0.0) for day in day_keys]
    avg_daily_net = statistics.fmean(net_series[-30:]) if net_series else 0.0
    runway_days = 9999.0
    if avg_daily_net < 0 and cash_buffer_proxy > 0:
        runway_days = cash_buffer_proxy / abs(avg_daily_net)

    abnormal_spend_flag = z_score >= 2.5 or bool(river_result.get("drift_detected")) or bool(pyod_result.get("outlier_flag"))
    income_drop_flag = income_drop_pct >= 0.25
    low_balance_flag = runway_days < 90

    flags = []
    if abnormal_spend_flag:
        flags.append("abnormal_spend")
    if bool(river_result.get("drift_detected")):
        flags.append("spend_drift")
    if bool(pyod_result.get("outlier_flag")):
        flags.append("spend_outlier")
    if bool(ruptures_result.get("change_detected")):
        flags.append("change_point")
    if income_drop_flag:
        flags.append("income_drop")
    if category_spikes:
        flags.append("category_spike")
    if low_balance_flag:
        flags.append("low_balance_risk")
    flags = sorted(set(flags))

    tool_input = {
        "user_id": user_id,
        "lookback_days": lookback,
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "abnormal_spend": {
            "flag": abnormal_spend_flag,
            "z_score": round(z_score, 4),
            "median_daily_spend": round(median_spend, 2),
            "recent_7d_avg_spend": round(recent_spend_avg, 2),
        },
        "income_drop": {
            "flag": income_drop_flag,
            "drop_pct": round(income_drop_pct, 4),
            "recent_daily_income_avg": round(recent_income_avg, 2),
            "baseline_daily_income_avg": round(prior_income_avg, 2),
        },
        "category_spikes": category_spikes[:5],
        "low_balance_risk": {
            "flag": low_balance_flag,
            "runway_days_estimate": round(runway_days, 2) if runway_days != 9999.0 else 9999,
            "cash_buffer_proxy": round(cash_buffer_proxy, 2),
            "avg_daily_net": round(avg_daily_net, 2),
        },
        "flags": flags,
        "external_engines": {
            "river_adwin": river_result,
            "pyod_ecod": pyod_result,
            "ruptures_pelt": ruptures_result,
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
        payload={"params": tool_input, "result": {"flags": flags}},
    )
    return result
