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
INVEST_KEYWORDS = {
    "invest",
    "stock",
    "etf",
    "crypto",
    "buy",
    "sell",
    "trade",
    "portfolio",
    "co phieu",
    "dau tu",
}


def _contains_invest_intent(text: str) -> bool:
    normalized = _normalize_text(text)
    for keyword in INVEST_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
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

    prompt_invest_like = _contains_invest_intent(prompt_text)
    action_invest_like = action in EXECUTION_ACTIONS or action in RECOMMENDATION_ACTIONS
    intent_invest_like = _contains_invest_intent(intent_norm)
    recommendation_hint = bool(
        re.search(
            r"\b(co nen|nen|should i|is it a good time to)\s*(mua|ban|buy|sell)\b",
            _normalize_text(prompt_text),
        )
    )
    invest_like = prompt_invest_like or action_invest_like or (intent_invest_like and recommendation_hint)
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

