from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from .supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    build_provenance,
    build_reliability,
    build_validation,
    build_window,
    clamp,
    ensure_user_scope,
    iso_utc,
    mean,
    new_trace_id,
    now_utc,
    parse_datetime,
    population_stddev,
    safe_float,
    weighted_score,
)
from .data import (
    fetch_anomaly_feedback,
    fetch_transactions_in_window,
    write_anomaly_feedback_rows,
    write_audit_event,
)
from .legacy_tools import detect_recurring_cashflow
from .trust import build_trust

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


def _enrich_items(
    *,
    items: List[Dict[str, Any]],
    normalized_txn: List[Dict[str, Any]],
    lookback_months: int,
    direction: str,
    feedback_map: Dict[str, List[Dict[str, Any]]] | None = None,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for item in items:
        cp_norm = _normalize_counterparty(str(item.get("counterparty_norm") or ""))
        matches = [
            tx for tx in normalized_txn
            if str(tx.get("direction") or "debit").lower() == direction
            and _normalize_counterparty(str(tx.get("counterparty_norm") or tx.get("counterparty") or "")) == cp_norm
        ]
        matches.sort(key=lambda tx: str(tx.get("date") or ""))
        amounts = [safe_float(tx.get("amount")) for tx in matches]
        dates = [parse_datetime(tx.get("date")) for tx in matches]
        dates = [dt for dt in dates if dt]
        gaps: List[int] = []
        for previous, current in zip(dates, dates[1:]):
            gaps.append(max(1, int((current - previous).total_seconds() // (24 * 60 * 60))))
        periodicity_days = round(mean(gaps), 2) if gaps else 0.0
        amount_mean = mean(amounts)
        amount_cv = safe_float(population_stddev(amounts), 0.0) / amount_mean if amount_mean > 0 else 1.0
        amount_stability = clamp(1.0 - min(1.0, amount_cv))
        timing_stability = clamp(1.0 - safe_float(population_stddev(gaps), 0.0) / max(periodicity_days, 1.0)) if gaps else 0.4
        recurrence_confidence = weighted_score(
            {
                "occurrence_coverage": clamp(safe_float(item.get("occurrence_months")) / max(lookback_months, 1)),
                "amount_stability": amount_stability,
                "timing_stability": timing_stability,
            },
            {
                "occurrence_coverage": 0.4,
                "amount_stability": 0.3,
                "timing_stability": 0.3,
            },
        )
        feedback_rows = list((feedback_map or {}).get(cp_norm, []))
        feedback_labels = [str(row.get("feedback_label") or "") for row in feedback_rows]
        if any(label in {"expected", "false_positive"} for label in feedback_labels):
            recurrence_confidence = clamp(recurrence_confidence + 0.08)
        elif any(label == "confirmed" for label in feedback_labels):
            recurrence_confidence = clamp(recurrence_confidence - 0.05)
        enriched.append(
            {
                **item,
                "periodicity_days": periodicity_days,
                "amount_stability": round(amount_stability, 4),
                "timing_stability": round(timing_stability, 4),
                "recurrence_confidence": round(recurrence_confidence, 4),
                "feedback_labels": feedback_labels,
                "feedback_count": len(feedback_rows),
            }
        )
    return enriched


def _feedback_map(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    mapping: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        entity_type = str(row.get("entity_type") or "")
        entity_id = str(row.get("entity_id") or "")
        if entity_type != "merchant" or not entity_id:
            continue
        normalized = _normalize_counterparty(entity_id)
        mapping.setdefault(normalized, []).append(row)
    return mapping


def _override_feedback_rows(
    *,
    user_id: str,
    trace_id: str,
    overrides: List[Dict[str, Any]],
    as_of_ts: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for override in overrides:
        cp_norm = _normalize_counterparty(str(override.get("counterparty_norm") or override.get("counterparty") or ""))
        if cp_norm == "UNKNOWN":
            continue
        direction = str(override.get("direction") or "debit").lower()
        force_recurring = bool(override.get("force_recurring", True))
        rows.append(
            {
                "user_id": user_id,
                "trace_id": trace_id,
                "tool_name": TOOL_NAME,
                "anomaly_type": "recurring_override",
                "detector_name": "override_capture",
                "entity_type": "merchant",
                "entity_id": cp_norm,
                "feedback_label": "confirmed" if force_recurring else "false_positive",
                "feedback_source": "system",
                "note": f"recurring_override_{direction}",
                "payload": {
                    "override": override,
                    "captured_by": "recurring_cashflow_detect_v1",
                },
                "resolved_at": as_of_ts,
            }
        )
    return rows


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
    feedback_rows = fetch_anomaly_feedback(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    feedback_map = _feedback_map(feedback_rows)
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
    override_feedback_rows = _override_feedback_rows(
        user_id=user_id,
        trace_id=trace,
        overrides=overrides,
        as_of_ts=iso_utc(as_of_dt),
    )
    write_anomaly_feedback_rows(sql, override_feedback_rows)

    recurring_income = _enrich_items(
        items=recurring_income,
        normalized_txn=normalized_txn,
        lookback_months=lookback,
        direction="credit",
        feedback_map=feedback_map,
    )
    recurring_expense = _enrich_items(
        items=recurring_expense,
        normalized_txn=normalized_txn,
        lookback_months=lookback,
        direction="debit",
        feedback_map=feedback_map,
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
    confidence_score = weighted_score(
        {
            "sample_sufficiency": clamp(len(normalized_txn) / max(lookback * 20, 1)),
            "income_item_quality": mean(item.get("recurrence_confidence", 0.0) for item in recurring_income) if recurring_income else 0.0,
            "expense_item_quality": mean(item.get("recurrence_confidence", 0.0) for item in recurring_expense) if recurring_expense else 0.0,
            "drift_signal_quality": 1.0 if not drift_alerts else 0.7,
            "feedback_context": 1.0 if feedback_rows else 0.6,
        },
        {
            "sample_sufficiency": 0.28,
            "income_item_quality": 0.25,
            "expense_item_quality": 0.3,
            "drift_signal_quality": 0.15,
            "feedback_context": 0.02,
        },
    )
    reason_codes = []
    if len(normalized_txn) < lookback * 15:
        reason_codes.append("sparse_transaction_history")
    if not recurring_income and not recurring_expense:
        reason_codes.append("no_recurring_patterns_detected")

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
        "feedback_summary": {
            "feedback_row_count": len(feedback_rows),
            "merchant_feedback_matches": sum(1 for key in feedback_map if feedback_map.get(key)),
            "override_feedback_written": len(override_feedback_rows),
        },
    }
    reliability = build_reliability(
        confidence_score=confidence_score,
        components={
            "sample_sufficiency": clamp(len(normalized_txn) / max(lookback * 20, 1)),
            "income_item_quality": mean(item.get("recurrence_confidence", 0.0) for item in recurring_income) if recurring_income else 0.0,
            "expense_item_quality": mean(item.get("recurrence_confidence", 0.0) for item in recurring_expense) if recurring_expense else 0.0,
            "drift_signal_quality": 1.0 if not drift_alerts else 0.7,
            "feedback_context": 1.0 if feedback_rows else 0.6,
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
            library="legacy_rules_plus_stability_metrics",
            model="recurring_detection_v2",
            model_version="recurring_v2",
            feature_set_version="recurring_features_v2",
        ),
        validation=build_validation(
            tx_count=len(normalized_txn),
            recurring_income_count=len(recurring_income),
            recurring_expense_count=len(recurring_expense),
            feedback_row_count=len(feedback_rows),
            override_feedback_written=len(override_feedback_rows),
        ),
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
                "confidence_score": result.get("reliability", {}).get("confidence_score"),
            },
        },
    )
    return result


