from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any, Dict, List

from .supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    build_provenance,
    build_reliability,
    build_validation,
    build_window,
    clamp,
    daterange_start,
    ensure_user_scope,
    hhi,
    iso_utc,
    mean,
    new_trace_id,
    now_utc,
    parse_datetime,
    safe_float,
    weighted_score,
)
from .data import fetch_balance_daily, fetch_income_sources, fetch_profiles, fetch_transactions_in_window, write_audit_event
from .trust import build_trust

TOOL_NAME = "risk_profile_non_investment_v1"
BALANCE_QUALITY_SCORES = {
    "verified": 1.0,
    "reconciled": 0.95,
    "estimated": 0.7,
    "unverified": 0.4,
}


def _recurring_burden_ratio(txns: List[Dict[str, Any]]) -> float:
    month_counterparty_amounts: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    total_spend = 0.0
    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred or str(tx.get("direction") or "debit").lower() == "credit":
            continue
        month_key = occurred.strftime("%Y-%m")
        counterparty = str(tx.get("counterparty") or "UNKNOWN")
        amount = safe_float(tx.get("amount"))
        month_counterparty_amounts[counterparty][month_key] += amount
        total_spend += amount
    recurring_total = 0.0
    for counterparty, month_values in month_counterparty_amounts.items():
        if len(month_values) < 3:
            continue
        recurring_total += mean(month_values.values())
    return clamp(recurring_total / total_spend) if total_spend > 0 else 0.0


def _latest_balance_snapshot(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "latest_balance": 0.0,
            "balance_quality": 0.0,
            "quality_flag": "missing",
            "source": "income_sources_proxy",
            "latest_date": None,
            "row_count": 0,
        }

    latest_day = max(str(row.get("balance_date") or "") for row in rows)
    latest_rows = [row for row in rows if str(row.get("balance_date") or "") == latest_day]
    overall_rows = [row for row in latest_rows if str(row.get("scope_type") or "") == "overall"]
    chosen_rows = overall_rows or latest_rows
    quality_scores = [
        BALANCE_QUALITY_SCORES.get(str(row.get("quality_flag") or "unverified"), 0.4)
        for row in chosen_rows
    ]
    return {
        "available": True,
        "latest_balance": round(sum(safe_float(row.get("closing_balance")) for row in chosen_rows), 2),
        "balance_quality": round(mean(quality_scores, default=0.4), 4),
        "quality_flag": str(chosen_rows[0].get("quality_flag") or "unverified"),
        "source": str(chosen_rows[0].get("source") or "derived"),
        "latest_date": latest_day,
        "row_count": len(rows),
    }


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
    profiles = fetch_profiles(sql, user_id)
    balance_rows = fetch_balance_daily(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)

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
    no_transactions_in_window = len(txns) == 0

    volatility_ratio = (net_volatility / avg_monthly_income) if avg_monthly_income > 0 else 0.0
    overspend_propensity = (overspend_count / len(months)) if months else 0.0
    recurring_burden_ratio = _recurring_burden_ratio(txns)
    income_concentration = hhi(safe_float(item.get("monthly_amount")) for item in income_sources)
    balance_snapshot = _latest_balance_snapshot(balance_rows)

    cash_buffer_proxy = sum(safe_float(item.get("monthly_amount")) for item in income_sources)
    available_balance = safe_float(balance_snapshot.get("latest_balance")) if balance_snapshot["available"] else cash_buffer_proxy
    if avg_monthly_net < 0 and available_balance > 0:
        runway_months = available_balance / abs(avg_monthly_net)
    elif avg_monthly_net >= 0:
        runway_months = 999.0
    else:
        runway_months = 0.0
    if no_transactions_in_window and available_balance <= 0:
        runway_months = None

    risk_score = 0.0
    risk_score += min(1.0, volatility_ratio) * 0.4
    risk_score += min(1.0, overspend_propensity) * 0.35
    if runway_months is None:
        runway_component = 0.0
    else:
        runway_component = 1.0 if runway_months == 0 else (0.0 if runway_months >= 6 else (1 - runway_months / 6))
    risk_score += max(0.0, min(1.0, runway_component)) * 0.25
    risk_score = clamp(
        risk_score
        + 0.15 * min(1.0, recurring_burden_ratio)
        + 0.10 * min(1.0, income_concentration)
    )

    if no_transactions_in_window:
        risk_band = "unknown"
    elif risk_score >= 0.66:
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
            "value": (
                round(runway_months, 2)
                if runway_months is not None and runway_months != 999.0
                else (999 if runway_months == 999.0 else None)
            ),
            "note": "Estimated months before buffer depletion under current average net.",
            "source": "balance_daily" if balance_snapshot["available"] else "income_sources_proxy",
        },
        {
            "name": "overspend_propensity",
            "value": round(overspend_propensity, 4),
            "note": "Share of months where spend exceeded income.",
        },
        {
            "name": "recurring_burden_ratio",
            "value": round(recurring_burden_ratio, 4),
            "note": "Proxy ratio of recurring-like expenses over total spend.",
        },
        {
            "name": "income_concentration",
            "value": round(income_concentration, 4),
            "note": "HHI concentration across declared income sources.",
        },
    ]

    stress_summary = {
        "income_drop_10pct": {
            "projected_net": round((avg_monthly_income * 0.9) - avg_monthly_spend, 2),
            "risk_band": "high" if ((avg_monthly_income * 0.9) - avg_monthly_spend) < 0 else risk_band,
        },
        "spend_up_10pct": {
            "projected_net": round(avg_monthly_income - (avg_monthly_spend * 1.1), 2),
            "risk_band": "high" if (avg_monthly_income - (avg_monthly_spend * 1.1)) < 0 else risk_band,
        },
    }
    profile = profiles[0] if profiles else {}
    confidence_score = weighted_score(
        {
            "history": clamp(len(months) / 6.0),
            "income_sources": clamp(len(income_sources) / 3.0),
            "recurring_proxy": 1.0 - clamp(abs(recurring_burden_ratio - 0.4)),
            "balance_data_quality": balance_snapshot["balance_quality"] if balance_snapshot["available"] else 0.45,
        },
        {
            "history": 0.35,
            "income_sources": 0.25,
            "recurring_proxy": 0.2,
            "balance_data_quality": 0.2,
        },
    )
    reason_codes = []
    if no_transactions_in_window:
        reason_codes.append("no_transactions_in_window")
    if not balance_snapshot["available"]:
        reason_codes.append("balance_proxy_used")
    elif balance_snapshot["balance_quality"] < 0.75:
        reason_codes.append("balance_quality_low")
    if len(months) < 3:
        reason_codes.append("limited_month_history")
    if not income_sources:
        reason_codes.append("missing_income_sources")

    tool_input = {
        "user_id": user_id,
        "lookback_days": lookback,
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "lookback_days": lookback,
        "cashflow_volatility": round(volatility_ratio, 4),
        "emergency_runway_months": (
            round(runway_months, 2)
            if runway_months is not None and runway_months != 999.0
            else (999 if runway_months == 999.0 else None)
        ),
        "overspend_propensity": round(overspend_propensity, 4),
        "risk_score": round(risk_score, 4),
        "risk_band": risk_band,
        "signals": signals,
        "drivers": {
            "volatility": round(volatility_ratio, 4),
            "runway": round(runway_component, 4),
            "overspend": round(overspend_propensity, 4),
            "recurring_burden": round(recurring_burden_ratio, 4),
            "income_concentration": round(income_concentration, 4),
        },
        "stress_summary": stress_summary,
        "summary": {
            "avg_monthly_income": round(avg_monthly_income, 2),
            "avg_monthly_spend": round(avg_monthly_spend, 2),
            "avg_monthly_net": round(avg_monthly_net, 2),
            "profile_risk_preference": str(profile.get("risk_profile_current") or ""),
            "balance_context": {
                "source": "balance_daily" if balance_snapshot["available"] else "income_sources_proxy",
                "latest_balance": round(available_balance, 2),
                "latest_balance_date": balance_snapshot.get("latest_date"),
                "quality_flag": balance_snapshot.get("quality_flag"),
            },
        },
    }
    reliability = build_reliability(
        confidence_score=confidence_score,
        components={
            "history": clamp(len(months) / 6.0),
            "income_source_completeness": clamp(len(income_sources) / 3.0),
            "recurring_proxy_quality": 1.0 - clamp(abs(recurring_burden_ratio - 0.4)),
            "balance_data_quality": balance_snapshot["balance_quality"] if balance_snapshot["available"] else 0.45,
        },
        reason_codes=reason_codes,
    )
    trust_bundle = build_trust(
        confidence_score=safe_float(reliability["confidence_score"]),
        reliability_components=reliability.get("components"),
        abstain_recommended=bool(reliability.get("abstain_recommended")),
        prior_alpha=7.0,
        prior_beta=3.0,
    )

    result = build_output(
        tool_name=TOOL_NAME,
        tool_input=tool_input,
        payload=payload,
        trace_id=trace,
        started_at=started_at,
        sql_snapshot_ts=iso_utc(),
        as_of=iso_utc(as_of_dt),
        window=build_window(start_dt, as_of_dt),
        reliability=reliability,
        trust=trust_bundle["trust"],
        agent_use=trust_bundle["agent_use"],
        provenance=build_provenance(
            library="deterministic_heuristics",
            model="non_investment_risk_v2",
            model_version="risk_v2",
            feature_set_version="risk_features_v2",
        ),
        validation=build_validation(
            month_count=len(months),
            tx_count=len(txns),
            income_source_count=len(income_sources),
            balance_row_count=len(balance_rows),
            balance_source="balance_daily" if balance_snapshot["available"] else "income_sources_proxy",
        ),
    )
    write_audit_event(
        sql,
        user_id=user_id,
        trace_id=trace,
        event_type=TOOL_NAME,
        payload={
            "params": tool_input,
            "result": {
                "risk_band": risk_band,
                "confidence_score": result.get("reliability", {}).get("confidence_score"),
            },
        },
    )
    return result


