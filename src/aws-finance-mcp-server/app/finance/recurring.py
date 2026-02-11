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
    parse_datetime,
    safe_float,
)
from .data import fetch_transactions_in_window, write_audit_event
from .legacy_tools import detect_recurring_cashflow

TOOL_NAME = "recurring_cashflow_detect_v1"


def _normalize_counterparty(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() else " " for ch in (value or "").upper())
    return " ".join(normalized.split()) or "UNKNOWN"


def _map_transactions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        occurred = parse_datetime(row.get("occurred_at"))
        if not occurred:
            continue
        amount = safe_float(row.get("amount"))
        direction = str(row.get("direction") or "debit").lower()
        counterparty = str(row.get("counterparty") or "UNKNOWN")
        normalized.append(
            {
                "date": occurred.date().isoformat(),
                "amount": amount,
                "direction": direction,
                "counterparty": counterparty,
                "counterparty_norm": _normalize_counterparty(counterparty),
            }
        )
    return normalized


def _apply_overrides(
    *,
    recurring_income: List[Dict[str, Any]],
    recurring_expense: List[Dict[str, Any]],
    min_occurrence_months: int,
    overrides: List[Dict[str, Any]],
) -> Dict[str, int]:
    applied = 0
    removed = 0
    for override in overrides:
        cp_norm = _normalize_counterparty(str(override.get("counterparty_norm") or override.get("counterparty") or ""))
        if cp_norm == "UNKNOWN":
            continue
        direction = str(override.get("direction") or "debit").lower()
        force_recurring = bool(override.get("force_recurring", True))
        amount_override = override.get("average_amount")
        occurrence_override = override.get("occurrence_months")
        target = recurring_income if direction == "credit" else recurring_expense
        idx = -1
        for i, item in enumerate(target):
            if _normalize_counterparty(str(item.get("counterparty_norm") or "")) == cp_norm:
                idx = i
                break

        if not force_recurring:
            if idx >= 0:
                target.pop(idx)
                removed += 1
            continue

        if idx >= 0:
            item = target[idx]
        else:
            item = {
                "counterparty_norm": cp_norm,
                "average_amount": 0.0,
                "occurrence_months": min_occurrence_months,
                "recurring_score": 1.0,
            }
            target.append(item)
            idx = len(target) - 1

        if amount_override is not None:
            item["average_amount"] = round(max(0.0, safe_float(amount_override)), 2)
        if occurrence_override is not None:
            item["occurrence_months"] = max(1, int(safe_float(occurrence_override)))
        item["recurring_score"] = round(max(0.0, min(1.0, safe_float(item.get("recurring_score"), 1.0))), 4)
        target[idx] = item
        applied += 1

    return {"applied": applied, "removed": removed}


def _build_drift_alerts(
    *,
    normalized_txn: List[Dict[str, Any]],
    recurring_expense: List[Dict[str, Any]],
    as_of_dt,
    drift_threshold_pct: float,
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    recent_start = as_of_dt - timedelta(days=30)
    for item in recurring_expense:
        cp_norm = _normalize_counterparty(str(item.get("counterparty_norm") or ""))
        if cp_norm == "UNKNOWN":
            continue

        baseline_values: List[float] = []
        recent_values: List[float] = []
        for tx in normalized_txn:
            if str(tx.get("direction") or "debit").lower() != "debit":
                continue
            if _normalize_counterparty(str(tx.get("counterparty_norm") or tx.get("counterparty") or "")) != cp_norm:
                continue
            tx_date = parse_datetime(tx.get("date"))
            if not tx_date:
                continue
            amount = safe_float(tx.get("amount"))
            if tx_date >= recent_start:
                recent_values.append(amount)
            else:
                baseline_values.append(amount)

        if not baseline_values or not recent_values:
            continue

        baseline_avg = sum(baseline_values) / len(baseline_values)
        recent_avg = sum(recent_values) / len(recent_values)
        if baseline_avg <= 0:
            continue

        drift_pct = (recent_avg - baseline_avg) / baseline_avg
        if abs(drift_pct) < drift_threshold_pct:
            continue

        alerts.append(
            {
                "counterparty_norm": cp_norm,
                "baseline_avg": round(baseline_avg, 2),
                "recent_avg": round(recent_avg, 2),
                "drift_pct": round(drift_pct, 4),
                "direction": "up" if drift_pct > 0 else "down",
            }
        )

    alerts.sort(key=lambda row: abs(safe_float(row.get("drift_pct"))), reverse=True)
    return alerts


def recurring_cashflow_detect(
    *,
    auth_user_id: str,
    user_id: str,
    lookback_months: int = 6,
    min_occurrence_months: int = 3,
    recurring_overrides: List[Dict[str, Any]] | None = None,
    drift_threshold_pct: float = 0.2,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    lookback = max(3, min(24, int(lookback_months or 6)))
    min_occurrence = max(2, min(12, int(min_occurrence_months or 3)))
    drift_threshold = max(0.0, min(2.0, safe_float(drift_threshold_pct, 0.2)))
    as_of_dt = parse_datetime(as_of) or now_utc()
    start_dt = as_of_dt - timedelta(days=lookback * 31)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    normalized_txn = _map_transactions(txns)

    detected = detect_recurring_cashflow(
        normalized_txn=normalized_txn,
        lookback_months=lookback,
        trace_id=trace,
    )

    recurring_income = list(detected.get("recurring_income") or [])
    recurring_expense = list(detected.get("recurring_expense") or [])
    recurring_income = [item for item in recurring_income if int(item.get("occurrence_months") or 0) >= min_occurrence]
    recurring_expense = [item for item in recurring_expense if int(item.get("occurrence_months") or 0) >= min_occurrence]

    overrides = recurring_overrides or []
    override_stats = _apply_overrides(
        recurring_income=recurring_income,
        recurring_expense=recurring_expense,
        min_occurrence_months=min_occurrence,
        overrides=overrides,
    )

    recurring_income.sort(key=lambda item: safe_float(item.get("average_amount")), reverse=True)
    recurring_expense.sort(key=lambda item: safe_float(item.get("average_amount")), reverse=True)

    total_spend = sum(
        safe_float(tx.get("amount"))
        for tx in normalized_txn
        if str(tx.get("direction") or "debit").lower() == "debit"
    )
    recurring_spend_est = sum(safe_float(item.get("average_amount")) for item in recurring_expense)
    fixed_cost_ratio = (recurring_spend_est / total_spend) if total_spend > 0 else 0.0

    drift_alerts = _build_drift_alerts(
        normalized_txn=normalized_txn,
        recurring_expense=recurring_expense,
        as_of_dt=as_of_dt,
        drift_threshold_pct=drift_threshold,
    )

    tool_input = {
        "user_id": user_id,
        "lookback_months": lookback,
        "min_occurrence_months": min_occurrence,
        "drift_threshold_pct": drift_threshold,
        "recurring_overrides": overrides,
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "lookback_months": lookback,
        "window_start": iso_utc(start_dt),
        "window_end": iso_utc(as_of_dt),
        "recurring_income": recurring_income,
        "recurring_expense": recurring_expense,
        "fixed_cost_ratio": round(max(0.0, min(1.0, fixed_cost_ratio)), 4),
        "drift_alerts": drift_alerts,
        "overrides_applied": override_stats,
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
                "lookback_months": lookback,
                "min_occurrence_months": min_occurrence,
            },
            "result": {
                "recurring_income_count": len(recurring_income),
                "recurring_expense_count": len(recurring_expense),
            },
        },
    )
    return result
