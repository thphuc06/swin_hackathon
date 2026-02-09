from __future__ import annotations

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


def suggest_intent_override(prompt: str, extraction: IntentExtractionV1) -> tuple[IntentName | None, str]:
    domain_relevance = float(getattr(extraction, "domain_relevance", 1.0))
    out_of_scope_score = _top2_score(extraction, "out_of_scope")
    if extraction.intent != "out_of_scope":
        if domain_relevance <= 0.25:
            return "out_of_scope", "intent_override:low_domain_relevance"
        if domain_relevance <= 0.40 and out_of_scope_score >= 0.30:
            return "out_of_scope", "intent_override:low_domain_relevance_top2_oos"

    if extraction.intent != "scenario":
        return None, ""

    normalized = _normalize_prompt(prompt)
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
