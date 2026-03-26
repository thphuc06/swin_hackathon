from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from planner_agent.finance.supabase_rest import SupabaseRestError, get_supabase_client

from service_agent.contracts import (
    CandidateServiceMap,
    FutureServicePreview,
    MilestoneServiceExplanation,
    NextActionRecommendedService,
    NextActionServiceExplanation,
    PhaseServiceExplanation,
    RecommendedService,
    RoadmapContract,
    ServiceReference,
)
from service_agent.model_adapter import invoke_json_prompt, resolve_model_id
from service_agent.roadmap_context import RoadmapContext

logger = logging.getLogger(__name__)

_SERVICE_TABLE = "banking_services"
_SELECTION_TOOL_NAME = "submit_banking_service_selection"
_PHASE_STATUSES_WITH_RECOMMENDATIONS = {"current", "upcoming"}
_MILESTONE_TYPE_BY_PHASE = {
    "protect_liquidity": "anomaly_contained",
    "stabilize": "cashflow_stabilized",
    "accumulate": "contribution_rhythm_active",
    "readiness_review": "pace_revalidated",
    "maturity_transition": "execution_readiness_confirmed",
}
_GOAL_TYPE_ALIASES = {
    "buy_home": "home_purchase",
}


@dataclass(frozen=True)
class BankingServiceRow:
    service_id: str
    display_name_vi: str
    display_name_en: str
    category: str
    description: str
    user_benefit_vi: str
    when_to_recommend_vi: str
    when_not_to_recommend_vi: str
    supported_phases: List[str]
    supported_milestones: List[str]
    supported_goal_types: List[str]
    liquidity_profile: str
    risk_level: str
    requires_positive_cashflow: bool
    requires_anomaly_resolved: bool
    requires_buffer_present: bool
    is_active: bool
    sort_order: int


def _feature_enabled() -> bool:
    return str(os.getenv("SERVICE_AGENT_BANKING_SERVICE_RECOMMENDATIONS_ENABLED") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [_compact_text(item) for item in value if _compact_text(item)]
    if isinstance(value, tuple):
        return [_compact_text(item) for item in value if _compact_text(item)]
    text = _compact_text(value)
    return [text] if text else []


def _canonical_goal_type(value: Any) -> str:
    goal_type = _compact_text(value).lower()
    return _GOAL_TYPE_ALIASES.get(goal_type, goal_type)


def _row_from_payload(payload: Mapping[str, Any]) -> BankingServiceRow | None:
    service_id = _compact_text(payload.get("service_id"))
    display_name_vi = _compact_text(payload.get("display_name_vi"))
    category = _compact_text(payload.get("category"))
    if not service_id or not display_name_vi or not category:
        return None
    return BankingServiceRow(
        service_id=service_id,
        display_name_vi=display_name_vi,
        display_name_en=_compact_text(payload.get("display_name_en")),
        category=category,
        description=_compact_text(payload.get("description")),
        user_benefit_vi=_compact_text(payload.get("user_benefit_vi")),
        when_to_recommend_vi=_compact_text(payload.get("when_to_recommend_vi")),
        when_not_to_recommend_vi=_compact_text(payload.get("when_not_to_recommend_vi")),
        supported_phases=_text_list(payload.get("supported_phases")),
        supported_milestones=_text_list(payload.get("supported_milestones")),
        supported_goal_types=_text_list(payload.get("supported_goal_types")),
        liquidity_profile=_compact_text(payload.get("liquidity_profile")).lower(),
        risk_level=_compact_text(payload.get("risk_level")).lower(),
        requires_positive_cashflow=_safe_bool(payload.get("requires_positive_cashflow")),
        requires_anomaly_resolved=_safe_bool(payload.get("requires_anomaly_resolved")),
        requires_buffer_present=_safe_bool(payload.get("requires_buffer_present")),
        is_active=_safe_bool(payload.get("is_active", True)),
        sort_order=_safe_int(payload.get("sort_order"), 0),
    )


def _planner_signals(context: RoadmapContext) -> Dict[str, Any]:
    planner = context.planner_state
    amount_monthly = planner.savings_capacity.amount_monthly
    return {
        "goal_type": _canonical_goal_type(context.goal.goal_type),
        "goal_type_original": _compact_text(context.goal.goal_type),
        "cashflow_status": _compact_text(planner.cashflow_status).lower(),
        "savings_capacity_amount_monthly": amount_monthly,
        "liquidity_pressure": _compact_text(planner.liquidity_pressure).lower(),
        "anomaly_active": _compact_text(planner.anomaly_state).lower() == "active",
        "buffer_present": _compact_text(planner.buffer_status).lower() == "present",
        "risk_band": _compact_text(planner.risk_band).lower(),
        "readiness_label": _compact_text(planner.readiness_label).lower(),
    }


def _phase_goal_match(service: BankingServiceRow, goal_type: str) -> bool:
    if not service.supported_goal_types:
        return True
    canonical_goal_type = _canonical_goal_type(goal_type)
    supported_goal_types = {_canonical_goal_type(item) for item in service.supported_goal_types if _compact_text(item)}
    return canonical_goal_type in supported_goal_types


def _phase_match(service: BankingServiceRow, phase_type: str) -> bool:
    return not service.supported_phases or phase_type in service.supported_phases


def _milestone_match(service: BankingServiceRow, milestone_type: str) -> bool:
    return not service.supported_milestones or milestone_type in service.supported_milestones


def _gating_allows(service: BankingServiceRow, context: RoadmapContext) -> tuple[bool, str]:
    planner = context.planner_state
    amount_monthly = planner.savings_capacity.amount_monthly or 0.0
    anomaly_active = _compact_text(planner.anomaly_state).lower() == "active"
    buffer_present = _compact_text(planner.buffer_status).lower() == "present"
    if service.requires_positive_cashflow and amount_monthly <= 0:
        return False, "requires_positive_cashflow"
    if service.requires_anomaly_resolved and anomaly_active:
        return False, "requires_anomaly_resolved"
    if service.requires_buffer_present and not buffer_present:
        return False, "requires_buffer_present"
    return True, ""


def _planner_state_fit_score(service: BankingServiceRow, context: RoadmapContext, *, phase_type: str) -> float:
    planner = context.planner_state
    amount_monthly = planner.savings_capacity.amount_monthly or 0.0
    anomaly_active = _compact_text(planner.anomaly_state).lower() == "active"
    liquidity_pressure = _compact_text(planner.liquidity_pressure).lower()
    score = 0.5
    if anomaly_active and service.category in {"alerts", "liquidity_protection", "account_management"}:
        score += 0.25
    if amount_monthly <= 0 and service.category in {"budgeting", "liquidity_protection", "alerts"}:
        score += 0.2
    if amount_monthly > 0 and phase_type in {"accumulate", "readiness_review"} and service.category in {"goal_funding", "savings"}:
        score += 0.2
    if liquidity_pressure in {"high", "critical"} and service.liquidity_profile in {"high", "medium", "variable"}:
        score += 0.15
    if liquidity_pressure in {"high", "critical"} and service.liquidity_profile == "locked":
        score -= 0.25
    return max(0.0, min(1.0, score))


def _liquidity_safety_score(service: BankingServiceRow, context: RoadmapContext, *, phase_type: str) -> float:
    liquidity_pressure = _compact_text(context.planner_state.liquidity_pressure).lower()
    if phase_type in {"protect_liquidity", "stabilize"} and service.liquidity_profile == "locked":
        return 0.1
    if liquidity_pressure in {"high", "critical"} and service.liquidity_profile == "locked":
        return 0.1
    if service.liquidity_profile in {"high", "medium", "variable", ""}:
        return 0.9
    if service.liquidity_profile == "low":
        return 0.5
    return 0.3


def _execution_readiness_score(service: BankingServiceRow, context: RoadmapContext, *, phase_status: str) -> float:
    planner = context.planner_state
    amount_monthly = planner.savings_capacity.amount_monthly or 0.0
    anomaly_active = _compact_text(planner.anomaly_state).lower() == "active"
    if phase_status == "completed":
        return 0.0
    score = 0.65
    if amount_monthly > 0:
        score += 0.15
    if anomaly_active and service.requires_anomaly_resolved:
        score -= 0.4
    if phase_status == "current":
        score += 0.1
    return max(0.0, min(1.0, score))


def _complexity_penalty(service: BankingServiceRow) -> float:
    penalty = 0.0
    if service.liquidity_profile == "locked":
        penalty += 0.2
    if service.risk_level == "high":
        penalty += 0.25
    elif service.risk_level == "moderate":
        penalty += 0.1
    return min(0.5, penalty)


def _fetch_catalog() -> tuple[List[BankingServiceRow], List[str], str]:
    if not _feature_enabled():
        return [], ["service recommendation feature flag disabled"], "disabled"
    try:
        client = get_supabase_client()
    except Exception as exc:  # pragma: no cover - defensive
        return [], [f"supabase client resolution failed: {exc}"], "supabase_client_error"
    if not client.configured:
        return [], ["supabase client not configured"], "supabase_not_configured"
    try:
        if hasattr(client, "table_exists") and not client.table_exists(_SERVICE_TABLE):
            return [], [f"{_SERVICE_TABLE} table not available"], "table_missing"
    except Exception as exc:
        return [], [f"unable to inspect {_SERVICE_TABLE}: {exc}"], "table_introspection_failed"
    try:
        rows = client.fetch_rows(
            _SERVICE_TABLE,
            select="service_id,display_name_vi,display_name_en,category,description,user_benefit_vi,when_to_recommend_vi,when_not_to_recommend_vi,supported_phases,supported_milestones,supported_goal_types,liquidity_profile,risk_level,requires_positive_cashflow,requires_anomaly_resolved,requires_buffer_present,is_active,sort_order",
            filters={"is_active": "eq.true"},
            order="sort_order.asc",
        )
        catalog = [row for row in (_row_from_payload(item) for item in rows if isinstance(item, Mapping)) if row is not None]
        if not catalog:
            return [], ["no active banking services returned from supabase"], "catalog_empty"
        return catalog, [], "ok"
    except SupabaseRestError as exc:
        return [], [str(exc)], "catalog_fetch_failed"


def _service_feature_payload(
    service: BankingServiceRow,
    context: RoadmapContext,
    *,
    phase_type: str,
    phase_status: str,
    milestone_type: str = "",
) -> Dict[str, Any]:
    goal_type = _canonical_goal_type(context.goal.goal_type)
    phase_fit = 1.0 if _phase_match(service, phase_type) else 0.0
    milestone_fit = 1.0 if (not milestone_type or _milestone_match(service, milestone_type)) else 0.0
    goal_fit = 1.0 if _phase_goal_match(service, goal_type) else 0.0
    planner_fit = _planner_state_fit_score(service, context, phase_type=phase_type)
    liquidity_safety = _liquidity_safety_score(service, context, phase_type=phase_type)
    execution_readiness = _execution_readiness_score(service, context, phase_status=phase_status)
    complexity_penalty = _complexity_penalty(service)
    return {
        "service_id": service.service_id,
        "display_name_vi": service.display_name_vi,
        "category": service.category,
        "description": service.description,
        "user_benefit_vi": service.user_benefit_vi,
        "when_to_recommend_vi": service.when_to_recommend_vi,
        "when_not_to_recommend_vi": service.when_not_to_recommend_vi,
        "liquidity_profile": service.liquidity_profile,
        "risk_level": service.risk_level,
        "scores": {
            "phase_fit_score": phase_fit,
            "milestone_fit_score": milestone_fit,
            "goal_fit_score": goal_fit,
            "planner_state_fit_score": round(planner_fit, 2),
            "liquidity_safety_score": round(liquidity_safety, 2),
            "execution_readiness_score": round(execution_readiness, 2),
            "complexity_penalty": round(complexity_penalty, 2),
        },
    }


def _eligible_phase_services(
    context: RoadmapContext,
    phase,
    catalog: List[BankingServiceRow],
    notes: List[str],
) -> List[BankingServiceRow]:
    goal_type = _canonical_goal_type(context.goal.goal_type)
    if phase.status not in _PHASE_STATUSES_WITH_RECOMMENDATIONS:
        notes.append(f"phase {phase.phase_type} skipped because status={phase.status}")
        return []
    eligible: List[BankingServiceRow] = []
    for service in catalog:
        if not _phase_match(service, phase.phase_type):
            continue
        if not _phase_goal_match(service, goal_type):
            continue
        allowed, reason = _gating_allows(service, context)
        if not allowed:
            notes.append(f"phase {phase.phase_type} excluded {service.service_id}: {reason}")
            continue
        if phase.phase_type in {"protect_liquidity", "stabilize"} and service.liquidity_profile == "locked":
            notes.append(f"phase {phase.phase_type} excluded {service.service_id}: locked_liquidity_in_early_phase")
            continue
        eligible.append(service)
    return eligible


def _eligible_milestone_services(
    context: RoadmapContext,
    milestone,
    catalog: List[BankingServiceRow],
    notes: List[str],
) -> tuple[str, List[BankingServiceRow]]:
    goal_type = _canonical_goal_type(context.goal.goal_type)
    milestone_type = _MILESTONE_TYPE_BY_PHASE.get(milestone.phase_type, milestone.phase_type)
    if milestone.status not in _PHASE_STATUSES_WITH_RECOMMENDATIONS:
        notes.append(f"milestone {milestone.milestone_id} skipped because status={milestone.status}")
        return milestone_type, []
    eligible: List[BankingServiceRow] = []
    for service in catalog:
        if not _phase_match(service, milestone.phase_type):
            continue
        if not _milestone_match(service, milestone_type):
            continue
        if not _phase_goal_match(service, goal_type):
            continue
        allowed, reason = _gating_allows(service, context)
        if not allowed:
            notes.append(f"milestone {milestone.milestone_id} excluded {service.service_id}: {reason}")
            continue
        eligible.append(service)
    return milestone_type, eligible


def _selection_system_prompt() -> str:
    return (
        "You are Layer 2B of a financial roadmap service agent.\n"
        "Your job is to select banking services only from the provided eligible services.\n"
        "You must not invent services, ids, categories, or benefits.\n"
        "For each phase and milestone, choose at most one primary service and at most two supporting services.\n"
        "Prefer services that strongly fit the current phase, current milestone, current planner_state, and the next roadmap transition.\n"
        "If stock_context is present, treat it as a secondary caution or timing signal only.\n"
        "Avoid later-stage or locked-liquidity services when the user is still in protection or stabilization.\n"
        "If no service is appropriate for a context, return an empty selected_services list.\n"
        "All generated explanations (e.g., why_recommended, why_this_service_now, how_it_supports_transition) must be written in highly professional, polished business English.\n"
        "Return JSON only via the provided tool.\n"
    )


def _selection_tool_schema() -> Dict[str, Any]:
    selected_service_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["service_id", "role", "why_recommended", "expected_benefit"],
        "properties": {
            "service_id": {"type": "string"},
            "role": {"type": "string", "enum": ["primary", "supporting"]},
            "why_recommended": {"type": "string"},
            "expected_benefit": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "phase_recommendations",
            "milestone_recommendations",
            "next_action_service",
            "selection_warnings",
        ],
        "properties": {
            "phase_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["phase_type", "selected_services", "explanation"],
                    "properties": {
                        "phase_type": {"type": "string"},
                        "selected_services": {"type": "array", "maxItems": 3, "items": selected_service_schema},
                        "explanation": {"type": "string"},
                    },
                },
            },
            "milestone_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["milestone_id", "selected_services", "explanation"],
                    "properties": {
                        "milestone_id": {"type": "string"},
                        "selected_services": {"type": "array", "maxItems": 3, "items": selected_service_schema},
                        "explanation": {"type": "string"},
                    },
                },
            },
            "next_action_service": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "service_id": {"type": "string"},
                    "why_this_service_now": {"type": "string"},
                    "how_it_supports_transition": {"type": "string"},
                },
            },
            "selection_warnings": {"type": "array", "items": {"type": "string"}},
        },
    }


def _selection_prompt(context_payload: Dict[str, Any]) -> str:
    return "Select the most suitable banking services for this roadmap.\nContext:\n" + json.dumps(
        context_payload,
        ensure_ascii=True,
        sort_keys=True,
    )


def _blocked_reason_for_phase(service: BankingServiceRow, context: RoadmapContext, *, phase_type: str) -> str:
    allowed, reason = _gating_allows(service, context)
    if not allowed:
        return reason
    if phase_type in {"protect_liquidity", "stabilize"} and service.liquidity_profile == "locked":
        return "locked_liquidity_in_early_phase"
    return ""


def _preview_reason_details(reason: str, service: BankingServiceRow, *, phase_type: str) -> tuple[str, str]:
    if reason == "requires_positive_cashflow":
        return (
            "This service becomes more useful once monthly contribution capacity is back above zero.",
            "Return monthly savings capacity to a positive range before activating it.",
        )
    if reason == "requires_anomaly_resolved":
        return (
            "This service fits better after the current anomaly or leakage risk has been resolved.",
            "Contain the anomaly first so later-stage funding tools sit on a cleaner baseline.",
        )
    if reason == "requires_buffer_present":
        return (
            "This service assumes the plan already has a usable cash buffer in place.",
            "Build or confirm the buffer before moving this service into active use.",
        )
    if reason == "locked_liquidity_in_early_phase":
        return (
            "This service is better later because it reduces flexibility while the plan is still protecting liquidity.",
            "Move beyond protection and confirm the cash baseline before using a more locked product.",
        )
    return (
        "This service is more suitable after the current phase unlocks a steadier baseline.",
        f"Complete the key unlock conditions for {phase_type} before bringing this service forward.",
    )


def _preview_priority(
    service: BankingServiceRow,
    context: RoadmapContext,
    *,
    phase_type: str,
    phase_status: str,
    milestone_type: str = "",
) -> float:
    payload = _service_feature_payload(
        service,
        context,
        phase_type=phase_type,
        phase_status=phase_status,
        milestone_type=milestone_type,
    )
    scores = payload["scores"]
    return (
        scores["phase_fit_score"] * 0.3
        + scores["milestone_fit_score"] * 0.15
        + scores["goal_fit_score"] * 0.15
        + scores["planner_state_fit_score"] * 0.15
        + scores["liquidity_safety_score"] * 0.1
        + scores["execution_readiness_score"] * 0.15
        - scores["complexity_penalty"] * 0.1
    )


def _build_preview_items(
    blocked_rows: List[tuple[BankingServiceRow, str]],
    context: RoadmapContext,
    *,
    phase_type: str,
    phase_status: str,
    selected_ids: set[str],
    milestone_type: str = "",
) -> List[FutureServicePreview]:
    ranked = sorted(
        blocked_rows,
        key=lambda item: (
            -round(
                _preview_priority(
                    item[0],
                    context,
                    phase_type=phase_type,
                    phase_status=phase_status,
                    milestone_type=milestone_type,
                ),
                6,
            ),
            item[0].sort_order,
            item[0].service_id,
        ),
    )
    previews: List[FutureServicePreview] = []
    seen: set[str] = set(selected_ids)
    for service, reason in ranked:
        if service.service_id in seen:
            continue
        why_not_now, unlock_hint = _preview_reason_details(reason, service, phase_type=phase_type)
        previews.append(
            FutureServicePreview(
                service_id=service.service_id,
                display_name_vi=service.display_name_vi,
                category=service.category,
                why_not_now=why_not_now,
                unlock_hint=unlock_hint,
                expected_benefit=service.user_benefit_vi or service.description,
            )
        )
        seen.add(service.service_id)
        if len(previews) >= 3:
            break
    return previews


def _sanitize_selected_services(
    raw_items: Any,
    allowed_rows: Mapping[str, BankingServiceRow],
) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    seen: set[str] = set()
    primary_seen = False
    supporting_count = 0
    if not isinstance(raw_items, list):
        return selected
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        service_id = _compact_text(item.get("service_id"))
        role = _compact_text(item.get("role")).lower() or "supporting"
        if service_id not in allowed_rows or service_id in seen:
            continue
        if role == "primary":
            if primary_seen:
                continue
            primary_seen = True
        else:
            role = "supporting"
            if supporting_count >= 2:
                continue
            supporting_count += 1
        seen.add(service_id)
        selected.append(
            {
                "service_id": service_id,
                "role": role,
                "why_recommended": _compact_text(item.get("why_recommended")),
                "expected_benefit": _compact_text(item.get("expected_benefit")),
            }
        )
    if selected and not any(item["role"] == "primary" for item in selected):
        selected[0]["role"] = "primary"
    return selected


def _run_selection_layer(context_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    model_id = resolve_model_id("SERVICE_AGENT_MODEL_ID", "BEDROCK_MODEL_ID")
    raw_payload, invoke_meta = invoke_json_prompt(
        _selection_prompt(context_payload),
        model_id=model_id,
        system_prompt=_selection_system_prompt(),
        tool_name=_SELECTION_TOOL_NAME,
        tool_schema=_selection_tool_schema(),
        tool_description="Select banking services from the provided eligible services for each roadmap context.",
        max_tokens=3200,
        temperature=0.1,
    )
    return raw_payload, invoke_meta


def attach_banking_service_recommendations(
    context: RoadmapContext,
    contract: RoadmapContract,
) -> tuple[RoadmapContract, Dict[str, Any]]:
    diagnostics: Dict[str, Any] = {
        "service_recommendation_status": "not_attempted",
        "service_candidate_counts_by_phase": {},
        "service_candidate_counts_by_milestone": {},
        "service_preview_counts_by_phase": {},
        "service_preview_counts_by_milestone": {},
        "service_filtering_notes": [],
        "service_selection_warnings": [],
    }
    contract_copy = contract.model_copy(deep=True)
    catalog, catalog_notes, fetch_status = _fetch_catalog()
    diagnostics["service_filtering_notes"].extend(catalog_notes)
    if fetch_status != "ok":
        diagnostics["service_recommendation_status"] = fetch_status
        return contract_copy, diagnostics

    phase_allowed_rows: Dict[str, Dict[str, BankingServiceRow]] = {}
    milestone_allowed_rows: Dict[str, Dict[str, BankingServiceRow]] = {}
    phase_blocked_rows: Dict[str, List[tuple[BankingServiceRow, str]]] = {}
    milestone_blocked_rows: Dict[str, List[tuple[BankingServiceRow, str]]] = {}
    phase_payloads: List[Dict[str, Any]] = []
    milestone_payloads: List[Dict[str, Any]] = []

    for phase in contract_copy.phases:
        eligible = _eligible_phase_services(context, phase, catalog, diagnostics["service_filtering_notes"])
        blocked: List[tuple[BankingServiceRow, str]] = []
        if phase.status in _PHASE_STATUSES_WITH_RECOMMENDATIONS:
            goal_type = _canonical_goal_type(context.goal.goal_type)
            for service in catalog:
                if not _phase_match(service, phase.phase_type):
                    continue
                if not _phase_goal_match(service, goal_type):
                    continue
                reason = _blocked_reason_for_phase(service, context, phase_type=phase.phase_type)
                if reason:
                    blocked.append((service, reason))
        phase_allowed_rows[phase.phase_type] = {item.service_id: item for item in eligible}
        phase_blocked_rows[phase.phase_type] = blocked
        diagnostics["service_candidate_counts_by_phase"][phase.phase_type] = len(eligible)
        diagnostics["service_preview_counts_by_phase"][phase.phase_type] = len(blocked)
        phase_payloads.append(
            {
                "phase_type": phase.phase_type,
                "phase_title": phase.title,
                "phase_status": phase.status,
                "objective": phase.objective,
                "next_transition": phase.exit_conditions[:2],
                "eligible_services": [
                    _service_feature_payload(item, context, phase_type=phase.phase_type, phase_status=phase.status)
                    for item in eligible
                ],
            }
        )

    for milestone in contract_copy.milestones:
        milestone_type, eligible = _eligible_milestone_services(context, milestone, catalog, diagnostics["service_filtering_notes"])
        blocked: List[tuple[BankingServiceRow, str]] = []
        if milestone.status in _PHASE_STATUSES_WITH_RECOMMENDATIONS:
            goal_type = _canonical_goal_type(context.goal.goal_type)
            for service in catalog:
                if not _phase_match(service, milestone.phase_type):
                    continue
                if not _milestone_match(service, milestone_type):
                    continue
                if not _phase_goal_match(service, goal_type):
                    continue
                reason = _blocked_reason_for_phase(service, context, phase_type=milestone.phase_type)
                if reason:
                    blocked.append((service, reason))
        milestone_allowed_rows[milestone.milestone_id] = {item.service_id: item for item in eligible}
        milestone_blocked_rows[milestone.milestone_id] = blocked
        diagnostics["service_candidate_counts_by_milestone"][milestone.milestone_id] = len(eligible)
        diagnostics["service_preview_counts_by_milestone"][milestone.milestone_id] = len(blocked)
        milestone_payloads.append(
            {
                "milestone_id": milestone.milestone_id,
                "milestone_type": milestone_type,
                "phase_type": milestone.phase_type,
                "status": milestone.status,
                "title": milestone.title,
                "unlock_rule": milestone.unlock_rule,
                "eligible_services": [
                    _service_feature_payload(
                        item,
                        context,
                        phase_type=milestone.phase_type,
                        phase_status=milestone.status,
                        milestone_type=milestone_type,
                    )
                    for item in eligible
                ],
            }
        )

    if not any(phase_allowed_rows.values()) and not any(milestone_allowed_rows.values()):
        for phase in contract_copy.phases:
            phase.recommended_now = []
            phase.recommended_services = []
            phase.future_services_preview = _build_preview_items(
                phase_blocked_rows.get(phase.phase_type, []),
                context,
                phase_type=phase.phase_type,
                phase_status=phase.status,
                selected_ids=set(),
            )
        for milestone in contract_copy.milestones:
            milestone_type = _MILESTONE_TYPE_BY_PHASE.get(milestone.phase_type, milestone.phase_type)
            milestone.recommended_now = []
            milestone.recommended_services = []
            milestone.future_services_preview = _build_preview_items(
                milestone_blocked_rows.get(milestone.milestone_id, []),
                context,
                phase_type=milestone.phase_type,
                phase_status=milestone.status,
                milestone_type=milestone_type,
                selected_ids=set(),
            )
        contract_copy.service_recommendations = []
        has_preview = any(phase.future_services_preview for phase in contract_copy.phases) or any(
            milestone.future_services_preview for milestone in contract_copy.milestones
        )
        diagnostics["service_recommendation_status"] = "preview_only" if has_preview else "no_eligible_services"
        if has_preview:
            diagnostics["service_selection_warnings"].append(
                "No banking services are eligible right now, so the roadmap is showing future previews only."
            )
        return contract_copy, diagnostics

    current_phase = next((phase for phase in contract_copy.phases if phase.phase_type == contract_copy.current_phase), None)
    current_phase_allowed = phase_allowed_rows.get(contract_copy.current_phase, {})
    goal_payload = contract_copy.goal.model_dump(exclude_none=True)
    goal_payload["goal_type_original"] = goal_payload.get("goal_type")
    goal_payload["goal_type"] = _canonical_goal_type(goal_payload.get("goal_type"))
    selection_payload = {
        "goal": goal_payload,
        "planner_state": _planner_signals(context),
        "stock_context": context.user_context.stock_context.model_dump(exclude_none=True) if context.user_context.stock_context else {},
        "journey_pattern": contract_copy.journey_pattern,
        "current_phase": contract_copy.current_phase,
        "phases": phase_payloads,
        "milestones": milestone_payloads,
        "next_action": {
            "title": contract_copy.next_best_action.title if contract_copy.next_best_action else "",
            "why": contract_copy.next_best_action.why if contract_copy.next_best_action else "",
            "current_phase": contract_copy.current_phase,
            "eligible_services": [
                _service_feature_payload(
                    item,
                    context,
                    phase_type=contract_copy.current_phase,
                    phase_status=current_phase.status if current_phase else "current",
                )
                for item in current_phase_allowed.values()
            ],
        },
    }

    try:
        raw_selection, selection_meta = _run_selection_layer(selection_payload)
        diagnostics["service_layer2"] = selection_meta
    except Exception as exc:  # pragma: no cover - runtime path
        logger.warning("service_banking_service_selection_failed error=%s", exc)
        diagnostics["service_recommendation_status"] = "selection_model_error"
        diagnostics["service_selection_warnings"].append(str(exc))
        return contract_copy, diagnostics

    phase_explanations: List[PhaseServiceExplanation] = []
    milestone_explanations: List[MilestoneServiceExplanation] = []
    phase_lookup = {phase.phase_type: phase for phase in contract_copy.phases}
    milestone_lookup = {milestone.milestone_id: milestone for milestone in contract_copy.milestones}

    for item in raw_selection.get("phase_recommendations", []) if isinstance(raw_selection, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        phase_type = _compact_text(item.get("phase_type"))
        phase = phase_lookup.get(phase_type)
        if phase is None:
            continue
        allowed_rows = phase_allowed_rows.get(phase_type, {})
        selected = _sanitize_selected_services(item.get("selected_services"), allowed_rows)
        phase.recommended_now = [
            RecommendedService(
                service_id=selected_item["service_id"],
                display_name_vi=allowed_rows[selected_item["service_id"]].display_name_vi,
                category=allowed_rows[selected_item["service_id"]].category,
                role=selected_item["role"],
                why_recommended=selected_item["why_recommended"],
                expected_benefit=selected_item["expected_benefit"] or allowed_rows[selected_item["service_id"]].user_benefit_vi,
            )
            for selected_item in selected
        ]
        phase.recommended_services = list(phase.recommended_now)
        phase.service_selection_reason = _compact_text(item.get("explanation"))
        phase.future_services_preview = _build_preview_items(
            phase_blocked_rows.get(phase_type, []),
            context,
            phase_type=phase.phase_type,
            phase_status=phase.status,
            selected_ids={item.service_id for item in phase.recommended_now},
        )
        phase_explanations.append(
            PhaseServiceExplanation(
                phase_type=phase_type,
                selected_services=[
                    ServiceReference(
                        service_id=selected_item["service_id"],
                        display_name_vi=allowed_rows[selected_item["service_id"]].display_name_vi,
                        role=selected_item["role"],
                    )
                    for selected_item in selected
                ],
                explanation=phase.service_selection_reason,
            )
        )

    for item in raw_selection.get("milestone_recommendations", []) if isinstance(raw_selection, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        milestone_id = _compact_text(item.get("milestone_id"))
        milestone = milestone_lookup.get(milestone_id)
        if milestone is None:
            continue
        allowed_rows = milestone_allowed_rows.get(milestone_id, {})
        selected = _sanitize_selected_services(item.get("selected_services"), allowed_rows)
        milestone.recommended_now = [
            RecommendedService(
                service_id=selected_item["service_id"],
                display_name_vi=allowed_rows[selected_item["service_id"]].display_name_vi,
                category=allowed_rows[selected_item["service_id"]].category,
                role=selected_item["role"],
                why_recommended=selected_item["why_recommended"],
                expected_benefit=selected_item["expected_benefit"] or allowed_rows[selected_item["service_id"]].user_benefit_vi,
            )
            for selected_item in selected
        ]
        milestone.recommended_services = list(milestone.recommended_now)
        milestone.service_selection_reason = _compact_text(item.get("explanation"))
        milestone.future_services_preview = _build_preview_items(
            milestone_blocked_rows.get(milestone_id, []),
            context,
            phase_type=milestone.phase_type,
            phase_status=milestone.status,
            milestone_type=_MILESTONE_TYPE_BY_PHASE.get(milestone.phase_type, milestone.phase_type),
            selected_ids={item.service_id for item in milestone.recommended_now},
        )
        milestone_explanations.append(
            MilestoneServiceExplanation(
                milestone_id=milestone_id,
                selected_services=[
                    ServiceReference(
                        service_id=selected_item["service_id"],
                        display_name_vi=allowed_rows[selected_item["service_id"]].display_name_vi,
                        role=selected_item["role"],
                    )
                    for selected_item in selected
                ],
                explanation=milestone.service_selection_reason,
            )
        )

    for phase in contract_copy.phases:
        if not phase.recommended_services:
            phase.recommended_now = []
            phase.recommended_services = []
            phase.future_services_preview = _build_preview_items(
                phase_blocked_rows.get(phase.phase_type, []),
                context,
                phase_type=phase.phase_type,
                phase_status=phase.status,
                selected_ids=set(),
            )

    for milestone in contract_copy.milestones:
        if not milestone.recommended_services:
            milestone.recommended_now = []
            milestone.recommended_services = []
            milestone.future_services_preview = _build_preview_items(
                milestone_blocked_rows.get(milestone.milestone_id, []),
                context,
                phase_type=milestone.phase_type,
                phase_status=milestone.status,
                milestone_type=_MILESTONE_TYPE_BY_PHASE.get(milestone.phase_type, milestone.phase_type),
                selected_ids=set(),
            )

    next_action_payload = (
        raw_selection.get("next_action_service")
        if isinstance(raw_selection, Mapping) and isinstance(raw_selection.get("next_action_service"), Mapping)
        else {}
    )
    next_service_id = _compact_text(next_action_payload.get("service_id"))
    if contract_copy.next_best_action and next_service_id and next_service_id in current_phase_allowed:
        selected_row = current_phase_allowed[next_service_id]
        contract_copy.next_best_action.recommended_service = NextActionRecommendedService(
            service_id=selected_row.service_id,
            display_name_vi=selected_row.display_name_vi,
            category=selected_row.category,
            why_this_service_now=_compact_text(next_action_payload.get("why_this_service_now")),
            how_it_supports_transition=_compact_text(next_action_payload.get("how_it_supports_transition")),
        )
    elif contract_copy.next_best_action:
        primary_service = next(
            (
                service
                for phase in contract_copy.phases
                if phase.phase_type == contract_copy.current_phase
                for service in phase.recommended_services
                if service.role == "primary"
            ),
            None,
        )
        if primary_service:
            contract_copy.next_best_action.recommended_service = NextActionRecommendedService(
                service_id=primary_service.service_id,
                display_name_vi=primary_service.display_name_vi,
                category=primary_service.category,
                why_this_service_now="This service is the clearest match for the current phase and the immediate next action.",
                how_it_supports_transition=contract_copy.next_best_action.follow_on_transition or "",
            )

    contract_copy.service_recommendations = [
        CandidateServiceMap(
            phase_type=phase.phase_type,
            service_ids=[item.service_id for item in phase.recommended_services],
        )
        for phase in contract_copy.phases
        if phase.recommended_services
    ]

    diagnostics["service_recommendation_status"] = "ok"
    diagnostics["service_selection_warnings"].extend(
        [
            _compact_text(item)
            for item in raw_selection.get("selection_warnings", [])
            if _compact_text(item)
        ]
        if isinstance(raw_selection, Mapping)
        else []
    )
    diagnostics["phase_service_explanations"] = [item.model_dump(exclude_none=True) for item in phase_explanations]
    diagnostics["milestone_service_explanations"] = [item.model_dump(exclude_none=True) for item in milestone_explanations]
    next_action_explanation = NextActionServiceExplanation(
        selected_service=contract_copy.next_best_action.recommended_service.model_dump(exclude_none=True)
        if contract_copy.next_best_action and contract_copy.next_best_action.recommended_service
        else {},
        explanation=_compact_text(next_action_payload.get("why_this_service_now")),
    )
    diagnostics["next_action_service_explanation"] = next_action_explanation.model_dump(exclude_none=True)
    return contract_copy, diagnostics
