from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import (
    SERVICE_SIGNAL_ANOMALY_RECENT_MIN_FLAGS,
    SERVICE_SIGNAL_GOAL_GAP_HIGH_AMOUNT,
    SERVICE_SIGNAL_OVESPEND_HIGH,
    SERVICE_SIGNAL_RUNWAY_LOW_MONTHS,
    SERVICE_SIGNAL_VOLATILITY_HIGH,
)


@dataclass
class ServiceSignalSet:
    signals: list[str] = field(default_factory=list)
    source_fact_ids: dict[str, list[str]] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _find_first_by_prefix(facts: list[Any], prefix: str) -> Any | None:
    for fact in facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        if fact_id.startswith(prefix):
            return fact
    return None


def _find_exact(facts: list[Any], fact_id: str) -> Any | None:
    for fact in facts:
        if str(getattr(fact, "fact_id", "") or "").strip() == fact_id:
            return fact
    return None


def _append_signal(
    bucket: dict[str, list[str]],
    *,
    signal: str,
    fact_id: str | None,
) -> None:
    if not signal:
        return
    rows = bucket.setdefault(signal, [])
    if fact_id and fact_id not in rows:
        rows.append(fact_id)


def _risk_signal_from_context(policy_flags: dict[str, Any], facts: list[Any]) -> str:
    risk_appetite = str((policy_flags or {}).get("risk_appetite") or "").strip().lower()
    if risk_appetite in {"conservative", "moderate", "aggressive"}:
        return f"risk_{risk_appetite}"

    slot_fact = _find_exact(facts, "slot.risk_appetite")
    if slot_fact is not None:
        value = str(getattr(slot_fact, "value", "") or "").strip().lower()
        if value in {"conservative", "moderate", "aggressive"}:
            return f"risk_{value}"

    risk_band_fact = _find_first_by_prefix(facts, "risk.risk_band.")
    if risk_band_fact is not None:
        risk_band = str(getattr(risk_band_fact, "value", "") or "").strip().lower()
        mapping = {
            "low": "risk_conservative",
            "conservative": "risk_conservative",
            "medium": "risk_moderate",
            "moderate": "risk_moderate",
            "high": "risk_aggressive",
            "aggressive": "risk_aggressive",
        }
        signal = mapping.get(risk_band, "")
        if signal:
            return signal

    return "risk_unknown"


def extract_service_signals(
    *,
    facts: list[Any],
    policy_flags: dict[str, Any] | None = None,
) -> ServiceSignalSet:
    policy = policy_flags or {}
    source_fact_ids: dict[str, list[str]] = {}

    net_fact = _find_first_by_prefix(facts, "spend.net_cashflow.")
    net_value = _safe_float(getattr(net_fact, "value", 0.0) if net_fact is not None else 0.0)
    if net_fact is not None:
        if net_value < 0:
            _append_signal(source_fact_ids, signal="cashflow_negative", fact_id=getattr(net_fact, "fact_id", ""))
        elif net_value > 0:
            _append_signal(source_fact_ids, signal="cashflow_positive", fact_id=getattr(net_fact, "fact_id", ""))

    anomaly_fact = _find_first_by_prefix(facts, "anomaly.flags_count.")
    anomaly_count = _safe_float(getattr(anomaly_fact, "value", 0.0) if anomaly_fact is not None else 0.0)
    if anomaly_fact is not None and anomaly_count >= float(SERVICE_SIGNAL_ANOMALY_RECENT_MIN_FLAGS):
        _append_signal(source_fact_ids, signal="anomaly_recent", fact_id=getattr(anomaly_fact, "fact_id", ""))

    goal_gap_fact = _find_exact(facts, "goal.gap_amount")
    goal_gap_value = _safe_float(getattr(goal_gap_fact, "value", 0.0) if goal_gap_fact is not None else 0.0)
    if goal_gap_fact is not None and goal_gap_value > float(SERVICE_SIGNAL_GOAL_GAP_HIGH_AMOUNT):
        _append_signal(source_fact_ids, signal="goal_gap_high", fact_id=getattr(goal_gap_fact, "fact_id", ""))

    overspend_fact = _find_first_by_prefix(facts, "risk.overspend_propensity.")
    overspend_value = _safe_float(getattr(overspend_fact, "value", 0.0) if overspend_fact is not None else 0.0)
    if overspend_fact is not None and overspend_value >= float(SERVICE_SIGNAL_OVESPEND_HIGH):
        _append_signal(source_fact_ids, signal="overspend_high", fact_id=getattr(overspend_fact, "fact_id", ""))

    runway_fact = _find_first_by_prefix(facts, "risk.runway_months.")
    runway_value = _safe_float(getattr(runway_fact, "value", 0.0) if runway_fact is not None else 0.0)
    if runway_fact is not None and runway_value > 0 and runway_value < float(SERVICE_SIGNAL_RUNWAY_LOW_MONTHS):
        _append_signal(source_fact_ids, signal="runway_low", fact_id=getattr(runway_fact, "fact_id", ""))

    volatility_fact = _find_first_by_prefix(facts, "risk.cashflow_volatility.")
    volatility_value = _safe_float(getattr(volatility_fact, "value", 0.0) if volatility_fact is not None else 0.0)
    if volatility_fact is not None and volatility_value >= float(SERVICE_SIGNAL_VOLATILITY_HIGH):
        _append_signal(source_fact_ids, signal="volatility_high", fact_id=getattr(volatility_fact, "fact_id", ""))

    goal_status_fact = _find_exact(facts, "goal.status")
    goal_status = str(getattr(goal_status_fact, "value", "") if goal_status_fact is not None else "").strip().lower()
    if goal_status.startswith("insufficient_"):
        _append_signal(source_fact_ids, signal="goal_input_missing", fact_id=getattr(goal_status_fact, "fact_id", ""))

    jar_status_fact = _find_exact(facts, "jar.status")
    jar_status = str(getattr(jar_status_fact, "value", "") if jar_status_fact is not None else "").strip().lower()
    if jar_status.startswith("insufficient_"):
        _append_signal(source_fact_ids, signal="jar_data_missing", fact_id=getattr(jar_status_fact, "fact_id", ""))

    risk_signal = _risk_signal_from_context(policy, facts)
    _append_signal(source_fact_ids, signal=risk_signal, fact_id=None)

    signals = sorted(source_fact_ids.keys())
    thresholds = {
        "overspend_high": float(SERVICE_SIGNAL_OVESPEND_HIGH),
        "runway_low_months": float(SERVICE_SIGNAL_RUNWAY_LOW_MONTHS),
        "volatility_high": float(SERVICE_SIGNAL_VOLATILITY_HIGH),
        "goal_gap_high_amount": float(SERVICE_SIGNAL_GOAL_GAP_HIGH_AMOUNT),
        "anomaly_recent_min_flags": float(SERVICE_SIGNAL_ANOMALY_RECENT_MIN_FLAGS),
    }
    return ServiceSignalSet(signals=signals, source_fact_ids=source_fact_ids, thresholds=thresholds)
