from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Mapping

from service_agent.constants import CLASS_READY, GOAL_TYPE_KEYWORDS
from service_agent.contracts import GoalInput, PlannerState, SavingsCapacity, SpecialistRequestEnvelope, StockContextInput, UserContextInput


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [_compact_text(item) for item in value if _compact_text(item)]
    if isinstance(value, tuple):
        return [_compact_text(item) for item in value if _compact_text(item)]
    text = _compact_text(value)
    return [text] if text else []


def _days_between(start: str, end: str) -> int | None:
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = (end_dt - start_dt).days
    return delta if delta > 0 else None


def _months_from_window(contract: Mapping[str, Any]) -> float | None:
    sections = contract.get("sections") if isinstance(contract.get("sections"), Mapping) else {}
    header = sections.get("HEADER") if isinstance(sections.get("HEADER"), Mapping) else {}
    start = _compact_text(header.get("analysis_window_start"))
    end = _compact_text(header.get("analysis_window_end"))
    days = _days_between(start, end)
    if days is None:
        days = _safe_int(header.get("analysis_window_days"))
    if not days:
        return None
    return max(days / 30.0, 1.0)


def _label_for_capacity(amount_monthly: float | None) -> str:
    if amount_monthly is None:
        return "unknown"
    if amount_monthly <= 0:
        return "none"
    if amount_monthly < 2_000_000:
        return "low"
    if amount_monthly < 8_000_000:
        return "moderate"
    return "strong"


def _liquidity_pressure(runway_months: float | None, stability_band: str) -> str:
    if runway_months is not None:
        if runway_months < 1.0:
            return "critical"
        if runway_months < 3.0:
            return "high"
        if runway_months < 6.0:
            return "medium"
        return "low"
    if stability_band == "fragile":
        return "high"
    if stability_band == "watch":
        return "medium"
    if stability_band == "stable":
        return "low"
    return "unknown"


def _anomaly_state(flags: Any, runtime_alerts: Any) -> str:
    has_flags = isinstance(flags, list) and bool(flags)
    has_alerts = isinstance(runtime_alerts, list) and bool(runtime_alerts)
    if has_flags or has_alerts:
        return "active"
    return "none"


def _feasibility_hint(goal_payload: Mapping[str, Any] | None) -> str:
    payload = goal_payload or {}
    grade = _compact_text(payload.get("grade")).upper()
    probability = _safe_float(payload.get("probability_of_success"))
    gap_amount = _safe_float(payload.get("gap_amount"))
    if grade == "A" or (probability is not None and probability >= 0.75):
        return "high"
    if grade == "B" or (probability is not None and probability >= 0.45):
        return "medium"
    if gap_amount is not None and gap_amount > 0:
        return "stretch"
    return "low"


def _goal_type_from_prompt(prompt: str) -> str | None:
    lowered = prompt.lower()
    for goal_type, markers in GOAL_TYPE_KEYWORDS.items():
        if any(marker in lowered for marker in markers):
            return goal_type
    return None


def _goal_from_prompt(prompt: str) -> GoalInput:
    lowered = prompt.lower()
    goal_type = _goal_type_from_prompt(prompt)
    timeline_match = re.search(r"(\d+)\s*(months?|thang)", lowered)
    amount_match = re.search(r"(\d[\d,\.]*)\s*(m|mn|million|b|bn|billion|k)?", lowered)
    timeline = _safe_int(timeline_match.group(1)) if timeline_match else None
    amount = None
    if amount_match:
        raw_value = str(amount_match.group(1) or "").replace(",", "")
        base = _safe_float(raw_value)
        suffix = _compact_text(amount_match.group(2)).lower()
        if base is not None:
            multiplier = 1.0
            if suffix == "k":
                multiplier = 1_000.0
            elif suffix in {"m", "mn", "million"}:
                multiplier = 1_000_000.0
            elif suffix in {"b", "bn", "billion"}:
                multiplier = 1_000_000_000.0
            if multiplier != 1.0:
                amount = base * multiplier
    return GoalInput(
        goal_type=goal_type,
        target_amount=amount,
        target_timeline_months=timeline,
        priority="high" if "urgent" in lowered or "asap" in lowered else "medium",
    )


def _goal_from_request(request: SpecialistRequestEnvelope) -> GoalInput:
    raw_goals = request.request.goals or []
    first = raw_goals[0] if raw_goals and isinstance(raw_goals[0], dict) else {}
    inferred = _goal_from_prompt(request.request.prompt)
    return GoalInput(
        goal_type=_compact_text(first.get("goal_type") or first.get("name")) or inferred.goal_type,
        target_amount=_safe_float(first.get("target_amount")) or inferred.target_amount,
        target_timeline_months=_safe_int(first.get("target_timeline_months") or first.get("horizon_months")) or inferred.target_timeline_months,
        priority=_compact_text(first.get("priority")) or inferred.priority or "medium",
        target_date=_compact_text(first.get("target_date")) or None,
    )


def _planner_state_from_contract(contract: Mapping[str, Any], goal: GoalInput) -> PlannerState:
    sections = contract.get("sections") if isinstance(contract.get("sections"), Mapping) else {}
    executive = sections.get("EXECUTIVE_SUMMARY") if isinstance(sections.get("EXECUTIVE_SUMMARY"), Mapping) else {}
    core = sections.get("CORE_FINANCIAL_ANALYSIS") if isinstance(sections.get("CORE_FINANCIAL_ANALYSIS"), Mapping) else {}
    observed_cashflow = core.get("observed_cashflow") if isinstance(core.get("observed_cashflow"), Mapping) else {}
    observed_anomaly = core.get("observed_anomaly") if isinstance(core.get("observed_anomaly"), Mapping) else {}
    computed_risk = core.get("computed_risk") if isinstance(core.get("computed_risk"), Mapping) else {}
    computed_goal = core.get("computed_goal_planning") if isinstance(core.get("computed_goal_planning"), Mapping) else {}

    observed_net = _safe_float(executive.get("observed_net_cashflow"))
    window_months = _months_from_window(contract)
    amount_monthly = None
    if observed_net is not None and window_months:
        amount_monthly = observed_net / max(window_months, 1.0)

    latest_balance = _safe_float(executive.get("observed_latest_buffer_balance"))
    target_amount = goal.target_amount
    goal_progress_ratio = None
    if latest_balance is not None and target_amount and target_amount > 0:
        goal_progress_ratio = max(0.0, min(1.0, latest_balance / target_amount))

    required_monthly = _safe_float(computed_goal.get("required_monthly_saving"))
    required_pace_ratio = None
    if required_monthly is not None and amount_monthly is not None and amount_monthly > 0:
        required_pace_ratio = required_monthly / amount_monthly

    cashflow_status = "unknown"
    if observed_net is not None:
        if observed_net > 0:
            cashflow_status = "positive"
        elif observed_net < 0:
            cashflow_status = "negative"
        else:
            cashflow_status = "flat"

    stability_band = _compact_text(executive.get("computed_financial_stability_band")).lower()
    runway_months = _safe_float(computed_risk.get("emergency_runway_months"))

    return PlannerState(
        cashflow_status=cashflow_status,
        savings_capacity=SavingsCapacity(amount_monthly=amount_monthly, label=_label_for_capacity(amount_monthly)),
        runway_months=runway_months,
        liquidity_pressure=_liquidity_pressure(runway_months, stability_band),
        anomaly_state=_anomaly_state(observed_anomaly.get("flags"), observed_anomaly.get("runtime_alerts")),
        readiness_label=_compact_text(executive.get("computed_planning_readiness")).lower() or "unknown",
        feasibility_hint=_feasibility_hint(computed_goal),
        risk_band=_compact_text(executive.get("computed_risk_band") or computed_risk.get("risk_band")).lower() or "unknown",
        income_stability=None,
        goal_progress_ratio=goal_progress_ratio,
        buffer_status="present" if latest_balance and latest_balance > 0 else "missing",
        required_pace_vs_current_pace=required_pace_ratio,
        source="planner_standardized_contract",
    )


def _planner_state_from_dict(raw: Mapping[str, Any]) -> PlannerState:
    savings = raw.get("savings_capacity") if isinstance(raw.get("savings_capacity"), Mapping) else {}
    amount_monthly = _safe_float(savings.get("amount_monthly")) if isinstance(savings, Mapping) else _safe_float(raw.get("savings_capacity_amount_monthly"))
    return PlannerState(
        cashflow_status=_compact_text(raw.get("cashflow_status")).lower() or "unknown",
        savings_capacity=SavingsCapacity(
            amount_monthly=amount_monthly,
            label=_compact_text(savings.get("label") if isinstance(savings, Mapping) else "").lower() or _label_for_capacity(amount_monthly),
        ),
        runway_months=_safe_float(raw.get("runway_months")),
        liquidity_pressure=_compact_text(raw.get("liquidity_pressure")).lower() or "unknown",
        anomaly_state=_compact_text(raw.get("anomaly_state")).lower() or "unknown",
        readiness_label=_compact_text(raw.get("readiness_label")).lower() or "unknown",
        feasibility_hint=_compact_text(raw.get("feasibility_hint")).lower() or "unknown",
        risk_band=_compact_text(raw.get("risk_band")).lower() or "unknown",
        income_stability=_compact_text(raw.get("income_stability")) or None,
        goal_progress_ratio=_safe_float(raw.get("goal_progress_ratio")),
        buffer_status=_compact_text(raw.get("buffer_status")) or None,
        required_pace_vs_current_pace=_safe_float(raw.get("required_pace_vs_current_pace")),
        source=_compact_text(raw.get("source")) or "planner_state",
    )


def _stock_context_from_envelope(payload: Mapping[str, Any]) -> StockContextInput | None:
    result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    suitability = result.get("suitability") if isinstance(result.get("suitability"), Mapping) else {}
    recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
    alternatives = result.get("alternatives") if isinstance(result.get("alternatives"), list) else []
    market_snapshot = result.get("market_snapshot") if isinstance(result.get("market_snapshot"), Mapping) else {}
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else result.get("warnings")
    warning_flags: List[str] = []
    for item in warnings if isinstance(warnings, list) else []:
        if isinstance(item, Mapping):
            code = _compact_text(item.get("code"))
            message = _compact_text(item.get("message"))
            warning_flags.extend([part for part in (code, message) if part])
        else:
            warning_flags.extend(_text_list(item))
    cited_symbols = [
        _compact_text(item.get("ticker") or item.get("symbol"))
        for item in recommendations
        if isinstance(item, Mapping) and _compact_text(item.get("ticker") or item.get("symbol"))
    ]
    for item in alternatives:
        if not isinstance(item, Mapping):
            continue
        symbol = _compact_text(item.get("ticker") or item.get("symbol"))
        if symbol and symbol not in cited_symbols and symbol != "GENERAL":
            cited_symbols.append(symbol)
    if isinstance(market_snapshot.get("highlighted_symbols"), list):
        for item in market_snapshot.get("highlighted_symbols", []):
            symbol = _compact_text(item)
            if symbol and symbol not in cited_symbols:
                cited_symbols.append(symbol)

    explicit_market_tone = _compact_text(result.get("market_tone") or payload.get("market_tone")).lower() or None
    suitability_status = _compact_text(suitability.get("status")).lower() or None
    if explicit_market_tone:
        market_tone = explicit_market_tone
    elif suitability_status in {"fail", "blocked", "warn", "deny"} or bool(warning_flags):
        market_tone = "cautious"
    elif suitability_status in {"pass", "ok", "constructive", "supportive"}:
        market_tone = "constructive"
    else:
        market_tone = "unknown"

    market_notes = _text_list(result.get("market_notes"))
    if not market_notes and isinstance(market_snapshot.get("market_notes"), list):
        market_notes = _text_list(market_snapshot.get("market_notes"))

    stock_context = StockContextInput(
        summary=_compact_text(result.get("summary") or payload.get("summary")) or None,
        suitability_status=suitability_status,
        market_tone=market_tone,
        market_notes=market_notes,
        warning_flags=warning_flags,
        cited_symbols=cited_symbols,
        source=_compact_text(payload.get("tool_name") or payload.get("agent_id")) or "stock_envelope",
    )
    if stock_context.model_dump(exclude_none=True, exclude_defaults=True):
        return stock_context
    return None


def stock_context_dict_from_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    stock_context = _stock_context_from_envelope(payload)
    if stock_context is None:
        return {}
    return stock_context.model_dump(exclude_none=True, exclude_defaults=True)


def _stock_context_from_request(raw: Mapping[str, Any]) -> StockContextInput | None:
    direct = raw.get("stock_context")
    if isinstance(direct, Mapping):
        stock_context = StockContextInput(
            summary=_compact_text(direct.get("summary")) or None,
            suitability_status=_compact_text(direct.get("suitability_status")) or None,
            market_tone=_compact_text(direct.get("market_tone")) or None,
            market_notes=_text_list(direct.get("market_notes")),
            warning_flags=_text_list(direct.get("warning_flags")),
            cited_symbols=_text_list(direct.get("cited_symbols")),
            source=_compact_text(direct.get("source")) or "user_context.stock_context",
        )
        if stock_context.model_dump(exclude_none=True, exclude_defaults=True):
            return stock_context

    for key in ("last_stock_advisory", "stock_advisory", "stock_envelope", "stock_specialist_result"):
        candidate = raw.get(key)
        if isinstance(candidate, Mapping):
            stock_context = _stock_context_from_envelope(candidate)
            if stock_context:
                return stock_context
    return None


def _user_context_from_request(request: SpecialistRequestEnvelope) -> UserContextInput:
    raw = request.request.user_context or {}
    return UserContextInput(
        risk_preference=_compact_text(raw.get("risk_preference") or raw.get("risk_appetite")) or None,
        liquidity_need=_compact_text(raw.get("liquidity_need")) or None,
        urgency=_compact_text(raw.get("urgency")) or None,
        life_context=_compact_text(raw.get("life_context")) or None,
        stock_context=_stock_context_from_request(raw) if isinstance(raw, Mapping) else None,
    )


@dataclass
class RoadmapContext:
    request: SpecialistRequestEnvelope
    prompt: str
    planner_state: PlannerState
    goal: GoalInput
    user_context: UserContextInput
    missing_fields: List[str] = field(default_factory=list)
    readiness_class: str = CLASS_READY
    warnings: List[str] = field(default_factory=list)

    def normalized_key(self) -> str:
        payload = {
            "prompt": self.prompt,
            "planner_state": self.planner_state.model_dump(exclude_none=True),
            "goal": self.goal.model_dump(exclude_none=True),
            "user_context": self.user_context.model_dump(exclude_none=True),
            "readiness_class": self.readiness_class,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def normalize_request(request: SpecialistRequestEnvelope) -> RoadmapContext:
    user_context_raw = request.request.user_context or {}
    goal = _goal_from_request(request)
    planner_state = PlannerState()
    if isinstance(user_context_raw.get("planner_state"), Mapping):
        planner_state = _planner_state_from_dict(user_context_raw["planner_state"])
    else:
        for key in ("planner_standardized_contract", "planner_contract", "last_planner_contract"):
            candidate = user_context_raw.get(key)
            if isinstance(candidate, Mapping):
                planner_state = _planner_state_from_contract(candidate, goal)
                break
    return RoadmapContext(
        request=request,
        prompt=request.request.prompt,
        planner_state=planner_state,
        goal=goal,
        user_context=_user_context_from_request(request),
    )


def classify_missing_fields(context: RoadmapContext) -> List[str]:
    missing: List[str] = []
    if not _compact_text(context.goal.goal_type):
        missing.append("goal.goal_type")
    if not context.goal.target_amount or context.goal.target_amount <= 0:
        missing.append("goal.target_amount")
    if not context.goal.target_timeline_months or context.goal.target_timeline_months <= 0:
        missing.append("goal.target_timeline_months")
    planner = context.planner_state
    for field_name in (
        "cashflow_status",
        "liquidity_pressure",
        "anomaly_state",
        "readiness_label",
        "feasibility_hint",
        "risk_band",
    ):
        if _compact_text(getattr(planner, field_name, "")).lower() in {"", "unknown"}:
            missing.append(f"planner_state.{field_name}")
    if planner.runway_months is None:
        missing.append("planner_state.runway_months")
    if planner.savings_capacity.amount_monthly is None:
        missing.append("planner_state.savings_capacity.amount_monthly")
    return missing
