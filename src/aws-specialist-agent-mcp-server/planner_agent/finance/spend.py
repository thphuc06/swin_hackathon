from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict

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
    parse_range_days,
    population_stddev,
    safe_float,
)
from .data import (
    fetch_budgets,
    fetch_categories,
    fetch_jars,
    fetch_transactions_in_window,
    write_audit_event,
)
from .taxonomy import bucket_category
from .trust import build_trust


TOOL_NAME = "spend_analytics_v1"


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spend_analytics(
    *,
    auth_user_id: str,
    user_id: str,
    range_value: str = "30d",
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    range_days = parse_range_days(range_value)
    window_start = daterange_start(as_of_dt, range_days)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=window_start, end_at=as_of_dt)
    jars = fetch_jars(sql, user_id)
    categories = fetch_categories(sql, user_id)
    budgets = fetch_budgets(sql, user_id)

    jar_name_by_id = {str(item.get("id")): str(item.get("name") or "Unknown") for item in jars}
    category_name_by_id = {str(item.get("id")): str(item.get("name") or "Unknown") for item in categories}

    total_spend = 0.0
    total_income = 0.0
    jar_spend: Dict[str, float] = defaultdict(float)
    merchant_spend: Dict[str, float] = defaultdict(float)
    category_spend: Dict[str, float] = defaultdict(float)
    monthly_spend_by_jar: Dict[str, float] = defaultdict(float)
    monthly_spend_by_category: Dict[str, float] = defaultdict(float)
    monthly_spend_total = 0.0
    daily_spend: Dict[str, float] = defaultdict(float)
    essential_spend = 0.0
    discretionary_spend = 0.0
    unknown_spend = 0.0
    categorized_txn = 0
    active_days = set()

    month_start = _month_start(as_of_dt)

    for row in txns:
        amount = safe_float(row.get("amount"))
        direction = str(row.get("direction") or "debit").lower()
        jar_id = str(row.get("jar_id") or "")
        category_id = str(row.get("category_id") or "")
        counterparty = str(row.get("counterparty") or "UNKNOWN")
        occurred_at = parse_datetime(row.get("occurred_at"))

        if direction == "credit":
            total_income += amount
            continue

        total_spend += amount
        jar_spend[jar_id] += amount
        merchant_spend[counterparty] += amount
        category_spend[category_id] += amount
        if occurred_at:
            day_key = occurred_at.date().isoformat()
            daily_spend[day_key] += amount
            active_days.add(day_key)
        if category_id:
            categorized_txn += 1
        bucket = bucket_category(category_name_by_id.get(category_id, ""))
        if bucket == "essential":
            essential_spend += amount
        elif bucket == "discretionary":
            discretionary_spend += amount
        else:
            unknown_spend += amount

        if occurred_at and occurred_at >= month_start:
            monthly_spend_total += amount
            monthly_spend_by_jar[jar_id] += amount
            monthly_spend_by_category[category_id] += amount

    jar_splits = []
    for jar_id, amount in sorted(jar_spend.items(), key=lambda item: item[1], reverse=True):
        pct = (amount / total_spend) if total_spend > 0 else 0.0
        jar_splits.append(
            {
                "jar_id": jar_id,
                "jar_name": jar_name_by_id.get(jar_id, "Unknown"),
                "amount": round(amount, 2),
                "pct_of_spend": round(pct, 4),
            }
        )

    top_merchants = []
    for merchant, amount in sorted(merchant_spend.items(), key=lambda item: item[1], reverse=True)[:5]:
        top_merchants.append({"merchant": merchant, "amount": round(amount, 2)})

    merchant_breakdown = []
    for merchant, amount in sorted(merchant_spend.items(), key=lambda item: item[1], reverse=True)[:10]:
        merchant_breakdown.append(
            {
                "merchant": merchant,
                "amount": round(amount, 2),
                "share": round(amount / total_spend, 4) if total_spend > 0 else 0.0,
            }
        )

    category_breakdown = []
    for category_id, amount in sorted(category_spend.items(), key=lambda item: item[1], reverse=True)[:10]:
        category_breakdown.append(
            {
                "category_id": category_id,
                "category_name": category_name_by_id.get(category_id, "Unknown"),
                "amount": round(amount, 2),
                "share": round(amount / total_spend, 4) if total_spend > 0 else 0.0,
                "bucket": bucket_category(category_name_by_id.get(category_id, "")),
            }
        )

    budget_drift = []
    for budget in budgets:
        scope_type = str(budget.get("scope_type") or "overall").lower()
        scope_id = str(budget.get("scope_id") or "")
        limit_amount = safe_float(budget.get("limit_amount"))
        if limit_amount <= 0:
            continue

        actual = monthly_spend_total
        scope_name = "Overall"
        if scope_type == "jar" and scope_id:
            actual = monthly_spend_by_jar.get(scope_id, 0.0)
            scope_name = jar_name_by_id.get(scope_id, "Unknown Jar")
        elif scope_type == "category" and scope_id:
            actual = monthly_spend_by_category.get(scope_id, 0.0)
            scope_name = category_name_by_id.get(scope_id, "Unknown Category")

        drift_amount = actual - limit_amount
        drift_pct = drift_amount / limit_amount if limit_amount > 0 else 0.0
        budget_drift.append(
            {
                "budget_id": str(budget.get("id") or ""),
                "scope_type": scope_type,
                "scope_id": scope_id or None,
                "scope_name": scope_name,
                "period": str(budget.get("period") or "monthly"),
                "limit_amount": round(limit_amount, 2),
                "actual_amount": round(actual, 2),
                "drift_amount": round(drift_amount, 2),
                "drift_pct": round(drift_pct, 4),
                "status": "over" if drift_amount > 0 else "on_track",
            }
        )

    daily_spend_values = list(daily_spend.values())
    debit_count = sum(1 for row in txns if str(row.get("direction") or "debit").lower() != "credit")
    categorized_txn_ratio = (categorized_txn / debit_count) if debit_count > 0 else 0.0
    active_days_ratio = (len(active_days) / range_days) if range_days > 0 else 0.0
    history_score = min(1.0, range_days / 90.0)
    data_quality_score = clamp(
        0.45 * categorized_txn_ratio
        + 0.35 * active_days_ratio
        + 0.20 * history_score
    )
    data_quality = {
        "history_days": range_days,
        "debit_txn_count": debit_count,
        "categorized_txn_ratio": round(categorized_txn_ratio, 4),
        "missing_category_ratio": round(1 - categorized_txn_ratio, 4) if debit_count > 0 else 0.0,
        "active_days_ratio": round(active_days_ratio, 4),
        "jar_coverage_ratio": round(sum(1 for row in txns if row.get("jar_id")) / len(txns), 4) if txns else 0.0,
        "counterparty_coverage_ratio": round(sum(1 for row in txns if str(row.get("counterparty") or "").strip()) / len(txns), 4) if txns else 0.0,
    }
    reason_codes = []
    if not txns:
        reason_codes.append("no_transactions_in_window")
    if range_days < 90:
        reason_codes.append("short_window")
    if active_days_ratio < 0.5:
        reason_codes.append("low_activity")
    if categorized_txn_ratio < 0.8:
        reason_codes.append("category_coverage_low")

    tool_input = {
        "user_id": user_id,
        "range": f"{range_days}d",
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "range": f"{range_days}d",
        "window_start": iso_utc(window_start),
        "window_end": iso_utc(as_of_dt),
        "total_spend": round(total_spend, 2),
        "total_income": round(total_income, 2),
        "net_cashflow": round(total_income - total_spend, 2),
        "jar_splits": jar_splits,
        "top_merchants": top_merchants,
        "merchant_breakdown": merchant_breakdown,
        "category_breakdown": category_breakdown,
        "essential_vs_discretionary_breakdown": {
            "essential": round(essential_spend, 2),
            "discretionary": round(discretionary_spend, 2),
            "unknown": round(unknown_spend, 2),
        },
        "spend_volatility": {
            "daily_average": round(mean(daily_spend_values), 2),
            "daily_stddev": round(population_stddev(daily_spend_values), 2),
        },
        "category_concentration_hhi": round(hhi(category_spend.values()), 4),
        "top_category_share": round(max((row["share"] for row in category_breakdown), default=0.0), 4),
        "data_quality": data_quality,
        "budget_drift": budget_drift,
    }
    reliability = build_reliability(
        confidence_score=data_quality_score,
        components={
            "data_quality": data_quality_score,
            "categorization": categorized_txn_ratio,
            "activity": active_days_ratio,
            "history": history_score,
        },
        reason_codes=reason_codes,
    )
    trust_bundle = build_trust(
        confidence_score=safe_float(reliability["confidence_score"]),
        reliability_components=reliability.get("components"),
        abstain_recommended=bool(reliability.get("abstain_recommended")),
        prior_alpha=9.0,
        prior_beta=1.0,
    )

    result = build_output(
        tool_name=TOOL_NAME,
        tool_input=tool_input,
        payload=payload,
        trace_id=trace,
        started_at=started_at,
        sql_snapshot_ts=iso_utc(),
        as_of=iso_utc(as_of_dt),
        window=build_window(window_start, as_of_dt),
        reliability=reliability,
        trust=trust_bundle["trust"],
        agent_use=trust_bundle["agent_use"],
        provenance=build_provenance(
            library="deterministic_sql_aggregates",
            model="windowed_spend_analytics_v2",
            model_version="spend_v2",
            feature_set_version="spend_window_features_v2",
        ),
        validation=build_validation(
            tx_count=len(txns),
            debit_txn_count=debit_count,
            daily_points=len(daily_spend_values),
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
                "total_spend": payload["total_spend"],
                "confidence_score": result.get("reliability", {}).get("confidence_score"),
            },
        },
    )
    return result


