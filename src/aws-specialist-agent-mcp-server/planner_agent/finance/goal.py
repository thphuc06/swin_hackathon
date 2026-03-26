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
    fetch_goals,
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

TOOL_NAME = "goal_feasibility_v1"
SIM_DRAWS = 2000
SIM_SEED = 42
BALANCE_QUALITY_SCORES = {
    "verified": 1.0,
    "reconciled": 0.95,
    "estimated": 0.7,
    "unverified": 0.4,
}


def _resolve_goal_target(
    *,
    goals: List[Dict[str, Any]],
    goal_id: str | None,
    target_amount: float | None,
    horizon_months: int | None,
) -> Dict[str, Any]:
    if target_amount is not None and safe_float(target_amount) > 0:
        return {
            "target_amount": safe_float(target_amount),
            "horizon_months": max(1, int(safe_float(horizon_months, 12))),
            "goal_id": goal_id,
            "goal_name": "input_target",
            "source": "input",
        }

    chosen = None
    if goal_id:
        for goal in goals:
            if str(goal.get("id") or "") == goal_id:
                chosen = goal
                break
    if chosen is None:
        for goal in goals:
            if safe_float(goal.get("target_amount")) > 0:
                chosen = goal
                break

    if chosen is None:
        raise ValueError("Missing target_amount and no goal found in DB for fallback.")

    return {
        "target_amount": safe_float(chosen.get("target_amount")),
        "horizon_months": max(1, int(safe_float(horizon_months, chosen.get("horizon_months") or 12))),
        "goal_id": str(chosen.get("id") or ""),
        "goal_name": str(chosen.get("name") or "goal"),
        "source": "db_fallback",
    }


def _simulate_goal_capacity(monthly_points: List[Dict[str, Any]], *, target_amount: float) -> Dict[str, Any]:
    if not monthly_points:
        return {
            "total_positive_samples": [0.0],
            "total_net_samples": [0.0],
            "time_to_goal_samples": [],
        }
    rng = random.Random(SIM_SEED)
    total_positive_samples: List[float] = []
    total_net_samples: List[float] = []
    time_to_goal_samples: List[int] = []
    for _ in range(SIM_DRAWS):
        total_positive = 0.0
        total_net = 0.0
        reached_month = None
        running_positive = 0.0
        for month_index, point in enumerate(monthly_points, start=1):
            mean_value = safe_float(point.get("p50"))
            sigma = max(1.0, safe_float(point.get("p90")) - safe_float(point.get("p10"))) / (2 * 1.281552)
            sample = rng.gauss(mean_value, sigma)
            total_net += sample
            running_positive += max(0.0, sample)
            total_positive += max(0.0, sample)
            if reached_month is None and running_positive >= target_amount:
                reached_month = month_index
        total_positive_samples.append(total_positive)
        total_net_samples.append(total_net)
        if reached_month is not None:
            time_to_goal_samples.append(reached_month)
    return {
        "total_positive_samples": total_positive_samples,
        "total_net_samples": total_net_samples,
        "time_to_goal_samples": time_to_goal_samples,
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


def goal_feasibility(
    *,
    auth_user_id: str,
    user_id: str,
    target_amount: float | None = None,
    horizon_months: int | None = None,
    goal_id: str | None = None,
    seasonality: bool = True,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    start_dt = as_of_dt - timedelta(days=365)

    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=start_dt, end_at=as_of_dt)
    goals = fetch_goals(sql, user_id)
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

    try:
        resolved = _resolve_goal_target(
            goals=goals,
            goal_id=goal_id,
            target_amount=target_amount,
            horizon_months=horizon_months,
        )
    except ValueError as exc:
        requested_target = safe_float(target_amount) if target_amount is not None else None
        requested_horizon = int(safe_float(horizon_months, 0)) if horizon_months is not None else None
        tool_input = {
            "user_id": user_id,
            "target_amount": requested_target,
            "horizon_months": requested_horizon,
            "goal_id": goal_id,
            "seasonality": parse_bool(seasonality),
            "as_of": iso_utc(as_of_dt),
        }
        payload = {
            "status": "insufficient_input",
            "reason_codes": ["missing_goal_target"],
            "message": str(exc),
            "goal_source": "none",
            "goal_id": goal_id,
            "goal_name": "unresolved_goal",
            "target_amount": round(safe_float(requested_target), 2) if requested_target else 0.0,
            "horizon_months": requested_horizon if requested_horizon and requested_horizon > 0 else None,
            "required_monthly_saving": 0.0,
            "required_monthly_saving_p90": 0.0,
            "probability_of_success": 0.0,
            "feasible": False,
            "gap_amount": 0.0,
            "grade": "N/A",
            "reasons": ["Provide target_amount or create a goal before requesting feasibility."],
            "metrics": {},
            "forecast_summary": {
                "base_total_net_p50": 0.0,
                "history_days": 0,
                "forecast_points": 0,
            },
        }
        reliability = build_reliability(confidence_score=0.0, reason_codes=["missing_goal_target"])
        trust_bundle = build_trust(
            confidence_score=0.0,
            reliability_components=reliability.get("components"),
            abstain_recommended=bool(reliability.get("abstain_recommended")),
            prior_alpha=8.0,
            prior_beta=2.0,
            monitoring_status="alert",
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
                library="forecast_projection",
                model="goal_feasibility_v2",
                model_version="goal_v2",
                feature_set_version="goal_features_v2",
            ),
            validation=build_validation(tx_count=len(txns), forecast_points=0),
        )
        write_audit_event(
            sql,
            user_id=user_id,
            trace_id=trace,
            event_type=TOOL_NAME,
            payload={
                "params": {
                    "goal_id": goal_id,
                    "target_amount": requested_target,
                    "horizon_months": requested_horizon,
                },
                "result": {
                    "status": "insufficient_input",
                    "reason_codes": ["missing_goal_target"],
                },
            },
        )
        return result

    horizon = int(resolved["horizon_months"])
    projection = build_cashflow_projection(
        txns,
        as_of_dt=as_of_dt,
        horizon_days=horizon * 31,
        scenario_overrides={},
    )
    monthly_points = aggregate_daily_predictions(projection["daily_predictions"], granularity="monthly", limit=horizon)
    monthly_points_clean = [{key: value for key, value in point.items() if not key.startswith("_")} for point in monthly_points]
    ets_result = dict(projection.get("external_engines", {}).get("statsmodels_ets_prediction_interval") or {})
    darts_result = dict(projection.get("external_engines", {}).get("darts_exponential_smoothing") or {})
    if ets_result.get("ready"):
        native_uncertainty_source = "statsmodels_ets_prediction_interval"
    elif darts_result.get("ready"):
        native_uncertainty_source = str(darts_result.get("source") or "darts_sampling_quantiles")
    else:
        native_uncertainty_source = "heuristic_sigma_band"
    native_uncertainty_summary = {
        "p10": round(mean(safe_float(point.get("p10")) for point in monthly_points_clean), 2) if monthly_points_clean else 0.0,
        "p50": round(mean(safe_float(point.get("p50")) for point in monthly_points_clean), 2) if monthly_points_clean else 0.0,
        "p90": round(mean(safe_float(point.get("p90")) for point in monthly_points_clean), 2) if monthly_points_clean else 0.0,
    }
    target = safe_float(resolved["target_amount"])
    simulations = _simulate_goal_capacity(monthly_points_clean, target_amount=target)
    required_monthly_saving = safe_float(target / max(horizon, 1))
    total_positive_samples = simulations["total_positive_samples"]
    total_net_samples = simulations["total_net_samples"]
    median_capacity = percentile(total_positive_samples, 0.5, 0.0)
    capacity_p10 = percentile(total_positive_samples, 0.1, 0.0)
    shortfalls = [max(0.0, target - sample) for sample in total_positive_samples]
    probability_of_success = round(sum(1 for sample in total_positive_samples if sample >= target) / len(total_positive_samples), 4)
    gap_amount = round(max(0.0, target - median_capacity), 2)
    required_monthly_saving_p90 = round(required_monthly_saving + max(0.0, target - capacity_p10) / max(horizon, 1), 2)
    feasible = probability_of_success >= 0.5
    if probability_of_success >= 0.75:
        grade = "A"
    elif probability_of_success >= 0.45:
        grade = "B"
    else:
        grade = "C"

    confidence_score = weighted_score(
        {
            "forecast_reliability": safe_float(projection["reliability"]["confidence_score"]),
            "goal_input_completeness": 1.0,
            "history": clamp(len(txns) / 200.0),
            "balance_data_quality": balance_context["balance_quality"] if balance_context["available"] else 0.45,
        },
        {
            "forecast_reliability": 0.55,
            "goal_input_completeness": 0.2,
            "history": 0.2,
            "balance_data_quality": 0.05,
        },
    )
    forecast_log_rows = build_forecast_actuals_rows(
        user_id=user_id,
        trace_id=trace,
        tool_name=TOOL_NAME,
        horizon=f"goal_{horizon}m",
        granularity="weekly",
        as_of_dt=as_of_dt,
        model_name="goal_feasibility_projection_v2",
        daily_predictions=projection["daily_predictions"],
        reliability_score=confidence_score,
        overrides={
            "goal_id": resolved["goal_id"],
            "goal_name": resolved["goal_name"],
            "target_amount": round(target, 2),
            "horizon_months": horizon,
        },
    )
    reasons = [
        f"Required monthly saving: {required_monthly_saving:.0f} VND.",
        f"Estimated probability of success over {horizon} months: {probability_of_success:.1%}.",
    ]
    if not feasible:
        reasons.append("Current forecast distribution suggests the goal may need either more saving or a longer horizon.")

    tool_input = {
        "user_id": user_id,
        "target_amount": resolved["target_amount"],
        "horizon_months": resolved["horizon_months"],
        "goal_id": resolved["goal_id"],
        "seasonality": parse_bool(seasonality),
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "goal_source": resolved["source"],
        "goal_id": resolved["goal_id"] or None,
        "goal_name": resolved["goal_name"],
        "target_amount": round(target, 2),
        "horizon_months": horizon,
        "required_monthly_saving": round(required_monthly_saving, 2),
        "required_monthly_saving_p90": required_monthly_saving_p90,
        "probability_of_success": probability_of_success,
        "feasible": feasible,
        "gap_amount": gap_amount,
        "grade": grade,
        "reasons": reasons,
        "metrics": {
            "required_monthly_saving": round(required_monthly_saving, 2),
            "required_monthly_saving_p90": required_monthly_saving_p90,
            "projected_positive_cashflow_p50": round(median_capacity, 2),
            "projected_positive_cashflow_p10": round(capacity_p10, 2),
            "gap_amount": gap_amount,
            "probability_of_success": probability_of_success,
        },
        "shortfall_distribution": {
            "p50": round(percentile(shortfalls, 0.5, 0.0), 2),
            "p90": round(percentile(shortfalls, 0.9, 0.0), 2),
        },
        "starting_balance_context": {
            "available": balance_context["available"],
            "latest_balance": balance_context["latest_balance"],
            "latest_date": balance_context["latest_date"],
            "quality_flag": balance_context["quality_flag"],
            "source": balance_context["source"],
        },
        "time_to_goal_distribution": {
            "p50_months": round(percentile(simulations["time_to_goal_samples"], 0.5, 0.0), 2) if simulations["time_to_goal_samples"] else None,
            "p90_months": round(percentile(simulations["time_to_goal_samples"], 0.9, 0.0), 2) if simulations["time_to_goal_samples"] else None,
        },
        "forecast_summary": {
            "base_total_net_p50": round(sum(safe_float(point.get("p50")) for point in monthly_points_clean), 2),
            "base_total_net_distribution_p50": round(percentile(total_net_samples, 0.5, 0.0), 2),
            "history_days": len(projection["dense_rows"]),
            "forecast_points": len(monthly_points_clean),
        },
    }
    goal_confidence_bucket = "high" if confidence_score >= 0.8 else ("medium" if confidence_score >= 0.6 else "low")
    historical_validation = historical_logged_validation(forecast_history)
    calibration_monitoring = {
        "confidence_score": round(confidence_score, 4),
        "confidence_bucket": goal_confidence_bucket,
        "monitoring_status": "healthy" if confidence_score >= 0.6 else ("watch" if confidence_score >= 0.4 else "alert"),
        "forecast_reliability_score": round(safe_float(projection["reliability"]["confidence_score"]), 4),
        "forecast_reliability_bucket": str(projection["reliability"].get("confidence_level") or "low"),
        "native_uncertainty_source": native_uncertainty_source,
        "interval_width_avg": ets_result.get("interval_width_avg") if ets_result.get("ready") else darts_result.get("interval_width_avg"),
        "historical_actual_count": int(safe_float(historical_validation.get("actual_count"), 0.0)),
        "forecast_log_rows": len(forecast_log_rows),
        "actualization_updated_count": int(safe_float(actualization_summary.get("updated_count"), 0.0)),
    }
    reliability = build_reliability(
        confidence_score=confidence_score,
        components={
            "forecast_reliability": safe_float(projection["reliability"]["confidence_score"]),
            "goal_input_completeness": 1.0,
            "history": clamp(len(txns) / 200.0),
            "balance_data_quality": balance_context["balance_quality"] if balance_context["available"] else 0.45,
        },
        reason_codes=projection["reliability"].get("reason_codes", []),
    )
    forecast_outcomes = count_forecast_actuals(
        forecast_history,
        horizon=f"goal_{horizon}m",
        granularity="weekly",
    )
    forecast_cap_bundle = build_trust(
        confidence_score=safe_float(projection["reliability"]["confidence_score"]),
        reliability_components=projection["reliability"].get("components"),
        abstain_recommended=bool(projection["reliability"].get("abstain_recommended")),
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
                points=monthly_points_clean,
                inherited_from="cashflow_forecast_v1",
                used_for_output=False,
                interval_width_avg=ets_result.get("interval_width_avg") if ets_result.get("ready") else darts_result.get("interval_width_avg"),
            )
        ),
        provenance=build_provenance(
            library="forecast_projection",
            model="goal_feasibility_v2",
            model_version="goal_v2",
            feature_set_version="goal_features_v2",
        ),
        validation=build_validation(
            tx_count=len(txns),
            forecast_points=len(monthly_points_clean),
            forecast_validation=projection.get("validation", {}),
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
                "goal_id": resolved["goal_id"],
                "target_amount": resolved["target_amount"],
                "horizon_months": resolved["horizon_months"],
            },
            "result": {
                "feasible": feasible,
                "gap_amount": gap_amount,
                "probability_of_success": probability_of_success,
            },
        },
    )
    return result


