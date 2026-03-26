from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, List

from .supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_model_evidence,
    build_native_confidence,
    build_output,
    build_provenance,
    build_reliability,
    build_validation,
    build_window,
    clamp,
    daterange_start,
    ensure_user_scope,
    iso_utc,
    mean,
    new_trace_id,
    normalize_reason_codes,
    now_utc,
    parse_datetime,
    safe_div,
    safe_float,
    weighted_score,
)
from .data import (
    fetch_audit_events,
    fetch_anomaly_feedback,
    fetch_balance_daily,
    fetch_categories,
    fetch_income_sources,
    fetch_transactions_in_window,
    write_audit_event,
)
from .feedback import anomaly_feedback_options
from .oss_adapters import pyod_ecod_outlier, river_adwin_drift, ruptures_pelt_change_points
from .recalibration import build_anomaly_recalibration_dataset, fit_recalibrated_probability
from .trust import build_trust, count_latest_anomaly_feedback

TOOL_NAME = "anomaly_signals_v1"
BALANCE_QUALITY_SCORES = {
    "verified": 1.0,
    "reconciled": 0.95,
    "estimated": 0.7,
    "unverified": 0.4,
}


def _median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def _mad(values: List[float], median_value: float) -> float:
    deviations = [abs(v - median_value) for v in values]
    return statistics.median(deviations) if deviations else 0.0


def _dense_daily_rows(
    txns: List[Dict[str, Any]],
    *,
    start_dt,
    end_dt,
) -> List[Dict[str, Any]]:
    day_map: Dict[str, Dict[str, float]] = defaultdict(lambda: {"income": 0.0, "spend": 0.0})
    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred:
            continue
        day_key = occurred.date().isoformat()
        amount = safe_float(tx.get("amount"))
        direction = str(tx.get("direction") or "debit").lower()
        if direction == "credit":
            day_map[day_key]["income"] += amount
        else:
            day_map[day_key]["spend"] += amount

    cursor = start_dt
    dense_rows: List[Dict[str, Any]] = []
    while cursor.date() <= end_dt.date():
        day_key = cursor.date().isoformat()
        income = day_map.get(day_key, {}).get("income", 0.0)
        spend = day_map.get(day_key, {}).get("spend", 0.0)
        dense_rows.append(
            {
                "day": day_key,
                "income": income,
                "spend": spend,
                "net": income - spend,
            }
        )
        cursor += timedelta(days=1)
    return dense_rows


def _build_spike_rows(
    recent_map: Dict[str, float],
    prior_map: Dict[str, float],
    *,
    name_lookup: Dict[str, str] | None = None,
) -> List[Dict[str, Any]]:
    total_recent = sum(recent_map.values())
    total_prior = sum(prior_map.values())
    rows: List[Dict[str, Any]] = []
    for key, recent_value in recent_map.items():
        prior_value = prior_map.get(key, 0.0) / 2.0
        recent_share = safe_div(recent_value, total_recent)
        prior_share = safe_div(prior_value, total_prior)
        delta_share = recent_share - prior_share
        if delta_share < 0.08 or recent_value < 1_000_000:
            continue
        rows.append(
            {
                "id": key,
                "name": name_lookup.get(key, key) if name_lookup else key,
                "recent_amount": round(recent_value, 2),
                "baseline_amount": round(prior_value, 2),
                "delta_share": round(delta_share, 4),
            }
        )
    rows.sort(key=lambda item: item["delta_share"], reverse=True)
    return rows[:5]


def _transaction_outliers(txns: List[Dict[str, Any]], category_name_by_id: Dict[str, str]) -> Dict[str, Any]:
    try:
        import numpy as np
        from pyod.models.ecod import ECOD
    except Exception as exc:  # pragma: no cover
        return {"available": False, "ready": False, "error": str(exc), "items": []}

    debit_txns = [tx for tx in txns if str(tx.get("direction") or "debit").lower() != "credit"]
    model_txns = debit_txns if len(debit_txns) >= 20 else list(txns)
    fit_scope = "debit_only" if model_txns is debit_txns else "mixed_fallback"
    suppressed_credit_candidate_count = max(0, len(txns) - len(model_txns))
    if len(model_txns) < 20:
        return {
            "available": True,
            "ready": False,
            "reason": "insufficient_samples",
            "fit_scope": fit_scope,
            "suppressed_credit_candidate_count": suppressed_credit_candidate_count,
            "items": [],
        }

    merchant_counts = Counter(str(tx.get("counterparty") or "UNKNOWN") for tx in model_txns)
    all_amounts = [safe_float(tx.get("amount")) for tx in model_txns]
    user_median = _median(all_amounts)
    user_sigma = max(1.0, _mad(all_amounts, user_median) * 1.4826)
    category_amounts: Dict[str, List[float]] = defaultdict(list)
    counterparty_amounts: Dict[str, List[float]] = defaultdict(list)
    for tx in model_txns:
        category_amounts[str(tx.get("category_id") or "")].append(safe_float(tx.get("amount")))
        counterparty_amounts[str(tx.get("counterparty") or "UNKNOWN")].append(safe_float(tx.get("amount")))

    features: List[List[float]] = []
    items: List[Dict[str, Any]] = []
    for tx in model_txns:
        amount = safe_float(tx.get("amount"))
        occurred = parse_datetime(tx.get("occurred_at")) or now_utc()
        category_id = str(tx.get("category_id") or "")
        category_values = category_amounts.get(category_id) or [amount]
        category_median = _median(category_values)
        category_sigma = max(1.0, _mad(category_values, category_median) * 1.4826)
        counterparty = str(tx.get("counterparty") or "UNKNOWN")
        counterparty_values = counterparty_amounts.get(counterparty) or [amount]
        counterparty_median = _median(counterparty_values)
        relative_counterparty_delta = abs(safe_div(amount - counterparty_median, max(counterparty_median, 1.0)))
        regular_credit_pattern = (
            str(tx.get("direction") or "debit").lower() == "credit"
            and merchant_counts[counterparty] >= 3
            and relative_counterparty_delta <= 0.2
        )
        features.append(
            [
                math.log1p(max(0.0, amount)),
                float(occurred.hour),
                float(occurred.weekday()),
                float(merchant_counts[counterparty]),
                safe_div(amount - user_median, user_sigma),
                safe_div(amount - category_median, category_sigma),
                1.0 if str(tx.get("direction") or "debit").lower() == "credit" else 0.0,
            ]
        )
        items.append(
            {
                "transaction_id": str(tx.get("id") or ""),
                "occurred_at": iso_utc(occurred),
                "amount": round(amount, 2),
                "direction": str(tx.get("direction") or "debit").lower(),
                "counterparty": counterparty,
                "category_name": category_name_by_id.get(category_id, "Unknown"),
                "_suppressed_user_facing": regular_credit_pattern,
            }
        )

    x = np.asarray(features, dtype=float)
    model = ECOD(contamination=0.1)
    model.fit(x)
    scores = [float(value) for value in model.decision_scores_]
    labels = [int(value) for value in model.labels_]

    try:
        probability_rows = model.predict_proba(x, method="linear")
        outlier_probabilities = [float(row[1]) for row in probability_rows]
    except Exception:
        outlier_probabilities = [0.0 for _ in items]

    try:
        prediction_confidences = [float(value) for value in model.predict_confidence(x)]
    except Exception:
        prediction_confidences = [0.0 for _ in items]

    rejection_labels = [label for label in labels]
    rejection_stats: Dict[str, Any] | None = None
    try:
        reject_predictions, expected_rejection_rate, upperbound_rejection_rate, upperbound_cost = model.predict_with_rejection(
            x,
            T=32,
            return_stats=True,
            c_r=0.1,
        )
        rejection_labels = [int(value) for value in reject_predictions]
        rejection_stats = {
            "expected_rejection_rate": round(float(expected_rejection_rate), 6),
            "upperbound_rejection_rate": round(float(upperbound_rejection_rate), 6),
            "upperbound_cost": round(float(upperbound_cost), 6),
        }
    except Exception:
        rejection_labels = [label for label in labels]

    enriched: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        score = scores[idx]
        probability = outlier_probabilities[idx] if idx < len(outlier_probabilities) else 0.0
        prediction_confidence = prediction_confidences[idx] if idx < len(prediction_confidences) else 0.0
        rejection_label = rejection_labels[idx] if idx < len(rejection_labels) else labels[idx]
        enriched.append(
            {
                **item,
                "decision_score": round(score, 6),
                "outlier_probability": round(probability, 6),
                "prediction_confidence": round(prediction_confidence, 6),
                "predict_label": int(labels[idx]),
                "rejection_label": int(rejection_label),
                "rejected_low_confidence": bool(rejection_label == -2),
                "score": round(score, 6),
                "proba": round(probability, 6),
                "confidence_score": round(clamp(prediction_confidence), 4),
                "reject": bool(labels[idx] == 1 and probability >= 0.95),
            }
        )

    enriched.sort(key=lambda row: row["score"], reverse=True)
    suppressed_user_facing_count = sum(1 for row in enriched if bool(row.get("_suppressed_user_facing")))
    visible_items = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in enriched
        if not bool(row.get("_suppressed_user_facing"))
    ]
    top_items = visible_items[:10]
    return {
        "available": True,
        "ready": True,
        "fit_scope": fit_scope,
        "evaluated_transaction_count": len(model_txns),
        "suppressed_credit_candidate_count": suppressed_credit_candidate_count,
        "items": top_items,
        "summary": {
            "outlier_ratio": round(sum(1 for row in top_items if row["predict_label"] == 1) / len(top_items), 4) if top_items else 0.0,
            "top_probability": top_items[0]["outlier_probability"] if top_items else 0.0,
            "top_prediction_confidence": top_items[0]["prediction_confidence"] if top_items else 0.0,
            "rejected_ratio": round(sum(1 for row in top_items if row["rejected_low_confidence"]) / len(top_items), 4) if top_items else 0.0,
            "visible_item_count": len(top_items),
            "suppressed_user_facing_count": suppressed_user_facing_count,
            "rejection_stats": rejection_stats,
        },
    }


def _build_feedback_request(
    *,
    trace_id: str,
    flags: List[str],
    tx_outlier_pack: Dict[str, Any],
    confidence_score: float,
    as_of: str,
) -> Dict[str, Any]:
    has_user_facing_signal = bool(flags) or bool(tx_outlier_pack.get("items"))
    return {
        "show_to_user": bool(has_user_facing_signal),
        "reason": "user_facing_anomaly_present" if has_user_facing_signal else "no_user_facing_anomaly",
        "trace_id": trace_id,
        "feedback_tool_name": "record_anomaly_feedback_v1",
        "prompt_type": "anomaly_verification",
        "prompt": "Sau khi hien thi ket qua anomaly, yeu cau nguoi dung xac nhan alert nay co dung khong.",
        "recommended_when": "Show after anomaly_signals_v1 whenever flags is non-empty or transaction_outliers.items is non-empty.",
        "options": anomaly_feedback_options(),
        "default_target": {
            "entity_type": "other",
            "entity_id": trace_id,
            "anomaly_type": "trace_review",
            "detector_name": "human_review",
        },
        "source_snapshot": {
            "trace_id": trace_id,
            "confidence_score": round(clamp(confidence_score), 4),
            "flags": list(flags),
            "as_of": as_of,
        },
        "signal_count": len(flags),
        "confidence_score": round(clamp(confidence_score), 4),
    }


def _latest_balance_snapshot(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "latest_balance": 0.0,
            "balance_quality": 0.0,
            "quality_flag": "missing",
            "source": "income_sources_proxy",
            "latest_date": None,
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
    }


def _apply_feedback(
    tx_outlier_pack: Dict[str, Any],
    merchant_spikes: List[Dict[str, Any]],
    feedback_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    feedback_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in feedback_rows:
        entity_type = str(row.get("entity_type") or "")
        entity_id = str(row.get("entity_id") or "")
        if not entity_type or not entity_id:
            continue
        key = (entity_type, entity_id)
        if key not in feedback_index:
            feedback_index[key] = row

    suppressed_transactions = 0
    confirmed_transactions = 0
    adjusted_items: List[Dict[str, Any]] = []
    for item in list(tx_outlier_pack.get("items") or []):
        feedback = feedback_index.get(("transaction", str(item.get("transaction_id") or "")))
        if not feedback:
            feedback = feedback_index.get(("merchant", str(item.get("counterparty") or "")))
        adjusted = dict(item)
        if feedback:
            label = str(feedback.get("feedback_label") or "")
            adjusted["feedback_label"] = label
            adjusted["feedback_source"] = str(feedback.get("feedback_source") or "")
            adjusted["feedback_adjusted"] = True
            if label in {"false_positive", "expected"}:
                if adjusted.get("reject"):
                    suppressed_transactions += 1
                adjusted["reject"] = False
                adjusted["suppressed_by_feedback"] = True
            elif label == "confirmed":
                confirmed_transactions += 1
        adjusted_items.append(adjusted)

    adjusted_merchant_spikes: List[Dict[str, Any]] = []
    feedback_merchant_matches = 0
    for row in merchant_spikes:
        feedback = feedback_index.get(("merchant", str(row.get("merchant") or "")))
        adjusted = dict(row)
        if feedback:
            feedback_merchant_matches += 1
            adjusted["feedback_label"] = str(feedback.get("feedback_label") or "")
            adjusted["feedback_source"] = str(feedback.get("feedback_source") or "")
        adjusted_merchant_spikes.append(adjusted)

    total_feedback = len(feedback_rows)
    contradictory = suppressed_transactions
    feedback_alignment = 1.0 if total_feedback == 0 else clamp(1.0 - safe_div(contradictory, max(total_feedback, 1), 0.0))
    return {
        "tx_outlier_pack": {
            **tx_outlier_pack,
            "items": adjusted_items,
            "summary": {
                **dict(tx_outlier_pack.get("summary") or {}),
                "suppressed_by_feedback": suppressed_transactions,
                "confirmed_by_feedback": confirmed_transactions,
            },
        },
        "merchant_spikes": adjusted_merchant_spikes,
        "feedback_summary": {
            "feedback_row_count": total_feedback,
            "suppressed_transactions": suppressed_transactions,
            "confirmed_transactions": confirmed_transactions,
            "merchant_feedback_matches": feedback_merchant_matches,
        },
        "feedback_alignment": round(feedback_alignment, 4),
    }


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
    balance_rows = fetch_balance_daily(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    feedback_rows = fetch_anomaly_feedback(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    feedback_history_rows = fetch_anomaly_feedback(
        sql,
        user_id=user_id,
        start_at=daterange_start(as_of_dt, 365),
        end_at=as_of_dt,
    )
    audit_rows = fetch_audit_events(
        sql,
        user_id=user_id,
        start_at=daterange_start(as_of_dt, 365),
        end_at=as_of_dt,
        event_type=TOOL_NAME,
    )
    category_name_by_id = {str(item.get("id")): str(item.get("name") or "Unknown") for item in categories}

    dense_rows = _dense_daily_rows(txns, start_dt=start_dt, end_dt=as_of_dt)
    day_keys = [row["day"] for row in dense_rows]
    spend_series = [row["spend"] for row in dense_rows]
    income_series = [row["income"] for row in dense_rows]
    net_series = [row["net"] for row in dense_rows]
    has_observed_activity = bool(txns) or any(abs(value) > 1e-9 for value in spend_series) or any(abs(value) > 1e-9 for value in income_series)

    recent_30_category_spend: Dict[str, float] = defaultdict(float)
    prior_60_category_spend: Dict[str, float] = defaultdict(float)
    recent_30_merchant_spend: Dict[str, float] = defaultdict(float)
    prior_60_merchant_spend: Dict[str, float] = defaultdict(float)
    recent_cutoff = as_of_dt - timedelta(days=29)
    prior_cutoff = as_of_dt - timedelta(days=89)

    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred or str(tx.get("direction") or "debit").lower() == "credit":
            continue
        amount = safe_float(tx.get("amount"))
        category_id = str(tx.get("category_id") or "")
        counterparty = str(tx.get("counterparty") or "UNKNOWN")
        if occurred >= recent_cutoff:
            recent_30_category_spend[category_id] += amount
            recent_30_merchant_spend[counterparty] += amount
        elif occurred >= prior_cutoff:
            prior_60_category_spend[category_id] += amount
            prior_60_merchant_spend[counterparty] += amount

    river_result = river_adwin_drift(spend_series)
    pyod_result = pyod_ecod_outlier(spend_series)
    ruptures_result = ruptures_pelt_change_points(day_keys, spend_series, penalty=3.0)
    tx_outlier_pack = _transaction_outliers(txns, category_name_by_id)

    median_spend = _median(spend_series)
    mad_spend = _mad(spend_series, median_spend)
    robust_sigma = mad_spend * 1.4826 if mad_spend > 0 else 0.0
    recent_spend_avg = mean(spend_series[-7:])
    z_score = safe_div(recent_spend_avg - median_spend, robust_sigma) if robust_sigma > 0 else 0.0

    recent_income_avg = mean(income_series[-30:])
    prior_income_avg = mean(income_series[-90:-30]) if len(income_series) > 30 else 0.0
    income_drop_pct = max(0.0, safe_div(prior_income_avg - recent_income_avg, prior_income_avg)) if prior_income_avg > 0 else 0.0

    category_spikes = [
        {
            "category_id": row["id"],
            "category_name": row["name"],
            "recent_amount": row["recent_amount"],
            "baseline_amount": row["baseline_amount"],
            "delta_share": row["delta_share"],
        }
        for row in _build_spike_rows(recent_30_category_spend, prior_60_category_spend, name_lookup=category_name_by_id)
    ]
    merchant_spikes = [
        {
            "merchant": row["name"],
            "recent_amount": row["recent_amount"],
            "baseline_amount": row["baseline_amount"],
            "delta_share": row["delta_share"],
        }
        for row in _build_spike_rows(recent_30_merchant_spend, prior_60_merchant_spend)
    ]
    feedback_adjustment = _apply_feedback(tx_outlier_pack, merchant_spikes, feedback_rows)
    tx_outlier_pack = feedback_adjustment["tx_outlier_pack"]
    merchant_spikes = feedback_adjustment["merchant_spikes"]
    feedback_summary = feedback_adjustment["feedback_summary"]
    feedback_alignment = safe_float(feedback_adjustment["feedback_alignment"])

    cash_buffer_proxy = sum(safe_float(item.get("monthly_amount")) for item in income_sources)
    balance_snapshot = _latest_balance_snapshot(balance_rows)
    avg_daily_net = mean(net_series[-30:])
    runway_days = 9999.0
    available_balance = safe_float(balance_snapshot.get("latest_balance")) if balance_snapshot["available"] else cash_buffer_proxy
    if avg_daily_net < 0 and available_balance > 0:
        runway_days = available_balance / abs(avg_daily_net)

    abnormal_spend_flag = has_observed_activity and (z_score >= 2.5 or bool(river_result.get("drift_detected")) or bool(pyod_result.get("outlier_flag")))
    income_drop_flag = has_observed_activity and income_drop_pct >= 0.25
    low_balance_flag = has_observed_activity and runway_days < 90

    detector_flags = {
        "robust_z": abnormal_spend_flag,
        "river_adwin": bool(river_result.get("drift_detected")),
        "pyod_daily": bool(pyod_result.get("outlier_flag")),
        "ruptures": bool(ruptures_result.get("change_detected")),
        "pyod_transaction": bool(tx_outlier_pack.get("items")),
    }
    available_detectors = [
        name for name, available in {
            "robust_z": True,
            "river_adwin": river_result.get("available", False),
            "pyod_daily": pyod_result.get("available", False),
            "ruptures": ruptures_result.get("available", False),
            "pyod_transaction": tx_outlier_pack.get("available", False),
        }.items()
        if available
    ]
    positive_detectors = [name for name in available_detectors if detector_flags.get(name)] if has_observed_activity else []
    detector_agreement_score = safe_div(len(positive_detectors), len(available_detectors)) if has_observed_activity else 0.0
    sample_sufficiency = clamp(len(txns) / 180.0)
    signal_strength = (
        clamp(
            max(
                abs(z_score) / 4.0,
                income_drop_pct,
                max((row["delta_share"] for row in category_spikes), default=0.0),
                safe_float(tx_outlier_pack.get("summary", {}).get("top_probability"), 0.0),
            )
        )
        if has_observed_activity
        else 0.0
    )
    stability_penalty_inverse = clamp(1.0 - max(0.0, abs(z_score) - 2.0) / 4.0)
    tx_confidence = safe_float(tx_outlier_pack.get("summary", {}).get("top_probability"), 0.0) if has_observed_activity else 0.0
    balance_data_quality = balance_snapshot["balance_quality"] if balance_snapshot["available"] else 0.45
    confidence_score = weighted_score(
        {
            "agreement": detector_agreement_score,
            "pyod_confidence": tx_confidence,
            "sample": sample_sufficiency,
            "signal": signal_strength,
            "stability": stability_penalty_inverse,
            "balance_data_quality": balance_data_quality,
            "feedback_alignment": feedback_alignment,
        },
        {
            "agreement": 0.25,
            "pyod_confidence": 0.2,
            "sample": 0.15,
            "signal": 0.15,
            "stability": 0.1,
            "balance_data_quality": 0.1,
            "feedback_alignment": 0.05,
        },
    )
    reason_codes = []
    if not txns:
        reason_codes.append("no_transactions_in_window")
    if len(available_detectors) < 3:
        reason_codes.append("detector_availability_low")
    if detector_agreement_score < 0.4 and signal_strength < 0.4:
        reason_codes.append("detector_disagreement")
    if sample_sufficiency < 0.5:
        reason_codes.append("sample_sufficiency_low")
    if not balance_snapshot["available"] and low_balance_flag:
        reason_codes.append("runway_proxy_used")
        reason_codes.append("balance_proxy_used")
    if balance_snapshot["available"] and balance_snapshot["balance_quality"] < 0.75:
        reason_codes.append("balance_quality_low")

    flags = []
    if abnormal_spend_flag:
        flags.append("abnormal_spend")
    if bool(river_result.get("drift_detected")):
        flags.append("spend_drift")
    if has_observed_activity and (bool(pyod_result.get("outlier_flag")) or tx_outlier_pack.get("items")):
        flags.append("spend_outlier")
    if bool(ruptures_result.get("change_detected")):
        flags.append("change_point")
    if income_drop_flag:
        flags.append("income_drop")
    if category_spikes:
        flags.append("category_spike")
    if merchant_spikes:
        flags.append("merchant_spike")
    if low_balance_flag:
        flags.append("low_balance_risk")
    flags = sorted(set(flags))

    daily_native_confidence = safe_float(pyod_result.get("prediction_confidence"), 0.0)
    daily_native_probability = safe_float(pyod_result.get("outlier_probability"), 0.0)
    top_tx_item = (tx_outlier_pack.get("items") or [None])[0]
    top_tx_probability = safe_float((top_tx_item or {}).get("outlier_probability"), 0.0)
    top_tx_confidence = safe_float((top_tx_item or {}).get("prediction_confidence"), 0.0)
    native_confidence_score = max(daily_native_confidence, top_tx_confidence)
    recalibration_dataset = build_anomaly_recalibration_dataset(
        audit_rows=audit_rows,
        feedback_rows=feedback_history_rows,
    )
    recalibration = fit_recalibrated_probability(
        raw_score=confidence_score,
        samples=recalibration_dataset.get("samples") or [],
        min_positive_rate=0.05,
        max_positive_rate=0.95,
    )

    runtime_alerts = {
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
        "category_spike": {"flag": bool(category_spikes), "rows": category_spikes},
        "merchant_spike": {"flag": bool(merchant_spikes), "rows": merchant_spikes},
        "low_balance_risk": {
            "flag": low_balance_flag,
            "runway_days_estimate": round(runway_days, 2) if runway_days != 9999.0 else 9999,
            "available_balance_estimate": round(available_balance, 2),
            "source": "balance_daily" if balance_snapshot["available"] else "income_sources_proxy",
            "quality_flag": balance_snapshot.get("quality_flag"),
            "avg_daily_net": round(avg_daily_net, 2),
        },
    }
    anomaly_confidence_bucket = "high" if confidence_score >= 0.8 else ("medium" if confidence_score >= 0.6 else "low")
    detector_availability_ratio = round(safe_div(len(available_detectors), 5.0), 4)
    monitoring_status = "healthy"
    if sample_sufficiency < 0.5 or detector_availability_ratio < 0.6:
        monitoring_status = "watch"
    trace_feedback_coverage = safe_float(recalibration_dataset.get("trace_feedback_coverage"), 0.0)
    if trace_feedback_coverage < 0.1:
        monitoring_status = "watch"
    if confidence_score < 0.4:
        monitoring_status = "alert"

    tool_input = {
        "user_id": user_id,
        "lookback_days": lookback,
        "as_of": iso_utc(as_of_dt),
    }
    feedback_request = _build_feedback_request(
        trace_id=trace,
        flags=flags,
        tx_outlier_pack=tx_outlier_pack,
        confidence_score=confidence_score,
        as_of=iso_utc(as_of_dt),
    )
    payload = {
        "lookback_days": lookback,
        "abnormal_spend": runtime_alerts["abnormal_spend"],
        "income_drop": runtime_alerts["income_drop"],
        "category_spikes": category_spikes,
        "merchant_spikes": merchant_spikes,
        "low_balance_risk": runtime_alerts["low_balance_risk"],
        "runtime_alerts": runtime_alerts,
        "transaction_outliers": tx_outlier_pack,
        "feedback_summary": feedback_summary,
        "feedback_request": feedback_request,
        "regime_changes": {
            "change_points": ruptures_result.get("change_points", []),
            "change_detected": bool(ruptures_result.get("change_detected")),
        },
        "detector_agreement": {
            "available_detectors": available_detectors,
            "positive_detectors": positive_detectors,
            "agreement_score": round(detector_agreement_score, 4),
        },
        "flags": flags,
        "external_engines": {
            "river_adwin": river_result,
            "pyod_ecod": pyod_result,
            "ruptures_pelt": ruptures_result,
        },
    }
    reliability = build_reliability(
        confidence_score=confidence_score,
        components={
            "detector_agreement": detector_agreement_score,
            "sample_sufficiency": sample_sufficiency,
            "signal_strength": signal_strength,
            "pyod_confidence": tx_confidence,
            "stability": stability_penalty_inverse,
            "balance_data_quality": balance_data_quality,
            "feedback_alignment": feedback_alignment,
        },
        reason_codes=reason_codes,
    )
    anomaly_outcomes = count_latest_anomaly_feedback(feedback_history_rows, tool_name=TOOL_NAME)
    trust_bundle = build_trust(
        confidence_score=safe_float(reliability["confidence_score"]),
        reliability_components=reliability.get("components"),
        abstain_recommended=bool(reliability.get("abstain_recommended")),
        prior_alpha=6.0,
        prior_beta=4.0,
        monitoring_status=monitoring_status,
        success_count=anomaly_outcomes["success_count"],
        failure_count=anomaly_outcomes["failure_count"],
        human_feedback_recommended=bool(feedback_request.get("show_to_user")),
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
        model_evidence=build_model_evidence(
            native_confidence=build_native_confidence(
                source="pyod_predict_confidence",
                score=native_confidence_score,
                daily_detector={
                    "engine": pyod_result.get("engine"),
                    "decision_score": pyod_result.get("decision_score"),
                    "outlier_probability": daily_native_probability,
                    "prediction_confidence": daily_native_confidence,
                    "rejected_low_confidence": pyod_result.get("rejected_low_confidence"),
                },
                transaction_detector={
                    "engine": "pyod_ecod_transaction",
                    "top_outlier_probability": top_tx_probability,
                    "top_prediction_confidence": top_tx_confidence,
                    "top_rejected_low_confidence": bool((top_tx_item or {}).get("rejected_low_confidence")),
                    "item_count": len(tx_outlier_pack.get("items") or []),
                },
            )
        ),
        provenance=build_provenance(
            library="river+pyod+ruptures",
            model="ensemble_anomaly_detector_v2",
            model_version="anomaly_v2",
            feature_set_version="transaction_anomaly_features_v2",
        ),
        validation=build_validation(
            tx_count=len(txns),
            daily_points=len(dense_rows),
            detector_count=len(available_detectors),
            balance_row_count=len(balance_rows),
            feedback_row_count=len(feedback_rows),
            feedback_history_row_count=len(feedback_history_rows),
            calibration_monitoring={
                "confidence_score": round(confidence_score, 4),
                "confidence_bucket": anomaly_confidence_bucket,
                "native_confidence_score": round(native_confidence_score, 4),
                "calibrated_confidence_score": recalibration.get("calibrated_score"),
                "recalibration": recalibration,
                "total_trace_count": int(recalibration_dataset.get("total_trace_count") or 0),
                "feedback_trace_count": int(recalibration_dataset.get("feedback_trace_count") or 0),
                "labeled_trace_count": int(recalibration_dataset.get("labeled_trace_count") or 0),
                "fallback_trace_count": int(recalibration_dataset.get("fallback_trace_count") or 0),
                "trace_feedback_coverage": round(trace_feedback_coverage, 4),
                "positive_rate_labeled": recalibration_dataset.get("positive_rate_labeled"),
                "recalibration_data_status": "enabled" if recalibration.get("available") else "disabled_by_data",
                "detector_availability_ratio": detector_availability_ratio,
                "sample_sufficiency": round(sample_sufficiency, 4),
                "feedback_alignment": round(feedback_alignment, 4),
                "monitoring_status": monitoring_status,
            },
            native_diagnostics={
                "pyod_daily": {
                    "threshold": pyod_result.get("threshold"),
                    "rejection_stats": pyod_result.get("rejection_stats"),
                },
                "pyod_transaction": {
                    "rejection_stats": tx_outlier_pack.get("summary", {}).get("rejection_stats"),
                    "rejected_ratio": tx_outlier_pack.get("summary", {}).get("rejected_ratio"),
                },
            },
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
                "flags": flags,
                "confidence_score": result.get("reliability", {}).get("confidence_score"),
            },
        },
    )
    return result


