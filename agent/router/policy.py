from __future__ import annotations

import calendar
import re
import unicodedata
from typing import cast

from .clarify import build_clarifying_question
from .contracts import IntentExtractionV1, IntentName, RouteDecisionV1, RouterMode
from .policy_registry import build_override_context, get_intent_override_rules, get_routing_policy

_DEFAULT_ROUTING_POLICY = get_routing_policy("v1")
TOOL_BUNDLE_MAP: dict[IntentName, list[str]] = {
    cast(IntentName, intent): list(bundle)
    for intent, bundle in _DEFAULT_ROUTING_POLICY.tool_bundles.items()
}


def _normalize_prompt(prompt: str) -> str:
    base = str(prompt or "").replace("đ", "d").replace("Đ", "D")
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", base) if unicodedata.category(ch) != "Mn"
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
    out_of_scope_score = _top2_score(extraction, "out_of_scope")
    context = build_override_context(prompt, normalized, extraction, out_of_scope_score=out_of_scope_score)
    for rule in get_intent_override_rules("v1"):
        if rule.evaluator(context):
            return rule.target_intent, f"intent_override:{rule.rule_id}"
    return None, ""


def tool_bundle_for_intent(intent: str, policy_version: str = "v1") -> list[str]:
    policy = get_routing_policy(policy_version)
    if intent not in policy.tool_bundles:
        return list(policy.tool_bundles["summary"])
    return list(policy.tool_bundles[cast(IntentName, intent)])


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
        tool_bundle=[] if clarify_needed else tool_bundle_for_intent(extraction.intent, policy_version=policy_version),
        clarify_needed=clarify_needed,
        clarifying_question=clarifying_question,
        reason_codes=reason_codes,
        fallback_used=None,
        source="semantic",
    )
