from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict

from app.services.supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    daterange_start,
    ensure_user_scope,
    iso_utc,
    new_trace_id,
    now_utc,
    parse_datetime,
    parse_range_days,
    safe_float,
)
from .data import (
    fetch_budgets,
    fetch_categories,
    fetch_jars,
    fetch_transactions_in_window,
    write_audit_event,
)


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
    monthly_spend_by_jar: Dict[str, float] = defaultdict(float)
    monthly_spend_by_category: Dict[str, float] = defaultdict(float)
    monthly_spend_total = 0.0

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
        "budget_drift": budget_drift,
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
        payload={"params": tool_input, "result": {"total_spend": payload["total_spend"]}},
    )
    return result
