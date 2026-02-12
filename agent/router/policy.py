from __future__ import annotations

import calendar
import re
import unicodedata
from typing import cast

from .clarify import build_clarifying_question
from .contracts import IntentExtractionV1, IntentName, RouteDecisionV1, RouterMode

TOOL_BUNDLE_MAP: dict[IntentName, list[str]] = {
    "summary": ["spend_analytics_v1", "cashflow_forecast_v1", "jar_allocation_suggest_v1"],
    "risk": ["spend_analytics_v1", "anomaly_signals_v1", "risk_profile_non_investment_v1"],
    "planning": [
        "spend_analytics_v1",
        "cashflow_forecast_v1",
        "recurring_cashflow_detect_v1",
        "goal_feasibility_v1",
        "jar_allocation_suggest_v1",
    ],
    "scenario": ["what_if_scenario_v1"],
    "invest": ["suitability_guard_v1", "risk_profile_non_investment_v1"],
    "out_of_scope": ["suitability_guard_v1"],
}


def _normalize_prompt(prompt: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", str(prompt or "")) if unicodedata.category(ch) != "Mn"
    )
    return stripped.lower()


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _has_invalid_calendar_date(text: str) -> bool:
    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text):
        day = int(match.group(1))
        month = int(match.group(2))
        year_text = match.group(3)
        year = int(year_text) if year_text else 2025
        if month < 1 or month > 12:
            return True
        max_day = calendar.monthrange(year, month)[1]
        if day < 1 or day > max_day:
            return True
    return False


def _has_scenario_delta(slots: dict[str, object]) -> bool:
    for key in ["income_delta_pct", "spend_delta_pct", "income_delta_amount_vnd", "spend_delta_amount_vnd", "variants"]:
        value = slots.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (int, float)) and float(value) == 0.0:
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        return True
    return False


def _top2_score(extraction: IntentExtractionV1, intent_name: IntentName) -> float:
    for item in extraction.top2:
        if item.intent == intent_name:
            return float(item.score)
    return 0.0


def _has_non_invest_purchase_goal(text: str, has_invest_terms: bool) -> bool:
    if has_invest_terms:
        return False
    if not re.search(r"\b(mua|buy)\b\s+\S", text):
        return False

    goal_cues = [
        "muc tieu",
        "ke hoach",
        "tiet kiem",
        "tra gop",
        "bao lau",
        "kha thi",
        "du tien",
        "ngan sach",
        "saving plan",
        "goal",
        "budget",
        "installment",
    ]
    if _contains_any(text, goal_cues):
        return True

    has_time_horizon = bool(re.search(r"\b(trong|sau)\s+\d{1,3}\s*(ngay|tuan|thang|nam|days?|weeks?|months?|years?)\b", text))
    has_budget_amount = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(k|nghin|ngan|trieu|ty|ti|m|million|billion)\b", text))
    return has_time_horizon or has_budget_amount


def suggest_intent_override(prompt: str, extraction: IntentExtractionV1) -> tuple[IntentName | None, str]:
    normalized = _normalize_prompt(prompt)
    domain_relevance = float(getattr(extraction, "domain_relevance", 1.0))
    out_of_scope_score = _top2_score(extraction, "out_of_scope")
    invest_terms = [
        "co phieu",
        "chung khoan",
        "crypto",
        "coin",
        "etf",
        "stock",
        "shares",
        "share",
        "bond",
        "trai phieu",
        "dau tu",
        "invest",
        "portfolio",
        "trade",
    ]
    optimize_terms = [
        "toi uu tai chinh",
        "toi uu tai chinh ca nhan",
        "quan ly tai chinh",
        "toi uu dong tien",
        "optimize personal finance",
        "financial optimization",
    ]
    anomaly_terms = [
        "giao dich la",
        "giao dich bat thuong",
        "bat thuong",
        "anomaly",
        "fraud",
        "lua dao",
        "suspicious transaction",
        "unrecognized transaction",
    ]
    planning_home_goal_terms = [
        "mua nha",
        "mua can ho",
        "mua xe",
        "mua o to",
        "mua oto",
        "muc tieu tiet kiem",
        "ke hoach tiet kiem",
        "saving goal",
        "goal",
        "saving plan",
        "bao lau",
        "kha thi",
    ]
    savings_deposit_terms = [
        "gui tiet kiem",
        "mo so tiet kiem",
        "lap so tiet kiem",
        "tiet kiem ky han",
        "goi tiet kiem",
        "term deposit",
        "fixed deposit",
        "recurring savings",
    ]
    recurring_terms = [
        "chi co dinh",
        "chi dinh ky",
        "dinh ky",
        "moi thang",
        "hang thang",
        "thuong xuyen",
        "fixed expense",
        "fixed cost",
        "recurring",
        "auto debit",
    ]
    service_priority_terms = [
        "dich vu ngan hang",
        "uu tien dich vu",
        "ngan hang nao truoc",
        "banking service",
        "service nao",
    ]
    cashflow_pressure_terms = [
        "dong tien am",
        "thieu hut dong tien",
        "negative cashflow",
        "cashflow am",
    ]
    finance_terms = [
        "chi tieu",
        "tieu",
        "dong tien",
        "thu nhap",
        "ngan sach",
        "tai chinh",
        "giao dich",
        "spend",
        "cashflow",
        "budget",
        "transaction",
        "saving",
        "tiet kiem",
    ]
    has_invest_terms = _contains_any(normalized, invest_terms) or bool(
        re.search(
            r"\b(mua|buy|ban|sell)\s+(co phieu|chung khoan|crypto|coin|etf|stock|shares?|portfolio|bond|trai phieu)\b",
            normalized,
        )
    )

    if extraction.intent == "invest" and _contains_any(normalized, optimize_terms) and not has_invest_terms:
        return "planning", "intent_override:invest_to_planning_optimize"

    if _contains_any(normalized, anomaly_terms) and not has_invest_terms:
        return "risk", "intent_override:anomaly_to_risk"

    if _contains_any(normalized, savings_deposit_terms) and not has_invest_terms:
        return "planning", "intent_override:savings_deposit_to_planning"

    if _contains_any(normalized, planning_home_goal_terms):
        return "planning", "intent_override:home_goal_to_planning"

    if _has_non_invest_purchase_goal(normalized, has_invest_terms):
        return "planning", "intent_override:purchase_goal_to_planning"

    if _contains_any(normalized, recurring_terms):
        return "planning", "intent_override:recurring_to_planning"

    if _contains_any(normalized, service_priority_terms) and _contains_any(normalized, cashflow_pressure_terms):
        return "planning", "intent_override:service_priority_to_planning"

    if (
        extraction.intent == "out_of_scope"
        and _contains_any(normalized, finance_terms)
        and _has_invalid_calendar_date(normalized)
    ):
        return "summary", "intent_override:oos_invalid_date_in_scope"

    if extraction.intent != "out_of_scope":
        if domain_relevance <= 0.25:
            return "out_of_scope", "intent_override:low_domain_relevance"
        if domain_relevance <= 0.40 and out_of_scope_score >= 0.30:
            return "out_of_scope", "intent_override:low_domain_relevance_top2_oos"

    if extraction.intent != "scenario":
        return None, ""
    slots = extraction.slots if isinstance(extraction.slots, dict) else {}
    has_delta = _has_scenario_delta(slots)

    what_if_terms = [
        "what if",
        "what-if",
        "scenario",
        "kich ban",
        "gia su",
        "neu",
        "if ",
    ]
    change_terms = [
        "giam",
        "tang",
        "cat",
        "thay doi",
        "reduce",
        "increase",
        "decrease",
        "drop",
        "up ",
        "down ",
    ]
    planning_terms = [
        "mua nha",
        "kha thi",
        "muc tieu",
        "tiet kiem",
        "bao lau",
        "goal",
        "saving plan",
        "ke hoach",
    ]
    risk_terms = [
        "rui ro",
        "risk",
        "canh bao",
        "khau vi",
        "volatility",
    ]
    summary_terms = [
        "dong tien",
        "chi tieu",
        "thu nhap",
        "tong quan",
        "khoan nao chi",
        "largest",
        "spending",
        "summary",
        "phan tich",
    ]

    explicit_what_if = _contains_any(normalized, what_if_terms)
    change_request = _contains_any(normalized, change_terms)
    if explicit_what_if or (has_delta and change_request):
        return None, ""

    if _contains_any(normalized, planning_terms):
        return "planning", "intent_override:scenario_to_planning"
    if _contains_any(normalized, risk_terms):
        return "risk", "intent_override:scenario_to_risk"
    if _contains_any(normalized, summary_terms):
        return "summary", "intent_override:scenario_to_summary"
    if not has_delta:
        return "summary", "intent_override:scenario_to_summary_default"
    return None, ""


def tool_bundle_for_intent(intent: str) -> list[str]:
    if intent not in TOOL_BUNDLE_MAP:
        return list(TOOL_BUNDLE_MAP["summary"])
    return list(TOOL_BUNDLE_MAP[cast(IntentName, intent)])


def build_route_decision(
    *,
    mode: RouterMode,
    extraction: IntentExtractionV1,
    policy_version: str,
    intent_conf_min: float,
    top2_gap_min: float,
    scenario_conf_min: float,
    max_clarify_questions: int,
    clarify_round: int = 0,
) -> RouteDecisionV1:
    reason_codes: list[str] = []

    if extraction.confidence < intent_conf_min:
        reason_codes.append("low_intent_confidence")
    if extraction.top2_gap() < top2_gap_min:
        reason_codes.append("low_top2_gap")

    if extraction.intent == "scenario":
        scenario_conf = extraction.scenario_confidence
        if scenario_conf is None:
            scenario_conf = extraction.confidence
        if scenario_conf < scenario_conf_min:
            reason_codes.append("low_scenario_confidence")

        slots = extraction.slots if isinstance(extraction.slots, dict) else {}
        if slots.get("horizon_months") in {None, "", 0}:
            reason_codes.append("scenario_horizon_missing")

        has_delta = any(
            slots.get(key) is not None
            for key in [
                "income_delta_pct",
                "spend_delta_pct",
                "income_delta_amount_vnd",
                "spend_delta_amount_vnd",
                "variants",
            ]
        )
        if not has_delta:
            reason_codes.append("scenario_delta_missing")

    clarify_needed = any(
        code in reason_codes
        for code in [
            "low_intent_confidence",
            "low_top2_gap",
            "low_scenario_confidence",
            "scenario_horizon_missing",
            "scenario_delta_missing",
        ]
    )

    if clarify_needed and clarify_round >= max_clarify_questions:
        return RouteDecisionV1(
            mode=mode,
            policy_version=policy_version,
            final_intent=extraction.intent,
            tool_bundle=[],
            clarify_needed=False,
            reason_codes=[*reason_codes, "clarify_exhausted"],
            fallback_used="clarify_exhausted",
            source="semantic",
        )

    clarifying_question = None
    if clarify_needed:
        clarifying_question = build_clarifying_question(
            extraction,
            reason_codes,
            max_questions=max_clarify_questions,
        )

    return RouteDecisionV1(
        mode=mode,
        policy_version=policy_version,
        final_intent=extraction.intent,
        tool_bundle=[] if clarify_needed else tool_bundle_for_intent(extraction.intent),
        clarify_needed=clarify_needed,
        clarifying_question=clarifying_question,
        reason_codes=reason_codes,
        fallback_used=None,
        source="semantic",
    )
