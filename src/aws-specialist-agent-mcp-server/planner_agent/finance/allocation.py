from __future__ import annotations

from collections import defaultdict
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
    daterange_start,
    ensure_user_scope,
    iso_utc,
    mean,
    new_trace_id,
    now_utc,
    parse_datetime,
    safe_div,
    safe_float,
    weighted_score,
)
from .data import (
    fetch_allocation_decision_history,
    fetch_categories,
    fetch_forecast_actuals_history,
    fetch_goals,
    fetch_jars,
    fetch_transactions_in_window,
    write_audit_event,
)
from .forecast import build_cashflow_projection
from .taxonomy import score_category_role, score_text_role
from .trust import build_trust, count_binary_outcomes, count_forecast_actuals

TOOL_NAME = "jar_allocation_suggest_v1"
ROLES = ["bills", "emergency", "goals", "living", "discretionary"]


def _monthly_average(values: List[float]) -> float:
    return mean(values)


def _infer_jar_roles(
    jars: List[Dict[str, Any]],
    *,
    category_breakdown_by_jar: Dict[str, Dict[str, float]],
    has_goals: bool,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for jar in jars:
        jar_id = str(jar.get("id") or "")
        name = str(jar.get("name") or "")
        description = str(jar.get("description") or "")
        keywords = list(jar.get("keywords") or [])
        text_scores = score_text_role(name, description, keywords)
        category_scores = score_category_role(category_breakdown_by_jar.get(jar_id, {}))
        goal_signal = 1.0 if has_goals and "goal" in name.lower() else 0.0
        combined_scores = {
            role: round(
                0.55 * safe_float(text_scores.get(role))
                + 0.35 * safe_float(category_scores.get(role))
                + 0.10 * (goal_signal if role == "goals" else 0.0),
                4,
            )
            for role in ROLES
        }
        ranked = sorted(combined_scores.items(), key=lambda item: item[1], reverse=True)
        top_role, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        role_confidence = clamp(top_score if top_score >= 0.55 else top_score * 0.85)
        assigned_role = top_role if top_score >= 0.55 and (top_score - second_score) >= 0.15 else "unclassified"
        rows.append(
            {
                "jar_id": jar_id,
                "jar_name": name,
                "role": assigned_role,
                "role_confidence": round(role_confidence, 4),
                "role_scores": combined_scores,
            }
        )
    return rows


def _role_jar_map(role_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for role in ROLES:
        candidates = [row for row in role_rows if row["role"] == role]
        if not candidates:
            continue
        mapping[role] = max(candidates, key=lambda row: safe_float(row.get("role_confidence")))
    return mapping


def _generate_transfer_suggestions(current_vs_target: List[Dict[str, Any]], baseline_income: float) -> List[Dict[str, Any]]:
    deficits = [
        dict(row, delta_amount=round(max(0.0, safe_float(row["target_share"]) - safe_float(row["current_share"])) * baseline_income, 2))
        for row in current_vs_target
        if safe_float(row["target_share"]) > safe_float(row["current_share"])
    ]
    surpluses = [
        dict(row, delta_amount=round(max(0.0, safe_float(row["current_share"]) - safe_float(row["target_share"])) * baseline_income, 2))
        for row in current_vs_target
        if safe_float(row["current_share"]) > safe_float(row["target_share"])
    ]
    suggestions: List[Dict[str, Any]] = []
    for deficit in deficits:
        needed = safe_float(deficit["delta_amount"])
        for surplus in surpluses:
            available = safe_float(surplus["delta_amount"])
            if available <= 0 or needed <= 0:
                continue
            amount = round(min(available, needed), 2)
            surplus["delta_amount"] = round(max(0.0, available - amount), 2)
            needed = round(max(0.0, needed - amount), 2)
            suggestions.append(
                {
                    "source_jar_id": surplus["jar_id"],
                    "source_jar_name": surplus["jar_name"],
                    "target_jar_id": deficit["jar_id"],
                    "target_jar_name": deficit["jar_name"],
                    "amount": amount,
                    "rationale": f"Shift monthly budget from {surplus['jar_name']} toward {deficit['jar_name']} target share.",
                }
            )
            if needed <= 0:
                break
    return suggestions[:6]


def _decision_history_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "decision_count": 0,
            "acceptance_rate": None,
            "modification_rate": None,
            "rejection_rate": None,
            "last_decision_at": None,
        }
    total = len(rows)
    accepted = sum(1 for row in rows if str(row.get("decision_status") or "") in {"accepted", "auto_applied"})
    modified = sum(1 for row in rows if str(row.get("decision_status") or "") == "modified")
    rejected = sum(1 for row in rows if str(row.get("decision_status") or "") == "rejected")
    return {
        "decision_count": total,
        "acceptance_rate": round(safe_div(accepted, total), 4),
        "modification_rate": round(safe_div(modified, total), 4),
        "rejection_rate": round(safe_div(rejected, total), 4),
        "last_decision_at": str(rows[0].get("created_at") or rows[0].get("decided_at") or ""),
    }


def jar_allocation_suggest(
    *,
    auth_user_id: str,
    user_id: str,
    monthly_income_override: float | None = None,
    goal_overrides: List[Dict[str, Any]] | None = None,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    as_of_dt = parse_datetime(as_of) or now_utc()
    history_start = daterange_start(as_of_dt, 180)
    sql = client or get_supabase_client()

    jars = fetch_jars(sql, user_id)
    categories = fetch_categories(sql, user_id)
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=history_start, end_at=as_of_dt)
    goals = goal_overrides if goal_overrides is not None else fetch_goals(sql, user_id)
    forecast_history = fetch_forecast_actuals_history(
        sql,
        user_id=user_id,
        start_at=daterange_start(as_of_dt, 365),
        end_at=as_of_dt,
        tool_name="cashflow_forecast_v1",
    )
    decision_history = fetch_allocation_decision_history(
        sql,
        user_id=user_id,
        start_at=daterange_start(as_of_dt, 365),
        end_at=as_of_dt,
    )
    category_name_by_id = {str(item.get("id")): str(item.get("name") or "Unknown") for item in categories}

    tool_input = {
        "user_id": user_id,
        "monthly_income_override": monthly_income_override,
        "goal_overrides": goal_overrides or [],
        "as_of": iso_utc(as_of_dt),
    }

    if not jars:
        payload = {
            "status": "insufficient_data",
            "reason_codes": ["missing_jars"],
            "message": "No jars found for user. Seed jars before requesting allocation suggestion.",
            "baseline_monthly_income": 0.0,
            "monthly_reference_spend": 0.0,
            "allocations": [],
            "leftover": 0.0,
            "constraints_applied": ["insufficient_data"],
        }
        reliability = build_reliability(confidence_score=0.0, reason_codes=["missing_jars"])
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
            window=build_window(history_start, as_of_dt),
            reliability=reliability,
            trust=trust_bundle["trust"],
            agent_use=trust_bundle["agent_use"],
            provenance=build_provenance(
                library="heuristic_rules",
                model="jar_allocation_v2",
                model_version="allocation_v2",
                feature_set_version="jar_role_features_v2",
            ),
            validation=build_validation(jar_count=0, tx_count=len(txns)),
        )
        write_audit_event(
            sql,
            user_id=user_id,
            trace_id=trace,
            event_type=TOOL_NAME,
            payload={"params": tool_input, "result": {"status": "insufficient_data", "reason_codes": ["missing_jars"]}},
        )
        return result

    jar_name_by_id = {str(j.get("id")): str(j.get("name") or "Unknown") for j in jars}
    monthly_income: Dict[str, float] = defaultdict(float)
    monthly_debit: Dict[str, float] = defaultdict(float)
    monthly_debit_by_jar: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    category_breakdown_by_jar: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred:
            continue
        month_key = occurred.strftime("%Y-%m")
        amount = safe_float(tx.get("amount"))
        direction = str(tx.get("direction") or "debit").lower()
        jar_id = str(tx.get("jar_id") or "")
        if direction == "credit":
            monthly_income[month_key] += amount
            continue
        monthly_debit[month_key] += amount
        monthly_debit_by_jar[month_key][jar_id] += amount
        category_name = category_name_by_id.get(str(tx.get("category_id") or ""), "Unknown")
        category_breakdown_by_jar[jar_id][category_name] += amount

    income_values = list(monthly_income.values())
    debit_values = list(monthly_debit.values())
    baseline_income = _monthly_average(income_values)
    if monthly_income_override is not None and monthly_income_override > 0:
        baseline_income = monthly_income_override

    role_rows = _infer_jar_roles(jars, category_breakdown_by_jar=category_breakdown_by_jar, has_goals=bool(goals))
    role_map = _role_jar_map(role_rows)

    def _role_average(role_name: str) -> float:
        jar = role_map.get(role_name)
        if not jar:
            return 0.0
        jar_id = jar["jar_id"]
        return _monthly_average([safe_float(month_data.get(jar_id)) for month_data in monthly_debit_by_jar.values()])

    monthly_bills_need = _role_average("bills")
    monthly_living_need = _role_average("living")
    monthly_goal_need = 0.0
    for goal in goals:
        target = safe_float(goal.get("target_amount"))
        horizon = max(1, int(safe_float(goal.get("horizon_months"), 12)))
        monthly_goal_need += target / horizon

    remaining = max(0.0, baseline_income)
    constraints: List[str] = []
    recommended_by_role = {
        "bills": min(remaining, monthly_bills_need),
        "emergency": 0.0,
        "goals": 0.0,
        "living": 0.0,
        "discretionary": 0.0,
    }
    remaining = max(0.0, remaining - recommended_by_role["bills"])
    recommended_by_role["emergency"] = min(remaining, max(0.0, baseline_income * 0.2))
    remaining = max(0.0, remaining - recommended_by_role["emergency"])
    recommended_by_role["goals"] = min(remaining, monthly_goal_need)
    remaining = max(0.0, remaining - recommended_by_role["goals"])
    recommended_by_role["living"] = min(remaining, max(monthly_living_need, baseline_income * 0.25))
    remaining = max(0.0, remaining - recommended_by_role["living"])
    recommended_by_role["discretionary"] = max(0.0, remaining)
    remaining = 0.0

    shaped_allocations: List[Dict[str, Any]] = []
    current_vs_target: List[Dict[str, Any]] = []
    avg_spend_total = _monthly_average(debit_values)
    for role_name in ROLES:
        jar_row = role_map.get(role_name)
        if not jar_row:
            continue
        amount = round(recommended_by_role.get(role_name, 0.0), 2)
        ratio = round(safe_div(amount, baseline_income), 4) if baseline_income > 0 else 0.0
        shaped_allocations.append(
            {
                "jar_id": jar_row["jar_id"],
                "jar_name": jar_row["jar_name"],
                "amount": amount,
                "ratio": ratio,
                "reason": f"{role_name}_allocation_target",
            }
        )
        current_share = safe_div(_role_average(role_name), avg_spend_total) if avg_spend_total > 0 else 0.0
        current_vs_target.append(
            {
                "jar_id": jar_row["jar_id"],
                "jar_name": jar_row["jar_name"],
                "role": role_name,
                "current_share": round(current_share, 4),
                "target_share": ratio,
                "delta_share": round(ratio - current_share, 4),
            }
        )

    if baseline_income > 0 and sum(item["amount"] for item in shaped_allocations) > baseline_income:
        constraints.append("allocation_clipped_to_income")

    projection = build_cashflow_projection(txns, as_of_dt=as_of_dt, horizon_days=30, scenario_overrides={})
    forecast_points = projection.get("daily_predictions", [])[:30]
    ets_result = dict(projection.get("external_engines", {}).get("statsmodels_ets_prediction_interval") or {})
    darts_result = dict(projection.get("external_engines", {}).get("darts_exponential_smoothing") or {})
    if ets_result.get("ready"):
        native_uncertainty_source = "statsmodels_ets_prediction_interval"
    elif darts_result.get("ready"):
        native_uncertainty_source = str(darts_result.get("source") or "darts_sampling_quantiles")
    else:
        native_uncertainty_source = "heuristic_sigma_band"
    native_uncertainty_summary = {
        "p10": round(mean(safe_float(point.get("p10")) for point in forecast_points), 2) if forecast_points else 0.0,
        "p50": round(mean(safe_float(point.get("p50")) for point in forecast_points), 2) if forecast_points else 0.0,
        "p90": round(mean(safe_float(point.get("p90")) for point in forecast_points), 2) if forecast_points else 0.0,
    }
    role_mapping_quality = mean(row["role_confidence"] for row in role_rows) if role_rows else 0.0
    forecast_reliability = safe_float(projection["reliability"]["confidence_score"], 0.0)
    spend_coverage_quality = clamp(len(monthly_debit) / 6.0)
    goal_input_completeness = 1.0 if goals else 0.4
    confidence_score = weighted_score(
        {
            "role_mapping": role_mapping_quality,
            "spend_coverage": spend_coverage_quality,
            "forecast_reliability": forecast_reliability,
            "goal_inputs": goal_input_completeness,
        },
        {
            "role_mapping": 0.3,
            "spend_coverage": 0.25,
            "forecast_reliability": 0.25,
            "goal_inputs": 0.2,
        },
    )
    reason_codes = []
    if not txns:
        reason_codes.append("no_transactions_in_window")
    if role_mapping_quality < 0.5:
        reason_codes.append("role_mapping_low_confidence")
    if not goals:
        reason_codes.append("missing_goals")
    if forecast_reliability < 0.5:
        reason_codes.append("forecast_reliability_low")

    bills_amount = recommended_by_role["bills"]
    goals_amount = recommended_by_role["goals"]
    emergency_amount = recommended_by_role["emergency"]
    allocation_risk = {
        "probability_of_bill_shortfall": round(clamp(projection["probability_negative_net"] + safe_div(monthly_bills_need - bills_amount, max(monthly_bills_need, 1.0), 0.0)), 4),
        "probability_of_goal_delay": round(
            clamp(1.0 - safe_div(goals_amount, max(monthly_goal_need, 1.0), 0.0), 0.0, 1.0) if monthly_goal_need > 0 else 0.0,
            4,
        ),
        "runway_impact": {
            "emergency_ratio": round(safe_div(emergency_amount, baseline_income), 4) if baseline_income > 0 else 0.0,
            "uses_proxy_balance": True,
        },
    }
    transfer_suggestions = _generate_transfer_suggestions(current_vs_target, baseline_income)
    decision_history_summary = _decision_history_summary(decision_history)

    payload = {
        "baseline_monthly_income": round(baseline_income, 2),
        "monthly_reference_spend": round(_monthly_average(debit_values), 2),
        "allocations": shaped_allocations,
        "leftover": round(remaining, 2),
        "constraints_applied": constraints,
        "jar_roles": role_rows,
        "current_vs_target": current_vs_target,
        "transfer_suggestions": transfer_suggestions,
        "allocation_risk": allocation_risk,
        "decision_history_summary": decision_history_summary,
    }
    allocation_confidence_bucket = "high" if confidence_score >= 0.8 else ("medium" if confidence_score >= 0.6 else "low")
    calibration_monitoring = {
        "confidence_score": round(confidence_score, 4),
        "confidence_bucket": allocation_confidence_bucket,
        "monitoring_status": "healthy" if confidence_score >= 0.6 else ("watch" if confidence_score >= 0.4 else "alert"),
        "forecast_reliability_score": round(forecast_reliability, 4),
        "forecast_reliability_bucket": str(projection["reliability"].get("confidence_level") or "low"),
        "native_uncertainty_source": native_uncertainty_source,
        "interval_width_avg": ets_result.get("interval_width_avg") if ets_result.get("ready") else darts_result.get("interval_width_avg"),
        "month_count": len(monthly_debit),
    }
    reliability = build_reliability(
        confidence_score=confidence_score,
        components={
            "role_mapping_quality": role_mapping_quality,
            "spend_coverage_quality": spend_coverage_quality,
            "forecast_reliability": forecast_reliability,
            "goal_input_completeness": goal_input_completeness,
        },
        reason_codes=reason_codes,
    )
    forecast_cap_outcomes = count_forecast_actuals(
        forecast_history,
        horizon="daily_30",
        granularity="daily",
    )
    if forecast_cap_outcomes["sample_count"] == 0:
        forecast_cap_outcomes = count_binary_outcomes(forecast_history, positive_key="within_p90")
    forecast_cap_bundle = build_trust(
        confidence_score=safe_float(projection["reliability"]["confidence_score"]),
        reliability_components=projection["reliability"].get("components"),
        abstain_recommended=bool(projection["reliability"].get("abstain_recommended")),
        prior_alpha=8.0,
        prior_beta=2.0,
        monitoring_status=str(calibration_monitoring["monitoring_status"]),
        success_count=forecast_cap_outcomes["success_count"],
        failure_count=forecast_cap_outcomes["failure_count"],
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
        window=build_window(history_start, as_of_dt),
        reliability=reliability,
        trust=trust_bundle["trust"],
        agent_use=trust_bundle["agent_use"],
        model_evidence=build_model_evidence(
            native_uncertainty=build_native_uncertainty(
                source=native_uncertainty_source,
                p10=native_uncertainty_summary["p10"],
                p50=native_uncertainty_summary["p50"],
                p90=native_uncertainty_summary["p90"],
                granularity="daily",
                points=[{key: value for key, value in point.items() if not key.startswith("_")} for point in forecast_points],
                inherited_from="cashflow_forecast_v1",
                used_for_output=False,
                interval_width_avg=ets_result.get("interval_width_avg") if ets_result.get("ready") else darts_result.get("interval_width_avg"),
            )
        ),
        provenance=build_provenance(
            library="heuristic_rules",
            model="jar_allocation_v2",
            model_version="allocation_v2",
            feature_set_version="jar_role_features_v2",
        ),
        validation=build_validation(
            jar_count=len(jars),
            tx_count=len(txns),
            month_count=len(monthly_debit),
            allocation_history_count=len(decision_history),
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
                "income": payload["baseline_monthly_income"],
                "confidence_score": result.get("reliability", {}).get("confidence_score"),
            },
        },
    )
    return result


