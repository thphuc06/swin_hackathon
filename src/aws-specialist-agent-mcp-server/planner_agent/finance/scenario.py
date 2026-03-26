from __future__ import annotations

import random
from datetime import timedelta
from typing import Any, Dict, List

from .supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_model_evidence,
    build_native_uncertainty,
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
    parse_bool,
    parse_datetime,
    percentile,
    safe_float,
    weighted_score,
)
from .data import (
    fetch_balance_daily,
    fetch_forecast_actuals_history,
    fetch_transactions_in_window,
    write_audit_event,
    write_forecast_actuals_rows,
)
from .forecast import (
    aggregate_daily_predictions,
    build_cashflow_projection,
    build_forecast_actuals_rows,
    historical_logged_validation,
    update_forecast_actuals_for_user,
)
from .trust import build_trust, count_forecast_actuals

TOOL_NAME = "what_if_scenario_v1"
SIM_DRAWS = 2000
BALANCE_QUALITY_SCORES = {
    "verified": 1.0,
    "reconciled": 0.95,
    "estimated": 0.7,
    "unverified": 0.4,
}


def _default_variants() -> List[Dict[str, Any]]:
    return [
        {
            "name": "cut_discretionary_spend_15pct",
            "scenario_overrides": {"spend_delta_pct": -0.15},
        },
        {
            "name": "increase_income_10pct",
            "scenario_overrides": {"income_delta_pct": 0.10},
        },
        {
            "name": "balanced_income_up5_spend_down10",
            "scenario_overrides": {"income_delta_pct": 0.05, "spend_delta_pct": -0.10},
        },
    ]


def _simulate_totals(monthly_points: List[Dict[str, Any]], *, seed: int) -> List[float]:
    rng = random.Random(seed)
    totals: List[float] = []
    if not monthly_points:
        return [0.0]
    for _ in range(SIM_DRAWS):
        total = 0.0
        for point in monthly_points:
            mean_value = safe_float(point.get("p50"))
            sigma = max(1.0, safe_float(point.get("p90")) - safe_float(point.get("p10"))) / (2 * 1.281552)
            total += rng.gauss(mean_value, sigma)
        totals.append(total)
    return totals


def _scenario_metrics(
    *,
    txns: List[Dict[str, Any]],
    as_of_dt,
    horizon_months: int,
    overrides: Dict[str, Any],
    seed: int,
) -> Dict[str, Any]:
    projection = build_cashflow_projection(
        txns,
        as_of_dt=as_of_dt,
        horizon_days=horizon_months * 31,
        scenario_overrides=overrides,
    )
    monthly_points = aggregate_daily_predictions(projection["daily_predictions"], granularity="monthly", limit=horizon_months)
    clean_points = [{key: value for key, value in point.items() if not key.startswith("_")} for point in monthly_points]
    totals = _simulate_totals(clean_points, seed=seed)
    return {
        "projection": projection,
        "monthly_points": clean_points,
        "totals": totals,
        "total_p50": round(sum(safe_float(point.get("p50")) for point in clean_points), 2),
        "total_p90": round(percentile(totals, 0.9, 0.0), 2),
        "probability_negative_net": round(sum(1 for sample in totals if sample < 0) / len(totals), 4),
        "goal_success_probability": round(sum(1 for sample in totals if sample > 0) / len(totals), 4),
    }


def _latest_balance_context(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "latest_balance": 0.0,
            "latest_date": None,
            "quality_flag": "missing",
            "balance_quality": 0.0,
            "source": "none",
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
        "latest_date": latest_day,
        "quality_flag": str(chosen_rows[0].get("quality_flag") or "unverified"),
        "balance_quality": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.4,
        "source": str(chosen_rows[0].get("source") or "derived"),
    }


def what_if_scenario(
    *,
    auth_user_id: str,
    user_id: str,
    horizon_months: int = 12,
    seasonality: bool = True,
    goal: str = "maximize_savings",
    base_scenario_overrides: Dict[str, Any] | None = None,
    variants: List[Dict[str, Any]] | None = None,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    start_dt = as_of_dt - timedelta(days=365)
    horizon = max(1, min(24, int(horizon_months or 12)))
    seasonality_flag = parse_bool(seasonality)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    balance_rows = fetch_balance_daily(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    actualization_summary = update_forecast_actuals_for_user(
        sql,
        user_id=user_id,
        tool_name=TOOL_NAME,
        available_until=as_of_dt,
        lookback_days=730,
    )
    forecast_history = fetch_forecast_actuals_history(
        sql,
        user_id=user_id,
        start_at=start_dt,
        end_at=as_of_dt,
        tool_name=TOOL_NAME,
    )
    balance_context = _latest_balance_context(balance_rows)

    base_overrides = dict(base_scenario_overrides or {})
    variant_rows = list(variants or _default_variants())
    base_metrics = _scenario_metrics(
        txns=txns,
        as_of_dt=as_of_dt,
        horizon_months=horizon,
        overrides=base_overrides,
        seed=42,
    )
    ets_result = dict(base_metrics["projection"].get("external_engines", {}).get("statsmodels_ets_prediction_interval") or {})
    darts_result = dict(base_metrics["projection"].get("external_engines", {}).get("darts_exponential_smoothing") or {})
    if ets_result.get("ready"):
        native_uncertainty_source = "statsmodels_ets_prediction_interval"
    elif darts_result.get("ready"):
        native_uncertainty_source = str(darts_result.get("source") or "darts_sampling_quantiles")
    else:
        native_uncertainty_source = "heuristic_sigma_band"
    native_uncertainty_summary = {
        "p10": round(mean(safe_float(point.get("p10")) for point in base_metrics["monthly_points"]), 2) if base_metrics["monthly_points"] else 0.0,
        "p50": round(mean(safe_float(point.get("p50")) for point in base_metrics["monthly_points"]), 2) if base_metrics["monthly_points"] else 0.0,
        "p90": round(mean(safe_float(point.get("p90")) for point in base_metrics["monthly_points"]), 2) if base_metrics["monthly_points"] else 0.0,
    }

    scenario_comparison: List[Dict[str, Any]] = []
    best_variant = "base"
    best_score = base_metrics["total_p50"]
    for index, variant in enumerate(variant_rows, start=1):
        name = str(variant.get("name") or f"variant_{index}")
        merged_overrides = dict(base_overrides)
        merged_overrides.update(variant.get("scenario_overrides", {}))
        variant_metrics = _scenario_metrics(
            txns=txns,
            as_of_dt=as_of_dt,
            horizon_months=horizon,
            overrides=merged_overrides,
            seed=42 + index,
        )
        probability_better_than_base = round(
            sum(
                1
                for variant_total, base_total in zip(variant_metrics["totals"], base_metrics["totals"])
                if variant_total > base_total
            )
            / len(base_metrics["totals"]),
            4,
        )
        row = {
            "name": name,
            "total_net_p50": variant_metrics["total_p50"],
            "delta_vs_base": round(variant_metrics["total_p50"] - base_metrics["total_p50"], 2),
            "delta_p50": round(variant_metrics["total_p50"] - base_metrics["total_p50"], 2),
            "delta_p90": round(variant_metrics["total_p90"] - base_metrics["total_p90"], 2),
            "probability_better_than_base": probability_better_than_base,
            "probability_negative_net": variant_metrics["probability_negative_net"],
            "goal_success_probability": variant_metrics["goal_success_probability"],
        }
        scenario_comparison.append(row)
        if row["total_net_p50"] > best_score:
            best_score = row["total_net_p50"]
            best_variant = name

    dominance_margin = max((safe_float(row["probability_better_than_base"]) for row in scenario_comparison), default=0.0)
    confidence_score = weighted_score(
        {
            "forecast_reliability": safe_float(base_metrics["projection"]["reliability"]["confidence_score"]),
            "variant_count": clamp(len(variant_rows) / 3.0),
            "dominance_margin": dominance_margin,
            "balance_data_quality": balance_context["balance_quality"] if balance_context["available"] else 0.45,
        },
        {
            "forecast_reliability": 0.55,
            "variant_count": 0.15,
            "dominance_margin": 0.25,
            "balance_data_quality": 0.05,
        },
    )
    forecast_log_rows = build_forecast_actuals_rows(
        user_id=user_id,
        trace_id=trace,
        tool_name=TOOL_NAME,
        horizon=f"scenario_{horizon}m",
        granularity="weekly",
        as_of_dt=as_of_dt,
        model_name="what_if_scenario_projection_v2",
        daily_predictions=base_metrics["projection"]["daily_predictions"],
        reliability_score=confidence_score,
        overrides={
            "goal": goal,
            "horizon_months": horizon,
            "base_scenario_overrides": base_overrides,
            "variant_count": len(variant_rows),
        },
    )

    tool_input = {
        "user_id": user_id,
        "horizon_months": horizon,
        "seasonality": seasonality_flag,
        "goal": goal,
        "base_scenario_overrides": base_overrides,
        "variants": variant_rows,
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "scenario_comparison": scenario_comparison,
        "best_variant_by_goal": best_variant,
        "recommended_variant": best_variant,
        "base_total_net_p50": round(base_metrics["total_p50"], 2),
        "base_scenario": {
            "horizon_months": horizon,
            "seasonality": seasonality_flag,
            "overrides": base_overrides,
            "probability_negative_net": base_metrics["probability_negative_net"],
            "starting_balance_context": {
                "available": balance_context["available"],
                "latest_balance": balance_context["latest_balance"],
                "latest_date": balance_context["latest_date"],
                "quality_flag": balance_context["quality_flag"],
                "source": balance_context["source"],
            },
        },
        "variants_used": [str(item.get("name") or "") for item in variant_rows],
    }
    scenario_confidence_bucket = "high" if confidence_score >= 0.8 else ("medium" if confidence_score >= 0.6 else "low")
    historical_validation = historical_logged_validation(forecast_history)
    calibration_monitoring = {
        "confidence_score": round(confidence_score, 4),
        "confidence_bucket": scenario_confidence_bucket,
        "monitoring_status": "healthy" if confidence_score >= 0.6 else ("watch" if confidence_score >= 0.4 else "alert"),
        "forecast_reliability_score": round(safe_float(base_metrics["projection"]["reliability"]["confidence_score"]), 4),
        "forecast_reliability_bucket": str(base_metrics["projection"]["reliability"].get("confidence_level") or "low"),
        "native_uncertainty_source": native_uncertainty_source,
        "interval_width_avg": ets_result.get("interval_width_avg") if ets_result.get("ready") else darts_result.get("interval_width_avg"),
        "historical_actual_count": int(safe_float(historical_validation.get("actual_count"), 0.0)),
        "forecast_log_rows": len(forecast_log_rows),
        "actualization_updated_count": int(safe_float(actualization_summary.get("updated_count"), 0.0)),
    }
    reliability = build_reliability(
        confidence_score=confidence_score,
        components={
            "forecast_reliability": safe_float(base_metrics["projection"]["reliability"]["confidence_score"]),
            "variant_count": clamp(len(variant_rows) / 3.0),
            "dominance_margin": dominance_margin,
            "balance_data_quality": balance_context["balance_quality"] if balance_context["available"] else 0.45,
        },
        reason_codes=base_metrics["projection"]["reliability"].get("reason_codes", []),
    )
    forecast_outcomes = count_forecast_actuals(
        forecast_history,
        horizon=f"scenario_{horizon}m",
        granularity="weekly",
    )
    forecast_cap_bundle = build_trust(
        confidence_score=safe_float(base_metrics["projection"]["reliability"]["confidence_score"]),
        reliability_components=base_metrics["projection"]["reliability"].get("components"),
        abstain_recommended=bool(base_metrics["projection"]["reliability"].get("abstain_recommended")),
        prior_alpha=8.0,
        prior_beta=2.0,
        monitoring_status=str(calibration_monitoring["monitoring_status"]),
        success_count=forecast_outcomes["success_count"],
        failure_count=forecast_outcomes["failure_count"],
    )
    trust_bundle = build_trust(
        confidence_score=safe_float(reliability["confidence_score"]),
        reliability_components=reliability.get("components"),
        abstain_recommended=bool(reliability.get("abstain_recommended")),
        prior_alpha=8.0,
        prior_beta=2.0,
        monitoring_status=str(calibration_monitoring["monitoring_status"]),
        cap_score=safe_float(forecast_cap_bundle["trust"].get("trust_score")),
        cap_reason="forecast_trust_cap",
        cap_method=str(forecast_cap_bundle["trust"].get("method") or "cold_start"),
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
            native_uncertainty=build_native_uncertainty(
                source=native_uncertainty_source,
                p10=native_uncertainty_summary["p10"],
                p50=native_uncertainty_summary["p50"],
                p90=native_uncertainty_summary["p90"],
                granularity="monthly",
                points=base_metrics["monthly_points"],
                inherited_from="cashflow_forecast_v1",
                used_for_output=False,
                interval_width_avg=ets_result.get("interval_width_avg") if ets_result.get("ready") else darts_result.get("interval_width_avg"),
            )
        ),
        provenance=build_provenance(
            library="forecast_projection",
            model="what_if_scenario_v2",
            model_version="scenario_v2",
            feature_set_version="scenario_features_v2",
        ),
        validation=build_validation(
            tx_count=len(txns),
            base_forecast_validation=base_metrics["projection"].get("validation", {}),
            calibration_monitoring=calibration_monitoring,
            native_diagnostics={
                "native_uncertainty_source": native_uncertainty_source,
                "statsmodels_ets_prediction_interval": {
                    "available": ets_result.get("available"),
                    "ready": ets_result.get("ready"),
                    "aic": (ets_result.get("diagnostics") or {}).get("aic"),
                    "bic": (ets_result.get("diagnostics") or {}).get("bic"),
                    "llf": (ets_result.get("diagnostics") or {}).get("llf"),
                    "error": ets_result.get("error"),
                    "reason": ets_result.get("reason"),
                },
                "darts_exponential_smoothing": {
                    "available": darts_result.get("available"),
                    "ready": darts_result.get("ready"),
                    "source": darts_result.get("source"),
                    "num_samples": darts_result.get("num_samples"),
                    "error": darts_result.get("error"),
                    "reason": darts_result.get("reason"),
                },
            },
            variant_count=len(variant_rows),
            balance_row_count=len(balance_rows),
            historical_logged_forecast_validation=historical_validation,
            forecast_log_rows=len(forecast_log_rows),
            actualization_summary=actualization_summary,
        ),
    )
    write_forecast_actuals_rows(sql, forecast_log_rows)
    write_audit_event(
        sql,
        user_id=user_id,
        trace_id=trace,
        event_type=TOOL_NAME,
        payload={
            "params": {
                "horizon_months": horizon,
                "seasonality": seasonality_flag,
                "variants_count": len(variant_rows),
            },
            "result": {
                "best_variant_by_goal": payload["best_variant_by_goal"],
                "base_total_net_p50": payload["base_total_net_p50"],
                "confidence_score": result.get("reliability", {}).get("confidence_score"),
            },
        },
    )
    return result


