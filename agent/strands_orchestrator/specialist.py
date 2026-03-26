from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from jsonschema import Draft202012Validator, RefResolver

from observability.trace_context import utc_now_iso
from observability.tracing import new_call_id
from subagents.catalog import SpecialistDescriptor, load_catalog
from subagents.selection import SelectionContext, select_specialist
from tools import _call_gateway_tool

logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "subagents" / "schemas"
_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_SCHEMA_STORE: Optional[Dict[str, Dict[str, Any]]] = None
_INTENT_DOMAIN_MAP = {
    "summary": ["planning", "budgeting", "cashflow"],
    "risk": ["risk", "planning", "cashflow"],
    "planning": ["planning", "budgeting", "goals", "cashflow"],
    "scenario": ["planning", "cashflow", "goals"],
    "invest": ["investing", "portfolio", "equity"],
}
_SERVICE_ROADMAP_MARKERS = (
    "roadmap",
    "current phase",
    "phase sequence",
    "milestone",
    "milestones",
    "next best action",
    "recommended banking services",
    "service recommendations",
)


def _should_retry_with_gateway_alias(exc: Exception) -> bool:
    text = str(exc or "").strip().lower()
    if not text:
        return False
    return "tool " in text and "not found in agentcore gateway tools/list" in text


def _load_schema(name: str) -> Dict[str, Any]:
    if name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[name]
    path = SCHEMA_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    _SCHEMA_CACHE[name] = data
    return data


def _schema_store() -> Dict[str, Dict[str, Any]]:
    global _SCHEMA_STORE
    if _SCHEMA_STORE is not None:
        return _SCHEMA_STORE
    store: Dict[str, Dict[str, Any]] = {}
    for path in SCHEMA_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        schema_id = str(data.get("$id") or path.name)
        store[schema_id] = data
    _SCHEMA_STORE = store
    return store


def validate_specialist_output(schema_name: str, payload: Dict[str, Any]) -> None:
    schema = _load_schema(schema_name)
    resolver = RefResolver.from_schema(schema, store=_schema_store())
    Draft202012Validator(schema, resolver=resolver).validate(payload)


def _intent_confidence(state: Dict[str, Any]) -> Optional[float]:
    extraction = state.get("extraction")
    if not isinstance(extraction, dict):
        return None
    for key in ("confidence", "intent_confidence"):
        raw = extraction.get(key)
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _required_domains(intent: str) -> list[str]:
    return list(_INTENT_DOMAIN_MAP.get(intent, []))


def _extract_goal_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    extraction = state.get("extraction") if isinstance(state.get("extraction"), dict) else {}
    slots = extraction.get("slots") if isinstance(extraction.get("slots"), dict) else {}
    goal: Dict[str, Any] = {}
    raw_goal_type = slots.get("goal_type") or slots.get("goal_name")
    raw_target_amount = slots.get("target_amount") or slots.get("target_amount_vnd") or slots.get("goal_target_amount")
    raw_timeline = slots.get("target_timeline_months") or slots.get("horizon_months")
    raw_priority = slots.get("priority")
    if raw_goal_type:
        goal["goal_type"] = str(raw_goal_type).strip()
    try:
        if raw_target_amount is not None and str(raw_target_amount).strip():
            goal["target_amount"] = float(raw_target_amount)
    except (TypeError, ValueError):
        pass
    try:
        if raw_timeline is not None and str(raw_timeline).strip():
            goal["target_timeline_months"] = int(float(raw_timeline))
    except (TypeError, ValueError):
        pass
    if raw_priority:
        goal["priority"] = str(raw_priority).strip()
    return goal


def _normalized_prompt(state: Dict[str, Any]) -> str:
    prompt = str(state.get("prompt") or "").strip().lower()
    prompt = re.sub(r"\s+", " ", prompt)
    return prompt


def _looks_like_service_roadmap_prompt(state: Dict[str, Any]) -> bool:
    prompt = _normalized_prompt(state)
    if not prompt:
        return False
    if any(marker in prompt for marker in _SERVICE_ROADMAP_MARKERS):
        return True
    goal = _extract_goal_from_state(state)
    return bool(goal) and "roadmap" in prompt


def _planner_contract_from_state(state: Dict[str, Any]) -> Dict[str, Any] | None:
    agent_outputs = state.get("agent_outputs")
    if isinstance(agent_outputs, dict):
        planner = agent_outputs.get("planner")
        if isinstance(planner, dict) and isinstance(planner.get("standardized_contract"), dict):
            return planner.get("standardized_contract")
    session_memory = state.get("session_memory")
    if isinstance(session_memory, dict):
        contract = session_memory.get("last_planner_contract")
        if isinstance(contract, dict):
            return contract
    return None


def _planner_summary_from_state(state: Dict[str, Any]) -> str:
    agent_outputs = state.get("agent_outputs")
    if isinstance(agent_outputs, dict):
        planner = agent_outputs.get("planner")
        if isinstance(planner, dict):
            result = planner.get("result")
            if isinstance(result, dict):
                summary = str(result.get("summary") or "").strip()
                if summary:
                    return summary
    session_memory = state.get("session_memory")
    if isinstance(session_memory, dict):
        return str(session_memory.get("last_planner_summary") or "").strip()
    return ""


def _stock_text_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    rendered: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text = str(
                item.get("message")
                or item.get("title")
                or item.get("source_id")
                or item.get("ticker")
                or item.get("symbol")
                or ""
            ).strip()
        else:
            text = str(item or "").strip()
        if text and text not in rendered:
            rendered.append(text)
    return rendered


def _stock_context_from_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    result = envelope.get("result") if isinstance(envelope.get("result"), dict) else {}
    suitability = result.get("suitability") if isinstance(result.get("suitability"), dict) else {}
    recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
    alternatives = result.get("alternatives") if isinstance(result.get("alternatives"), list) else []
    warnings = envelope.get("warnings") if isinstance(envelope.get("warnings"), list) else result.get("warnings")
    warning_flags: list[str] = []
    for item in warnings if isinstance(warnings, list) else []:
        warning_flags.extend(_stock_text_list(item))

    market_notes = _stock_text_list(result.get("market_notes"))
    if not market_notes:
        for item in alternatives[:3]:
            if not isinstance(item, dict):
                continue
            rationale = str(item.get("rationale") or "").strip()
            if rationale and rationale not in market_notes:
                market_notes.append(rationale)

    cited_symbols: list[str] = []
    for collection in (recommendations, alternatives):
        for item in collection:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("ticker") or item.get("symbol") or "").strip()
            if symbol and symbol not in cited_symbols:
                cited_symbols.append(symbol)

    suitability_status = str(suitability.get("status") or (envelope.get("policy") or {}).get("suitability") or "").strip()
    market_tone = str(result.get("market_tone") or envelope.get("market_tone") or "").strip()
    if not market_tone:
        lowered_summary = str(result.get("summary") or envelope.get("summary") or "").strip().lower()
        if suitability_status.lower() in {"warn", "fail", "deny", "blocked"} or warning_flags:
            market_tone = "cautious"
        elif suitability_status.lower() == "pass":
            market_tone = "constructive"
        elif any(marker in lowered_summary for marker in ("risk", "volatile", "uncertain", "cautious")):
            market_tone = "cautious"

    payload: Dict[str, Any] = {}
    summary = str(result.get("summary") or envelope.get("summary") or "").strip()
    if summary:
        payload["summary"] = summary
    if suitability_status:
        payload["suitability_status"] = suitability_status
    if market_tone:
        payload["market_tone"] = market_tone
    if market_notes:
        payload["market_notes"] = market_notes
    if warning_flags:
        payload["warning_flags"] = warning_flags
    if cited_symbols:
        payload["cited_symbols"] = cited_symbols
    if payload:
        payload["source"] = str(envelope.get("tool_name") or envelope.get("agent_id") or "stock").strip()
    return payload


def _stock_context_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    request_envelope = state.get("request_envelope") if isinstance(state.get("request_envelope"), dict) else {}
    request_block = request_envelope.get("request") if isinstance(request_envelope.get("request"), dict) else {}
    user_context = request_block.get("user_context") if isinstance(request_block.get("user_context"), dict) else {}
    direct_stock_context = user_context.get("stock_context") if isinstance(user_context.get("stock_context"), dict) else {}
    if direct_stock_context:
        return dict(direct_stock_context)

    agent_outputs = state.get("agent_outputs") if isinstance(state.get("agent_outputs"), dict) else {}
    stock_output = agent_outputs.get("stock") if isinstance(agent_outputs.get("stock"), dict) else {}
    if stock_output:
        stock_context = _stock_context_from_envelope(stock_output)
        if stock_context:
            return stock_context

    session_memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
    last_stock_context = session_memory.get("last_stock_context") if isinstance(session_memory.get("last_stock_context"), dict) else {}
    return dict(last_stock_context) if last_stock_context else {}


def select_specialist_for_state(state: Dict[str, Any]) -> Tuple[Optional[SpecialistDescriptor], Dict[str, Any]]:
    intent = str(state.get("intent") or "").strip().lower()
    confidence = _intent_confidence(state)
    extraction = state.get("extraction") if isinstance(state.get("extraction"), dict) else {}
    target_agent_id = str(extraction.get("target_agent_id") or "").strip().lower()

    if not intent or intent == "out_of_scope":
        meta = {
            "intent": intent,
            "confidence": confidence,
            "required_domains": [],
            "selected_id": None,
            "selected_tool": None,
            "selected_version": None,
            "reason": "intent_not_delegated",
        }
        return None, meta
    
    required_domains = _required_domains(intent)

    if target_agent_id:
        specialist = get_specialist_by_id(target_agent_id)
        if specialist is not None:
            meta = {
                "intent": intent,
                "confidence": confidence,
                "required_domains": required_domains,
                "selected_id": specialist.id,
                "selected_tool": specialist.tool_name,
                "selected_version": specialist.tool_version,
                "selection_mode": "semantic_llm_direct",
                "confidence_relaxed": False,
            }
            return specialist, meta

    denied_agent_ids = []
    if intent in {"planning", "scenario"}:
        if _looks_like_service_roadmap_prompt(state):
            specialist = get_specialist_by_id("service")
            if specialist is not None:
                meta = {
                    "intent": intent,
                    "confidence": confidence,
                    "required_domains": required_domains,
                    "selected_id": specialist.id,
                    "selected_tool": specialist.tool_name,
                    "selected_version": specialist.tool_version,
                    "selection_mode": "service_roadmap_hint",
                    "confidence_relaxed": False,
                }
                return specialist, meta
        denied_agent_ids.append("service")

    context = SelectionContext(
        intent=intent or None,
        confidence=confidence,
        required_domains=required_domains,
        denied_agent_ids=denied_agent_ids,
    )
    catalog = load_catalog()
    specialist = select_specialist(catalog, context)
    confidence_relaxed = False
    if specialist is None and confidence is not None:
        specialist = select_specialist(
            catalog,
            SelectionContext(
                intent=intent or None,
                confidence=None,
                required_domains=required_domains,
                denied_agent_ids=denied_agent_ids,
            ),
        )
        confidence_relaxed = specialist is not None

    meta = {
        "intent": intent,
        "confidence": confidence,
        "required_domains": required_domains,
        "selected_id": specialist.id if specialist else None,
        "selected_tool": specialist.tool_name if specialist else None,
        "selected_version": specialist.tool_version if specialist else None,
        "selection_mode": "specialist_catalog_fallback" if confidence_relaxed else "specialist_catalog",
        "confidence_relaxed": confidence_relaxed,
    }
    return specialist, meta


def get_specialist_by_id(agent_id: str) -> Optional[SpecialistDescriptor]:
    catalog = load_catalog()
    for agent in catalog.agents:
        if agent.id == agent_id:
            return agent
    return None


def _fallback_envelope(descriptor: SpecialistDescriptor, state: Dict[str, Any]) -> Dict[str, Any]:
    request_id = str(state.get("request_id") or "").strip()
    session_id = str(state.get("session_id") or "").strip()
    trace_id = str(state.get("trace_id") or "").strip()
    request_timestamp = str(state.get("request_timestamp") or "").strip() or utc_now_iso()
    user_profile = state.get("user_profile") if isinstance(state.get("user_profile"), dict) else {}
    return {
        "schema_version": descriptor.tool_version,
        "actor": {
            "actor_id": str(state.get("user_id") or ""),
            "user_id": str(state.get("user_id") or ""),
            "tenant_id": "",
            "scopes": ["chat:invoke"],
        },
        "correlation": {
            "session_id": session_id,
            "request_id": request_id,
            "trace_id": trace_id,
            "parent_request_id": request_id,
            "request_timestamp": request_timestamp,
        },
        "request": {
            "prompt": str(state.get("prompt") or ""),
            "intent": str(state.get("intent") or ""),
            "policy_flags": {
                "education_only": bool(state.get("education_only", False)),
            },
            "user_context": {
                "user_id": str(state.get("user_id") or ""),
                "risk_appetite": str(user_profile.get("risk_appetite") or ""),
            },
            "goals": [],
            "session_summary": "",
        },
        "routing": {
            "specialist_id": descriptor.id,
            "tool_name": descriptor.tool_name,
        },
    }


def _base_payload(descriptor: SpecialistDescriptor, state: Dict[str, Any]) -> Dict[str, Any]:
    raw_envelope = state.get("request_envelope") if isinstance(state.get("request_envelope"), dict) else None
    envelope = deepcopy(raw_envelope) if raw_envelope else _fallback_envelope(descriptor, state)
    correlation = envelope.get("correlation")
    if not isinstance(correlation, dict):
        correlation = {}
        envelope["correlation"] = correlation
    if not str(correlation.get("request_timestamp") or "").strip():
        correlation["request_timestamp"] = str(state.get("request_timestamp") or "").strip() or utc_now_iso()

    request_block = envelope.get("request")
    if not isinstance(request_block, dict):
        request_block = {}
        envelope["request"] = request_block
    request_block["prompt"] = str(request_block.get("prompt") or state.get("prompt") or "")
    request_block["intent"] = str(request_block.get("intent") or state.get("intent") or "")
    request_block["session_summary"] = str(request_block.get("session_summary") or "")

    policy_flags = request_block.get("policy_flags")
    if not isinstance(policy_flags, dict):
        policy_flags = {}
    policy_flags["education_only"] = bool(
        policy_flags.get("education_only")
        or state.get("education_only", False)
    )
    request_block["policy_flags"] = policy_flags

    user_context = request_block.get("user_context")
    if not isinstance(user_context, dict):
        user_context = {}
    user_context.setdefault("user_id", str(state.get("user_id") or ""))
    user_context.setdefault("intent", str(state.get("intent") or ""))
    user_context.setdefault(
        "risk_appetite",
        str((state.get("user_profile") or {}).get("risk_appetite") or ""),
    )
    request_block["user_context"] = user_context
    request_block.setdefault("goals", [])

    envelope["routing"] = {
        "specialist_id": descriptor.id,
        "tool_name": descriptor.tool_name,
    }
    envelope["schema_version"] = descriptor.tool_version
    return envelope


def _risk_profile_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    profile = state.get("user_profile") if isinstance(state.get("user_profile"), dict) else {}
    risk_band = str(profile.get("risk_appetite") or "").strip().lower()
    if risk_band not in {"conservative", "moderate", "aggressive"}:
        risk_band = "unknown"
    return {"risk_band": risk_band, "education_only": bool(state.get("education_only", False))}


def build_specialist_payload(descriptor: SpecialistDescriptor, state: Dict[str, Any]) -> Dict[str, Any]:
    base = _base_payload(descriptor, state)
    if descriptor.id == "planner":
        return base
    if descriptor.id == "service":
        request_block = base.get("request") if isinstance(base.get("request"), dict) else {}
        user_context = request_block.get("user_context") if isinstance(request_block.get("user_context"), dict) else {}
        for key in (
            "stock_context",
            "stock_envelope",
            "stock_advisory",
            "last_stock_advisory",
            "stock_specialist_result",
        ):
            user_context.pop(key, None)
        user_context.setdefault(
            "risk_preference",
            str((state.get("user_profile") or {}).get("risk_appetite") or ""),
        )
        planner_contract = _planner_contract_from_state(state)
        if planner_contract and not isinstance(user_context.get("planner_standardized_contract"), dict):
            user_context["planner_standardized_contract"] = planner_contract
        planner_summary = _planner_summary_from_state(state)
        if planner_summary and not str(user_context.get("planner_summary") or "").strip():
            user_context["planner_summary"] = planner_summary
        request_block["user_context"] = user_context

        goals = request_block.get("goals") if isinstance(request_block.get("goals"), list) else []
        if not goals:
            inferred_goal = _extract_goal_from_state(state)
            if inferred_goal:
                request_block["goals"] = [inferred_goal]
        base["request"] = request_block
        return base
    if descriptor.id == "stock":
        planner_summary = _planner_summary_from_state(state)
        request_block = base.get("request") if isinstance(base.get("request"), dict) else {}
        user_context = request_block.get("user_context") if isinstance(request_block.get("user_context"), dict) else {}
        user_context.update(
            {
                "risk_profile": _risk_profile_from_state(state),
                "liquidity_constraints": {},
                "planner_summary": planner_summary,
                "portfolio": [],
            }
        )
        request_block["user_context"] = user_context
        base["request"] = request_block
        return base
    return base


def call_specialist_tool(
    descriptor: SpecialistDescriptor,
    payload: Dict[str, Any],
    user_token: str,
    *,
    trace_id: str,
    trace_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    def _strip_transport_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = deepcopy(result)
        sanitized.pop("call_id", None)
        sanitized.pop("idempotency_key", None)
        return sanitized

    call_id = new_call_id("spec")
    try:
        result = _call_gateway_tool(
            descriptor.tool_name,
            payload,
            user_token,
            call_id=call_id,
            trace_id=trace_id,
            trace_context=trace_context,
        )
        return _strip_transport_metadata(result)
    except Exception as exc:
        if (
            descriptor.gateway_tool_name
            and descriptor.gateway_tool_name != descriptor.tool_name
            and _should_retry_with_gateway_alias(exc)
        ):
            logger.warning(
                "Specialist tool fallback to gateway_tool_name: base=%s gateway=%s error=%s",
                descriptor.tool_name,
                descriptor.gateway_tool_name,
                exc,
            )
            result = _call_gateway_tool(
                descriptor.gateway_tool_name,
                payload,
                user_token,
                call_id=call_id,
                trace_id=trace_id,
                trace_context=trace_context,
            )
            return _strip_transport_metadata(result)
        raise


__all__ = [
    "build_specialist_payload",
    "call_specialist_tool",
    "get_specialist_by_id",
    "select_specialist_for_state",
    "validate_specialist_output",
]
