from __future__ import annotations

import statistics
from collections import defaultdict
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
from .data import fetch_income_sources, fetch_transactions_in_window, write_audit_event

TOOL_NAME = "risk_profile_non_investment_v1"


def risk_profile_non_investment(
    *,
    auth_user_id: str,
    user_id: str,
    lookback_days: int = 180,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    lookback = max(60, min(720, int(lookback_days or 180)))
    start_dt = daterange_start(as_of_dt, lookback)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    income_sources = fetch_income_sources(sql, user_id)

    monthly_income: Dict[str, float] = defaultdict(float)
    monthly_spend: Dict[str, float] = defaultdict(float)

    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred:
            continue
        month_key = occurred.strftime("%Y-%m")
        amount = safe_float(tx.get("amount"))
        direction = str(tx.get("direction") or "debit").lower()
        if direction == "credit":
            monthly_income[month_key] += amount
        else:
            monthly_spend[month_key] += amount

    months = sorted(set(monthly_income.keys()) | set(monthly_spend.keys()))
    net_values: List[float] = []
    overspend_count = 0
    for month in months:
        income = monthly_income.get(month, 0.0)
        spend = monthly_spend.get(month, 0.0)
        net = income - spend
        net_values.append(net)
        if spend > income and income > 0:
            overspend_count += 1

    avg_monthly_income = statistics.fmean([monthly_income.get(month, 0.0) for month in months]) if months else 0.0
    avg_monthly_spend = statistics.fmean([monthly_spend.get(month, 0.0) for month in months]) if months else 0.0
    avg_monthly_net = statistics.fmean(net_values) if net_values else 0.0
    net_volatility = statistics.pstdev(net_values) if len(net_values) > 1 else abs(avg_monthly_net) * 0.2

    volatility_ratio = (net_volatility / avg_monthly_income) if avg_monthly_income > 0 else 1.0
    overspend_propensity = (overspend_count / len(months)) if months else 0.0

    cash_buffer_proxy = sum(safe_float(item.get("monthly_amount")) for item in income_sources)
    if avg_monthly_net < 0 and cash_buffer_proxy > 0:
        runway_months = cash_buffer_proxy / abs(avg_monthly_net)
    elif avg_monthly_net >= 0:
        runway_months = 999.0
    else:
        runway_months = 0.0

    risk_score = 0.0
    risk_score += min(1.0, volatility_ratio) * 0.4
    risk_score += min(1.0, overspend_propensity) * 0.35
    runway_component = 1.0 if runway_months == 0 else (0.0 if runway_months >= 6 else (1 - runway_months / 6))
    risk_score += max(0.0, min(1.0, runway_component)) * 0.25

    if risk_score >= 0.66:
        risk_band = "high"
    elif risk_score >= 0.33:
        risk_band = "moderate"
    else:
        risk_band = "low"

    signals = [
        {
            "name": "cashflow_volatility",
            "value": round(volatility_ratio, 4),
            "note": "Net cashflow volatility relative to average monthly income.",
        },
        {
            "name": "emergency_runway_months",
            "value": round(runway_months, 2) if runway_months != 999.0 else 999,
            "note": "Estimated months before buffer depletion under current average net.",
        },
        {
            "name": "overspend_propensity",
            "value": round(overspend_propensity, 4),
            "note": "Share of months where spend exceeded income.",
        },
    ]

    tool_input = {
        "user_id": user_id,
        "lookback_days": lookback,
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "cashflow_volatility": round(volatility_ratio, 4),
        "emergency_runway_months": round(runway_months, 2) if runway_months != 999.0 else 999,
        "overspend_propensity": round(overspend_propensity, 4),
        "risk_band": risk_band,
        "signals": signals,
        "summary": {
            "avg_monthly_income": round(avg_monthly_income, 2),
            "avg_monthly_spend": round(avg_monthly_spend, 2),
            "avg_monthly_net": round(avg_monthly_net, 2),
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
        payload={"params": tool_input, "result": {"risk_band": risk_band}},
    )
    return result
