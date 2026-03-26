from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict

import graph as legacy_graph
from orchestrator.nodes.safety import safety_node as legacy_safety
from strands_orchestrator.config import enable_specialist_delegation

_DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."
_EXECUTION_ACTIONS = {"buy", "sell", "execute", "trade", "order", "transfer_funds"}
_RECOMMENDATION_ACTIONS = {"recommend_buy", "recommend_sell", "recommend_trade"}
_INVEST_ASSET_KEYWORDS = {
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
_NON_INVEST_PLANNING_TERMS = {
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


def _normalize_text(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(ch) != "Mn"
    )
    return stripped.lower()


def _contains_invest_asset_context(text: str) -> bool:
    normalized = _normalize_text(text)
    for keyword in _INVEST_ASSET_KEYWORDS:
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
    return any(term in normalized for term in _NON_INVEST_PLANNING_TERMS)


def _local_specialist_suitability_decision(state: Dict[str, Any], requested_action: str) -> Dict[str, Any]:
    prompt = str(state.get("prompt") or "")
    intent = str(state.get("intent") or "").strip().lower()
    action = str(requested_action or "").strip().lower()
    normalized_prompt = _normalize_text(prompt)

    prompt_invest_context = _contains_invest_asset_context(prompt)
    intent_invest_context = intent == "invest" and prompt_invest_context
    has_invest_context = prompt_invest_context or intent_invest_context
    non_invest_planning_goal = _contains_non_invest_planning_goal(prompt)
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
        action_invest_like = action in _EXECUTION_ACTIONS and has_invest_context

    intent_invest_like = intent == "invest" and has_invest_context
    invest_like = prompt_invest_context or action_invest_like or intent_invest_like or recommendation_hint
    if non_invest_planning_goal and not has_invest_context:
        invest_like = False

    is_execution = action in _EXECUTION_ACTIONS
    is_recommendation = action in _RECOMMENDATION_ACTIONS or recommendation_hint

    if invest_like and is_execution:
        return {
            "allow": False,
            "decision": "deny_execution",
            "reason_codes": ["execution_blocked", "education_only_policy"],
            "required_disclaimer": _DEFAULT_DISCLAIMER,
            "refusal_message": "I cannot execute buy/sell actions. I can provide educational guidance only.",
            "education_only": True,
            "trace_id": str(state.get("trace_id") or ""),
            "status": "ok",
            "source": "local_specialist_guard",
        }
    if invest_like and is_recommendation:
        return {
            "allow": False,
            "decision": "deny_recommendation",
            "reason_codes": ["investment_recommendation_blocked", "education_only_policy"],
            "required_disclaimer": _DEFAULT_DISCLAIMER,
            "refusal_message": (
                "I cannot provide buy/sell recommendations. "
                "I can help with cashflow, budgeting, and non-investment risk planning."
            ),
            "education_only": True,
            "trace_id": str(state.get("trace_id") or ""),
            "status": "ok",
            "source": "local_specialist_guard",
        }
    if invest_like:
        return {
            "allow": True,
            "decision": "education_only",
            "reason_codes": ["education_only_policy"],
            "required_disclaimer": _DEFAULT_DISCLAIMER,
            "refusal_message": "",
            "education_only": True,
            "trace_id": str(state.get("trace_id") or ""),
            "status": "ok",
            "source": "local_specialist_guard",
        }
    return {
        "allow": True,
        "decision": "allow",
        "reason_codes": ["non_investment_intent"],
        "required_disclaimer": _DEFAULT_DISCLAIMER,
        "refusal_message": "",
        "education_only": False,
        "trace_id": str(state.get("trace_id") or ""),
        "status": "ok",
        "source": "local_specialist_guard",
    }


def safety_node(state: Dict[str, Any]) -> Dict[str, Any]:
    if not enable_specialist_delegation():
        return legacy_safety(state)
    if state.get("response"):
        return state
    if bool(state.get("clarification", {}).get("pending")):
        return state

    requested_action = legacy_graph._requested_action(state.get("prompt", ""))  # type: ignore[attr-defined]
    # The specialist-first path no longer exposes a standalone suitability guard tool
    # through Gateway, so we apply the same deterministic education-only policy locally.
    decision = _local_specialist_suitability_decision(state, requested_action)
    legacy_graph._record_tool_output(state, "suitability_guard_v1", decision)  # type: ignore[attr-defined]
    state["education_only"] = bool(decision.get("education_only") or decision.get("decision") == "education_only")

    if not bool(decision.get("allow", True)):
        refusal = str(decision.get("refusal_message") or "Action is not allowed by policy.")
        disclaimer = str(decision.get("required_disclaimer") or legacy_graph.DEFAULT_DISCLAIMER)
        decision_reason_codes = [
            str(code).strip() for code in decision.get("reason_codes", []) if str(code).strip()
        ]
        fallback_used = (
            "safety_guard_degraded"
            if "safety_guard_degraded" in decision_reason_codes
            else "suitability_refusal"
        )
        legacy_graph._build_safe_refusal_response(  # type: ignore[attr-defined]
            state,
            refusal_message=refusal,
            disclaimer=disclaimer,
            fallback_used=fallback_used,
            extra_reason_codes=decision_reason_codes,
        )
    return state
