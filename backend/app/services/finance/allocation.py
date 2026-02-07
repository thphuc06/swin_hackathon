from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from app.services.supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    daterange_start,
    ensure_user_scope,
    iso_utc,
    new_trace_id,
    now_utc,
    parse_datetime,
    safe_float,
)
from .data import (
    fetch_goals,
    fetch_jars,
    fetch_transactions_in_window,
    write_audit_event,
)

TOOL_NAME = "jar_allocation_suggest_v1"


def _jar_lookup(jars: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for row in jars:
        jar_id = str(row.get("id") or "")
        name = str(row.get("name") or "").strip().lower()
        if jar_id and name:
            mapping[name] = jar_id
    return mapping


def _pick_jar_id(jars: List[Dict[str, Any]], preferred_names: List[str]) -> str:
    name_map = _jar_lookup(jars)
    for name in preferred_names:
        jar_id = name_map.get(name.lower())
        if jar_id:
            return jar_id
    return str(jars[0].get("id")) if jars else ""


def _monthly_average(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


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
    history_start = daterange_start(as_of_dt, 120)
    sql = client or get_supabase_client()

    jars = fetch_jars(sql, user_id)
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=history_start, end_at=as_of_dt)
    goals = goal_overrides if goal_overrides is not None else fetch_goals(sql, user_id)

    if not jars:
        raise ValueError("No jars found for user. Seed jars before requesting allocation suggestion.")

    monthly_income: Dict[str, float] = defaultdict(float)
    monthly_debit: Dict[str, float] = defaultdict(float)
    monthly_debit_by_jar: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

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
        else:
            monthly_debit[month_key] += amount
            monthly_debit_by_jar[month_key][jar_id] += amount

    income_values = list(monthly_income.values())
    debit_values = list(monthly_debit.values())

    baseline_income = _monthly_average(income_values)
    if monthly_income_override is not None and monthly_income_override > 0:
        baseline_income = monthly_income_override

    bills_jar_id = _pick_jar_id(jars, ["Bills"])
    emergency_jar_id = _pick_jar_id(jars, ["Emergency"])
    goals_jar_id = _pick_jar_id(jars, ["Goals"])
    living_jar_id = _pick_jar_id(jars, ["Living"])
    misc_jar_id = _pick_jar_id(jars, ["Misc"])

    monthly_bills_need = 0.0
    monthly_living_need = 0.0
    if bills_jar_id:
        monthly_bills_need = _monthly_average([
            safe_float(month_data.get(bills_jar_id)) for month_data in monthly_debit_by_jar.values()
        ])
    if living_jar_id:
        monthly_living_need = _monthly_average([
            safe_float(month_data.get(living_jar_id)) for month_data in monthly_debit_by_jar.values()
        ])

    monthly_goal_need = 0.0
    for goal in goals:
        target = safe_float(goal.get("target_amount"))
        horizon = max(1, int(safe_float(goal.get("horizon_months"), 12)))
        monthly_goal_need += target / horizon

    allocations: List[Dict[str, Any]] = []
    remaining = max(0.0, baseline_income)
    constraints: List[str] = []

    bills_amount = min(remaining, monthly_bills_need)
    remaining -= bills_amount
    allocations.append({"jar_id": bills_jar_id, "amount": round(bills_amount, 2), "reason": "fixed_cost_coverage"})

    emergency_floor = max(0.0, baseline_income * 0.2)
    emergency_amount = min(remaining, emergency_floor)
    remaining -= emergency_amount
    allocations.append({"jar_id": emergency_jar_id, "amount": round(emergency_amount, 2), "reason": "emergency_buffer_floor"})

    goals_amount = min(remaining, monthly_goal_need)
    remaining -= goals_amount
    allocations.append({"jar_id": goals_jar_id, "amount": round(goals_amount, 2), "reason": "goal_funding"})

    living_amount = min(remaining, max(monthly_living_need, baseline_income * 0.25))
    remaining -= living_amount
    allocations.append({"jar_id": living_jar_id, "amount": round(living_amount, 2), "reason": "living_expense_provision"})

    misc_amount = max(0.0, remaining)
    remaining = 0.0
    allocations.append({"jar_id": misc_jar_id, "amount": round(misc_amount, 2), "reason": "discretionary_remaining"})

    jar_name_by_id = {str(j.get("id")): str(j.get("name") or "Unknown") for j in jars}
    total_allocated = sum(item["amount"] for item in allocations)
    if baseline_income > 0 and total_allocated > baseline_income:
        constraints.append("allocation_clipped_to_income")

    shaped_allocations = []
    for item in allocations:
        amount = safe_float(item["amount"])
        ratio = amount / baseline_income if baseline_income > 0 else 0.0
        shaped_allocations.append(
            {
                "jar_id": item["jar_id"],
                "jar_name": jar_name_by_id.get(item["jar_id"], "Unknown"),
                "amount": round(amount, 2),
                "ratio": round(ratio, 4),
                "reason": item["reason"],
            }
        )

    tool_input = {
        "user_id": user_id,
        "monthly_income_override": monthly_income_override,
        "goal_overrides": goal_overrides or [],
        "as_of": iso_utc(as_of_dt),
    }
    payload = {
        "baseline_monthly_income": round(baseline_income, 2),
        "monthly_reference_spend": round(_monthly_average(debit_values), 2),
        "allocations": shaped_allocations,
        "leftover": round(remaining, 2),
        "constraints_applied": constraints,
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
        payload={"params": tool_input, "result": {"income": payload["baseline_monthly_income"]}},
    )
    return result
