from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict

from app.supabase_rest import SupabaseRestClient, get_supabase_client

from .common import build_output, ensure_user_scope, iso_utc, new_trace_id, now_utc
from .data import write_decision_event

TOOL_NAME = "suitability_guard_v1"
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."

EXECUTION_ACTIONS = {"buy", "sell", "execute", "trade", "order", "transfer_funds"}
RECOMMENDATION_ACTIONS = {"recommend_buy", "recommend_sell", "recommend_trade"}
INVEST_ASSET_KEYWORDS = {
    "invest",
    "stock",
    "etf",
    "crypto",
    "coin",
    "shares",
    "share",
    "portfolio",
    "bond",
    "trai phieu",
    "chung khoan",
    "co phieu",
    "dau tu",
}

NON_INVEST_PLANNING_TERMS = {
    "mua nha",
    "mua can ho",
    "mua xe",
    "mua o to",
    "mua oto",
    "muc tieu tiet kiem",
    "ke hoach tiet kiem",
    "saving goal",
    "buy house",
    "buy home",
    "buy car",
}


def _contains_invest_asset_context(text: str) -> bool:
    normalized = _normalize_text(text)
    for keyword in INVEST_ASSET_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            return True
    return bool(
        re.search(
            r"\b(mua|buy|ban|sell)\s+(co phieu|chung khoan|crypto|coin|etf|stock|shares?|portfolio|bond|trai phieu)\b",
            normalized,
        )
    )


def _contains_non_invest_planning_goal(text: str) -> bool:
    normalized = _normalize_text(text)
    for term in NON_INVEST_PLANNING_TERMS:
        if term in normalized:
            return True
    return False


def _normalize_text(text: str) -> str:
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def suitability_guard(
    *,
    auth_user_id: str,
    user_id: str,
    intent: str,
    requested_action: str,
    prompt: str,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    action = (requested_action or "").strip().lower()
    intent_norm = (intent or "").strip().lower()
    prompt_text = prompt or ""
    normalized_prompt = _normalize_text(prompt_text)

    prompt_invest_context = _contains_invest_asset_context(prompt_text)
    intent_invest_context = intent_norm == "invest" and prompt_invest_context
    has_invest_context = prompt_invest_context or intent_invest_context
    non_invest_planning_goal = _contains_non_invest_planning_goal(prompt_text)
    recommendation_hint = bool(
        re.search(
            r"\b(co nen|nen|should i|is it a good time to)\s*(mua|ban|buy|sell)\b",
            normalized_prompt,
        )
    )
    recommendation_hint = recommendation_hint and has_invest_context

    if action in {"buy", "sell", "recommend_buy", "recommend_sell", "recommend_trade"}:
        action_invest_like = has_invest_context
    else:
        action_invest_like = action in EXECUTION_ACTIONS and has_invest_context

    intent_invest_like = intent_norm == "invest" and has_invest_context
    invest_like = prompt_invest_context or action_invest_like or intent_invest_like or recommendation_hint
    if non_invest_planning_goal and not has_invest_context:
        invest_like = False

    is_execution = action in EXECUTION_ACTIONS
    is_recommendation = action in RECOMMENDATION_ACTIONS or recommendation_hint

    if invest_like and is_execution:
        allow = False
        decision = "deny_execution"
        reason_codes = ["execution_blocked", "education_only_policy"]
        refusal = "I cannot execute buy/sell actions. I can provide educational guidance only."
    elif invest_like and is_recommendation:
        allow = False
        decision = "deny_recommendation"
        reason_codes = ["investment_recommendation_blocked", "education_only_policy"]
        refusal = "I cannot provide buy/sell recommendations. I can help with cashflow, budgeting, and non-investment risk planning."
    elif invest_like:
        allow = True
        decision = "education_only"
        reason_codes = ["education_only_policy"]
        refusal = ""
    else:
        allow = True
        decision = "allow"
        reason_codes = ["non_investment_intent"]
        refusal = ""

    policy_decision = decision
    tool_input = {
        "user_id": user_id,
        "intent": intent,
        "requested_action": requested_action,
        "prompt": prompt,
    }
    payload = {
        "allow": allow,
        "decision": decision,
        "reason_codes": reason_codes,
        "required_disclaimer": DEFAULT_DISCLAIMER,
        "refusal_message": refusal,
        "education_only": invest_like,
    }

    result = build_output(
        tool_name=TOOL_NAME,
        tool_input=tool_input,
        payload=payload,
        trace_id=trace,
        started_at=started_at,
        sql_snapshot_ts=iso_utc(),
        policy_decision=policy_decision,
    )

    sql = client or get_supabase_client()
    write_decision_event(
        sql,
        user_id=user_id,
        trace_id=trace,
        decision_type=TOOL_NAME,
        decision=decision,
        payload={"params": tool_input, "reason_codes": reason_codes},
    )
    return result

