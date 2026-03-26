from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Callable, Mapping

from .contracts import IntentExtractionV1, IntentName


@dataclass(frozen=True)
class RoutingPolicyConfig:
    version: str
    owner: str
    tool_bundles: Mapping[IntentName, tuple[str, ...]]


@dataclass(frozen=True)
class IntentOverrideContext:
    prompt: str
    normalized_prompt: str
    extraction: IntentExtractionV1
    domain_relevance: float
    out_of_scope_score: float
    has_invest_terms: bool


@dataclass(frozen=True)
class IntentOverrideRule:
    rule_id: str
    owner: str
    classification: str
    target_intent: IntentName
    evaluator: Callable[[IntentOverrideContext], bool]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
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


def _has_non_invest_purchase_goal(text: str, has_invest_terms: bool) -> bool:
    if has_invest_terms:
        return False
    if not re.search(r"\b(mua|buy)\b\s+\S", text):
        return False

    goal_cues = (
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
    )
    if _contains_any(text, goal_cues):
        return True

    has_time_horizon = bool(re.search(r"\b(trong|sau)\s+\d{1,3}\s*(ngay|tuan|thang|nam|days?|weeks?|months?|years?)\b", text))
    has_budget_amount = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(k|nghin|ngan|trieu|ty|ti|m|million|billion)\b", text))
    return has_time_horizon or has_budget_amount


_INVEST_TERMS = (
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
)
_OPTIMIZE_TERMS = (
    "toi uu tai chinh",
    "toi uu tai chinh ca nhan",
    "quan ly tai chinh",
    "toi uu dong tien",
    "optimize personal finance",
    "financial optimization",
)
_ANOMALY_TERMS = (
    "giao dich la",
    "giao dich bat thuong",
    "bat thuong",
    "anomaly",
    "fraud",
    "lua dao",
    "suspicious transaction",
    "unrecognized transaction",
)
_RISK_PRIORITY_TERMS = (
    "danh gia rui ro",
    "rui ro dong tien",
    "canh bao",
    "bat thuong",
    "anomaly",
    "volatility",
    "runway",
    "risk assessment",
    "cashflow risk",
)
_PLANNING_HOME_GOAL_TERMS = (
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
)
_SAVINGS_DEPOSIT_TERMS = (
    "gui tiet kiem",
    "mo so tiet kiem",
    "lap so tiet kiem",
    "tiet kiem ky han",
    "goi tiet kiem",
    "term deposit",
    "fixed deposit",
    "recurring savings",
)
_RECURRING_TERMS = (
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
)
_SERVICE_PRIORITY_TERMS = (
    "dich vu ngan hang",
    "uu tien dich vu",
    "ngan hang nao truoc",
    "banking service",
    "service nao",
)
_CASHFLOW_PRESSURE_TERMS = (
    "dong tien am",
    "thieu hut dong tien",
    "negative cashflow",
    "cashflow am",
)
_FINANCE_TERMS = (
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
)
_SCENARIO_WHAT_IF_TERMS = ("what if", "what-if", "scenario", "kich ban", "gia su", "neu", "if ")
_SCENARIO_CHANGE_TERMS = ("giam", "tang", "cat", "thay doi", "reduce", "increase", "decrease", "drop", "up ", "down ")
_SCENARIO_PLANNING_TERMS = ("mua nha", "kha thi", "muc tieu", "tiet kiem", "bao lau", "goal", "saving plan", "ke hoach")
_SCENARIO_RISK_TERMS = ("rui ro", "risk", "canh bao", "khau vi", "volatility")
_SCENARIO_SUMMARY_TERMS = ("dong tien", "chi tieu", "thu nhap", "tong quan", "khoan nao chi", "largest", "spending", "summary", "phan tich")


def _has_invest_terms(normalized_prompt: str) -> bool:
    return _contains_any(normalized_prompt, _INVEST_TERMS) or bool(
        re.search(
            r"\b(mua|buy|ban|sell)\s+(co phieu|chung khoan|crypto|coin|etf|stock|shares?|portfolio|bond|trai phieu)\b",
            normalized_prompt,
        )
    )


def _rule_invest_to_planning_optimize(ctx: IntentOverrideContext) -> bool:
    return ctx.extraction.intent == "invest" and _contains_any(ctx.normalized_prompt, _OPTIMIZE_TERMS) and not ctx.has_invest_terms


def _rule_invest_terms_to_invest(ctx: IntentOverrideContext) -> bool:
    if not ctx.has_invest_terms:
        return False
    if ctx.extraction.intent == "invest":
        return False
    return True


def _rule_anomaly_to_risk(ctx: IntentOverrideContext) -> bool:
    return _contains_any(ctx.normalized_prompt, _ANOMALY_TERMS) and not ctx.has_invest_terms


def _rule_risk_priority_keywords(ctx: IntentOverrideContext) -> bool:
    return ctx.extraction.intent in {"summary", "planning"} and _contains_any(ctx.normalized_prompt, _RISK_PRIORITY_TERMS) and not ctx.has_invest_terms


def _rule_savings_deposit_to_planning(ctx: IntentOverrideContext) -> bool:
    return _contains_any(ctx.normalized_prompt, _SAVINGS_DEPOSIT_TERMS) and not ctx.has_invest_terms


def _rule_home_goal_to_planning(ctx: IntentOverrideContext) -> bool:
    return _contains_any(ctx.normalized_prompt, _PLANNING_HOME_GOAL_TERMS)


def _rule_purchase_goal_to_planning(ctx: IntentOverrideContext) -> bool:
    return _has_non_invest_purchase_goal(ctx.normalized_prompt, ctx.has_invest_terms)


def _rule_recurring_to_planning(ctx: IntentOverrideContext) -> bool:
    return _contains_any(ctx.normalized_prompt, _RECURRING_TERMS)


def _rule_service_priority_to_planning(ctx: IntentOverrideContext) -> bool:
    return _contains_any(ctx.normalized_prompt, _SERVICE_PRIORITY_TERMS) and _contains_any(ctx.normalized_prompt, _CASHFLOW_PRESSURE_TERMS)


def _rule_oos_invalid_date_in_scope(ctx: IntentOverrideContext) -> bool:
    return ctx.extraction.intent == "out_of_scope" and _contains_any(ctx.normalized_prompt, _FINANCE_TERMS) and _has_invalid_calendar_date(ctx.normalized_prompt)


def _rule_low_domain_relevance(ctx: IntentOverrideContext) -> bool:
    return ctx.extraction.intent != "out_of_scope" and ctx.domain_relevance <= 0.25


def _rule_low_domain_relevance_top2_oos(ctx: IntentOverrideContext) -> bool:
    return (
        ctx.extraction.intent != "out_of_scope"
        and ctx.domain_relevance <= 0.40
        and ctx.out_of_scope_score >= 0.30
    )


def _rule_scenario_to_planning(ctx: IntentOverrideContext) -> bool:
    if ctx.extraction.intent != "scenario":
        return False
    slots = ctx.extraction.slots if isinstance(ctx.extraction.slots, dict) else {}
    explicit_what_if = _contains_any(ctx.normalized_prompt, _SCENARIO_WHAT_IF_TERMS)
    change_request = _contains_any(ctx.normalized_prompt, _SCENARIO_CHANGE_TERMS)
    if explicit_what_if or (_has_scenario_delta(slots) and change_request):
        return False
    return _contains_any(ctx.normalized_prompt, _SCENARIO_PLANNING_TERMS)


def _rule_scenario_to_risk(ctx: IntentOverrideContext) -> bool:
    if ctx.extraction.intent != "scenario":
        return False
    slots = ctx.extraction.slots if isinstance(ctx.extraction.slots, dict) else {}
    explicit_what_if = _contains_any(ctx.normalized_prompt, _SCENARIO_WHAT_IF_TERMS)
    change_request = _contains_any(ctx.normalized_prompt, _SCENARIO_CHANGE_TERMS)
    if explicit_what_if or (_has_scenario_delta(slots) and change_request):
        return False
    return _contains_any(ctx.normalized_prompt, _SCENARIO_RISK_TERMS)


def _rule_scenario_to_summary(ctx: IntentOverrideContext) -> bool:
    if ctx.extraction.intent != "scenario":
        return False
    slots = ctx.extraction.slots if isinstance(ctx.extraction.slots, dict) else {}
    explicit_what_if = _contains_any(ctx.normalized_prompt, _SCENARIO_WHAT_IF_TERMS)
    change_request = _contains_any(ctx.normalized_prompt, _SCENARIO_CHANGE_TERMS)
    if explicit_what_if or (_has_scenario_delta(slots) and change_request):
        return False
    return _contains_any(ctx.normalized_prompt, _SCENARIO_SUMMARY_TERMS)


def _rule_scenario_to_summary_default(ctx: IntentOverrideContext) -> bool:
    if ctx.extraction.intent != "scenario":
        return False
    slots = ctx.extraction.slots if isinstance(ctx.extraction.slots, dict) else {}
    explicit_what_if = _contains_any(ctx.normalized_prompt, _SCENARIO_WHAT_IF_TERMS)
    change_request = _contains_any(ctx.normalized_prompt, _SCENARIO_CHANGE_TERMS)
    if explicit_what_if or (_has_scenario_delta(slots) and change_request):
        return False
    return not _has_scenario_delta(slots)


ROUTING_POLICY_REGISTRY: dict[str, RoutingPolicyConfig] = {
    "v1": RoutingPolicyConfig(
        version="v1",
        owner="platform-routing",
        tool_bundles={
            "summary": ("spend_analytics_v1", "cashflow_forecast_v1", "jar_allocation_suggest_v1"),
            "risk": ("anomaly_signals_v1", "risk_profile_non_investment_v1", "spend_analytics_v1"),
            "planning": (
                "spend_analytics_v1",
                "cashflow_forecast_v1",
                "recurring_cashflow_detect_v1",
                "goal_feasibility_v1",
                "jar_allocation_suggest_v1",
                "run_service_agent_v1",
            ),
            "scenario": ("what_if_scenario_v1",),
            "invest": ("suitability_guard_v1", "risk_profile_non_investment_v1", "run_stock_agent_v1"),
            "out_of_scope": ("suitability_guard_v1",),
        },
    )
}

INTENT_OVERRIDE_RULES_REGISTRY: dict[str, tuple[IntentOverrideRule, ...]] = {
    "v1": (
        IntentOverrideRule("invest_to_planning_optimize", "platform-routing", "policy", "planning", _rule_invest_to_planning_optimize),
        IntentOverrideRule("invest_terms_to_invest", "platform-routing", "temporary_heuristic", "invest", _rule_invest_terms_to_invest),
        IntentOverrideRule("anomaly_to_risk", "platform-routing", "policy", "risk", _rule_anomaly_to_risk),
        IntentOverrideRule("risk_priority_keywords", "platform-routing", "temporary_heuristic", "risk", _rule_risk_priority_keywords),
        IntentOverrideRule("savings_deposit_to_planning", "platform-routing", "policy", "planning", _rule_savings_deposit_to_planning),
        IntentOverrideRule("home_goal_to_planning", "platform-routing", "policy", "planning", _rule_home_goal_to_planning),
        IntentOverrideRule("purchase_goal_to_planning", "platform-routing", "temporary_heuristic", "planning", _rule_purchase_goal_to_planning),
        IntentOverrideRule("recurring_to_planning", "platform-routing", "policy", "planning", _rule_recurring_to_planning),
        IntentOverrideRule("service_priority_to_planning", "platform-routing", "temporary_heuristic", "planning", _rule_service_priority_to_planning),
        IntentOverrideRule("oos_invalid_date_in_scope", "platform-routing", "temporary_heuristic", "summary", _rule_oos_invalid_date_in_scope),
        IntentOverrideRule("low_domain_relevance", "platform-routing", "policy", "out_of_scope", _rule_low_domain_relevance),
        IntentOverrideRule("low_domain_relevance_top2_oos", "platform-routing", "policy", "out_of_scope", _rule_low_domain_relevance_top2_oos),
        IntentOverrideRule("scenario_to_planning", "platform-routing", "temporary_heuristic", "planning", _rule_scenario_to_planning),
        IntentOverrideRule("scenario_to_risk", "platform-routing", "temporary_heuristic", "risk", _rule_scenario_to_risk),
        IntentOverrideRule("scenario_to_summary", "platform-routing", "temporary_heuristic", "summary", _rule_scenario_to_summary),
        IntentOverrideRule("scenario_to_summary_default", "platform-routing", "temporary_heuristic", "summary", _rule_scenario_to_summary_default),
    )
}


def get_routing_policy(version: str) -> RoutingPolicyConfig:
    return ROUTING_POLICY_REGISTRY[version]


def get_intent_override_rules(version: str) -> tuple[IntentOverrideRule, ...]:
    return INTENT_OVERRIDE_RULES_REGISTRY[version]


def build_override_context(prompt: str, normalized_prompt: str, extraction: IntentExtractionV1, *, out_of_scope_score: float) -> IntentOverrideContext:
    return IntentOverrideContext(
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        extraction=extraction,
        domain_relevance=float(getattr(extraction, "domain_relevance", 1.0)),
        out_of_scope_score=out_of_scope_score,
        has_invest_terms=_has_invest_terms(normalized_prompt),
    )


def override_rule_snapshot(version: str) -> list[dict[str, str]]:
    return [
        {
            "rule_id": rule.rule_id,
            "owner": rule.owner,
            "classification": rule.classification,
            "target_intent": rule.target_intent,
        }
        for rule in get_intent_override_rules(version)
    ]
