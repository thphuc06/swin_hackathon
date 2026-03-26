from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from .common import clamp, parse_datetime, safe_float

TRUST_HIGH_THRESHOLD = 0.85
TRUST_MEDIUM_THRESHOLD = 0.65
TRUST_ADVISORY_THRESHOLD = 0.45


def compute_component_mean(
    components: Mapping[str, Any] | None,
    *,
    fallback_score: float,
) -> float:
    values = [clamp(safe_float(value)) for value in (components or {}).values()]
    if not values:
        return round(clamp(safe_float(fallback_score)), 4)
    return round(sum(values) / len(values), 4)


def compute_cold_start_trust(confidence_score: float, component_mean: float) -> float:
    runtime_health = 0.5 + 0.5 * clamp(safe_float(component_mean))
    return round(clamp(clamp(safe_float(confidence_score)) * runtime_health), 4)


def compute_beta_posterior(
    *,
    alpha: float,
    beta: float,
    success_count: int,
    failure_count: int,
) -> Dict[str, Any]:
    alpha_prior = max(1e-9, safe_float(alpha, 1.0))
    beta_prior = max(1e-9, safe_float(beta, 1.0))
    successes = max(0, int(success_count or 0))
    failures = max(0, int(failure_count or 0))
    posterior_alpha = alpha_prior + successes
    posterior_beta = beta_prior + failures
    prior_mean = clamp(alpha_prior / (alpha_prior + beta_prior))
    posterior_mean = clamp(posterior_alpha / (posterior_alpha + posterior_beta))

    conservative_p05 = None
    try:
        from scipy.stats import beta as scipy_beta

        conservative_p05 = round(
            clamp(float(scipy_beta.ppf(0.05, posterior_alpha, posterior_beta))),
            4,
        )
    except Exception:
        conservative_p05 = None

    return {
        "alpha": round(alpha_prior, 4),
        "beta": round(beta_prior, 4),
        "prior_mean": round(prior_mean, 4),
        "sample_count": successes + failures,
        "success_count": successes,
        "failure_count": failures,
        "posterior_mean": round(posterior_mean, 4),
        "conservative_p05": conservative_p05,
    }


def compute_trust_score(cold_start_trust: float, prior_mean: float, posterior_mean: float) -> float:
    normalized_prior = max(1e-9, clamp(safe_float(prior_mean)))
    return round(clamp(clamp(safe_float(cold_start_trust)) * clamp(safe_float(posterior_mean)) / normalized_prior), 4)


def compute_trust_level(score: float) -> str:
    value = clamp(safe_float(score))
    if value >= TRUST_HIGH_THRESHOLD:
        return "high"
    if value >= TRUST_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def normalize_monitoring_status(monitoring_status: str | None, confidence_score: float) -> str:
    normalized = str(monitoring_status or "").strip().lower()
    if normalized in {"healthy", "watch", "alert", "insufficient_data"}:
        return normalized
    value = clamp(safe_float(confidence_score))
    if value >= 0.6:
        return "healthy"
    if value >= 0.4:
        return "watch"
    return "alert"


def compute_usage_mode(
    score: float,
    monitoring_status: str,
    abstain_recommended: bool,
    human_feedback_recommended: bool,
) -> str:
    normalized_score = clamp(safe_float(score))
    if bool(abstain_recommended) or normalized_score < TRUST_ADVISORY_THRESHOLD:
        return "abstain"
    if monitoring_status == "alert":
        return "advisory_only"
    if normalized_score >= TRUST_HIGH_THRESHOLD:
        return "cautious" if human_feedback_recommended else "direct"
    if normalized_score >= TRUST_MEDIUM_THRESHOLD:
        return "cautious"
    return "advisory_only"


def build_trust(
    *,
    confidence_score: float,
    reliability_components: Mapping[str, Any] | None,
    abstain_recommended: bool,
    prior_alpha: float,
    prior_beta: float,
    monitoring_status: str | None = None,
    success_count: int = 0,
    failure_count: int = 0,
    human_feedback_recommended: bool = False,
    cap_score: float | None = None,
    cap_reason: str | None = None,
    cap_method: str | None = None,
) -> Dict[str, Any]:
    base_confidence = round(clamp(safe_float(confidence_score)), 4)
    component_mean = compute_component_mean(reliability_components, fallback_score=base_confidence)
    runtime_health = round(0.5 + 0.5 * component_mean, 4)
    cold_start_trust = compute_cold_start_trust(base_confidence, component_mean)
    posterior = compute_beta_posterior(
        alpha=prior_alpha,
        beta=prior_beta,
        success_count=success_count,
        failure_count=failure_count,
    )
    sample_count = int(posterior["sample_count"])
    cold_start = sample_count == 0
    trust_score = cold_start_trust if cold_start else compute_trust_score(cold_start_trust, posterior["prior_mean"], posterior["posterior_mean"])
    method = "cold_start" if cold_start else "posterior_beta_binomial"
    caps_applied: list[str] = []
    normalized_cap_score = safe_float(cap_score, None)
    if normalized_cap_score is not None and clamp(normalized_cap_score) < trust_score:
        trust_score = round(clamp(normalized_cap_score), 4)
        cap_name = str(cap_reason or "external_trust_cap")
        caps_applied.append(cap_name)
        if cap_name == "forecast_trust_cap":
            method = f"{str(cap_method or method)}_capped_by_forecast"

    trust_level = compute_trust_level(trust_score)
    resolved_monitoring_status = normalize_monitoring_status(monitoring_status, base_confidence)
    usage_mode = compute_usage_mode(
        trust_score,
        resolved_monitoring_status,
        bool(abstain_recommended),
        bool(human_feedback_recommended),
    )
    agent_use = {
        "usage_mode": usage_mode,
        "automation_allowed": usage_mode == "direct",
        "human_feedback_recommended": bool(human_feedback_recommended),
        "primary_confidence_field": "trust.trust_score",
        "secondary_confidence_field": "reliability.confidence_score",
        "monitoring_status": resolved_monitoring_status,
    }
    trust = {
        "trust_score": round(clamp(trust_score), 4),
        "trust_level": trust_level,
        "cold_start": cold_start,
        "method": method,
        "runtime": {
            "base_confidence_score": base_confidence,
            "component_mean": component_mean,
            "runtime_health": runtime_health,
            "cold_start_trust": cold_start_trust,
        },
        "prior": {
            "alpha": posterior["alpha"],
            "beta": posterior["beta"],
            "prior_mean": posterior["prior_mean"],
        },
        "posterior": {
            "sample_count": sample_count,
            "success_count": posterior["success_count"],
            "failure_count": posterior["failure_count"],
            "posterior_mean": posterior["posterior_mean"],
            "conservative_p05": posterior["conservative_p05"],
        },
        "caps_applied": caps_applied,
    }
    return {"trust": trust, "agent_use": agent_use}


def count_binary_outcomes(rows: Iterable[Dict[str, Any]], *, positive_key: str) -> Dict[str, int]:
    success_count = 0
    failure_count = 0
    for row in rows:
        value = row.get(positive_key)
        if value is None:
            continue
        if bool(value):
            success_count += 1
        else:
            failure_count += 1
    return {
        "sample_count": success_count + failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
    }


def count_latest_anomaly_feedback(
    rows: Iterable[Dict[str, Any]],
    *,
    tool_name: str,
) -> Dict[str, int]:
    latest_by_trace: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if str(row.get("tool_name") or "").strip() != tool_name:
            continue
        trace_id = str(row.get("trace_id") or "").strip()
        if not trace_id:
            continue
        label_text = str(row.get("feedback_label") or "").strip().lower()
        if label_text == "confirmed":
            label = 1
        elif label_text in {"false_positive", "expected"}:
            label = 0
        else:
            continue
        created_at = parse_datetime(row.get("created_at"))
        current = latest_by_trace.get(trace_id)
        current_created_at = parse_datetime(current.get("created_at")) if current else None
        if (
            current is None
            or (created_at and current_created_at and created_at > current_created_at)
            or (created_at and current_created_at is None)
        ):
            latest_by_trace[trace_id] = {
                "label": label,
                "created_at": row.get("created_at"),
            }
    return count_binary_outcomes(latest_by_trace.values(), positive_key="label")


def count_forecast_actuals(
    rows: Iterable[Dict[str, Any]],
    *,
    horizon: str | None = None,
    granularity: str | None = None,
) -> Dict[str, int]:
    filtered: list[Dict[str, Any]] = []
    for row in rows:
        if horizon is not None and str(row.get("horizon") or "") != str(horizon):
            continue
        if granularity is not None and str(row.get("granularity") or "") != str(granularity):
            continue
        filtered.append(row)
    return count_binary_outcomes(filtered, positive_key="within_p90")


