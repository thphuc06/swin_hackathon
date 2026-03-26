from __future__ import annotations

import logging
from typing import Any, Dict, List

from service_agent.candidate_normalizer import normalize_candidate
from service_agent.candidate_ranker import rank_candidates
from service_agent.candidate_schema import parse_candidate_set
from service_agent.candidate_validator import validate_candidate
from service_agent.banking_service_recommender import attach_banking_service_recommendations
from service_agent.constants import (
    AGENT_ID,
    AGENT_VERSION,
    CLASS_INSUFFICIENT_GOAL,
    CLASS_INSUFFICIENT_STATE,
    CLASS_REJECTED_FALLBACK,
    SCHEMA_VERSION,
    TOOL_NAME,
)
from service_agent.contracts import ServiceAgentEnvelope, ServiceResultSummary, SpecialistRequestEnvelope, UIExplanation
from service_agent.explanation_layer import build_explanation
from service_agent.layer1_sufficiency import classify_request
from service_agent.layer2_reasoning_adapter import propose_candidates
from service_agent.roadmap_compiler import build_partial_roadmap, compile_roadmap
from service_agent.roadmap_context import normalize_request
from service_agent.visualization_mapper import build_visualization

logger = logging.getLogger(__name__)


def _warning(code: str, message: str, severity: str = "warn") -> Dict[str, Any]:
    return {"code": code, "message": message, "severity": severity}


def _has_dict_payload(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _has_planner_context(user_context: Dict[str, Any]) -> bool:
    if _has_dict_payload(user_context.get("planner_state")):
        return True
    for key in ("planner_standardized_contract", "planner_contract", "last_planner_contract"):
        if _has_dict_payload(user_context.get(key)):
            return True
    return bool(str(user_context.get("planner_summary") or "").strip())


def _strip_stock_fields(user_context: Dict[str, Any]) -> None:
    for key in (
        "stock_context",
        "stock_envelope",
        "stock_advisory",
        "last_stock_advisory",
        "stock_specialist_result",
    ):
        user_context.pop(key, None)


def _projection_trend(contract: Dict[str, Any]) -> str:
    series = contract.get("projection", {}).get("series", []) if isinstance(contract.get("projection"), dict) else []
    if not isinstance(series, list) or len(series) < 2:
        return "flat"
    try:
        first = float(series[0].get("projected_amount"))
        last = float(series[-1].get("projected_amount"))
    except (TypeError, ValueError, AttributeError):
        return "flat"
    if last > first + 1:
        return "improving"
    if last < first - 1:
        return "declining"
    return "flat"


def _target_gap_level(contract: Dict[str, Any]) -> str:
    projection = contract.get("projection") if isinstance(contract.get("projection"), dict) else {}
    try:
        target_amount = float(projection.get("target_amount"))
        projected_end_amount = float(projection.get("projected_end_amount"))
    except (TypeError, ValueError):
        return "unknown"
    if target_amount <= 0:
        return "unknown"
    gap_ratio = max(0.0, (target_amount - projected_end_amount) / target_amount)
    if gap_ratio >= 0.75:
        return "very_high"
    if gap_ratio >= 0.45:
        return "high"
    if gap_ratio >= 0.2:
        return "moderate"
    return "low"


def _reasoning_signals(context, contract: Dict[str, Any]) -> Dict[str, Any]:
    planner = context.planner_state
    return {
        "anomaly_active": str(planner.anomaly_state or "").strip().lower() == "active",
        "negative_cashflow": str(planner.cashflow_status or "").strip().lower() == "negative"
        or ((planner.savings_capacity.amount_monthly or 0.0) < 0),
        "buffer_present": str(planner.buffer_status or "").strip().lower() == "present",
        "liquidity_pressure_level": planner.liquidity_pressure,
        "contribution_capacity_label": planner.savings_capacity.label,
        "target_gap_level": _target_gap_level(contract),
        "current_projection_trend": _projection_trend(contract),
    }


def _build_ui_explanation(explanation, contract) -> UIExplanation:
    next_explanation = explanation.next_action_explanation
    next_transition = ""
    if hasattr(next_explanation, "what_happens_next"):
        next_transition = str(next_explanation.what_happens_next or "").strip()
    if not next_transition and contract.next_best_action:
        next_transition = str(contract.next_best_action.follow_on_transition or "").strip()

    return UIExplanation(
        summary=str(explanation.summary or "").strip(),
        why_this_roadmap=str(explanation.why_fit or "").strip(),
        why_current_phase=str(explanation.current_phase_explanation or "").strip(),
        what_has_to_change_next=next_transition,
    )


def run_service(arguments: Dict[str, Any]) -> Dict[str, Any]:
    request = SpecialistRequestEnvelope.model_validate(arguments)
    
    user_context = request.request.user_context or {}
    
    # --- CROSS-AGENT AUTO INVOCATION ---
    # 1. Auto-invoke Planner if context is missing
    if not _has_planner_context(user_context):
        logger.info("Service Agent: Auto-invoking planner_agent for missing financial context.")
        try:
            from planner_agent.agent import run_planner
            planner_payload = request.model_dump(exclude_none=True)
            planner_payload["request"]["prompt"] = "Analyze my current financial status, cashflow, and savings capacity to establish a baseline for building a roadmap."
            planner_resp = run_planner(planner_payload)
            planner_contract = planner_resp.get("standardized_contract", {})
            if isinstance(planner_contract, dict) and planner_contract:
                user_context["planner_standardized_contract"] = planner_contract
                user_context["planner_contract"] = planner_contract
            planner_summary = str(
                planner_resp.get("summary")
                or ((planner_resp.get("result") or {}).get("summary") if isinstance(planner_resp.get("result"), dict) else "")
                or ""
            ).strip()
            if planner_summary:
                user_context["planner_summary"] = planner_summary
        except Exception as exc:
            logger.warning("Service Agent: Auto-invoke planner failed: %s", exc)

    _strip_stock_fields(user_context)
    request.request.user_context = user_context
    # --- END CROSS-AGENT AUTO INVOCATION ---

    context = classify_request(normalize_request(request))

    diagnostics: Dict[str, Any] = {
        "readiness_class": context.readiness_class,
        "missing_fields": list(context.missing_fields),
        "candidate_count": 0,
        "rejected_candidates": [],
        "service_recommendation_status": "not_attempted",
        "service_candidate_counts_by_phase": {},
        "service_candidate_counts_by_milestone": {},
        "service_filtering_notes": [],
        "service_selection_warnings": [],
    }
    warnings: List[Dict[str, Any]] = []

    if context.readiness_class in {CLASS_INSUFFICIENT_GOAL, CLASS_INSUFFICIENT_STATE}:
        fallback_reason = "Grounded roadmap generation is blocked until the missing goal or planner fields are available."
        contract = build_partial_roadmap(context, fallback_reason=fallback_reason)
        diagnostics["reasoning_signals"] = _reasoning_signals(context, contract.model_dump(exclude_none=True))
        explanation, explanation_meta = build_explanation(contract)
        diagnostics["layer4"] = explanation_meta
        envelope = ServiceAgentEnvelope(
            schema_version=SCHEMA_VERSION,
            agent_id=AGENT_ID,
            agent_version=AGENT_VERSION,
            tool_name=TOOL_NAME,
            status="partial",
            correlation=request.correlation.model_dump(),
            result=ServiceResultSummary(
                summary=explanation.summary,
                roadmap_status=context.readiness_class,
                journey_pattern=contract.journey_pattern,
                current_phase=contract.current_phase,
                phase_sequence=list(contract.phase_sequence),
            ),
            roadmap_contract=contract,
            explanation=explanation,
            ui_explanation=_build_ui_explanation(explanation, contract),
            warnings=[_warning("service_partial_setup", fallback_reason)],
            diagnostics=diagnostics,
        )
        return envelope.model_dump(exclude_none=True)

    candidate_set, adapter_meta = propose_candidates(context)
    diagnostics["layer2"] = adapter_meta
    candidate_set = parse_candidate_set(candidate_set)

    normalized_candidates = []
    for item in candidate_set.candidates:
        try:
            normalized_candidates.append(normalize_candidate(item))
        except Exception as exc:
            warnings.append(_warning("service_candidate_normalization_failed", str(exc)))

    validated = [validate_candidate(candidate, context) for candidate in normalized_candidates]
    diagnostics["candidate_count"] = len(normalized_candidates)
    diagnostics["rejected_candidates"] = [
        {"candidate_id": item.candidate.candidate_id, "reasons": list(item.hard_reject_reasons)}
        for item in validated
        if not item.is_valid
    ]

    ranked = rank_candidates(validated, context)
    if not ranked:
        context.readiness_class = CLASS_REJECTED_FALLBACK
        if adapter_meta.get("mode") == "model_error":
            warnings.append(
                _warning(
                    "service_candidate_proposal_failed",
                    "The roadmap proposal model did not return a usable structured candidate set, so the output stays in safe fallback mode.",
                )
            )
            fallback_reason = "The roadmap proposal layer did not return a usable structured candidate set, so the output stays in safe fallback mode."
        else:
            fallback_reason = "All roadmap candidates were rejected by deterministic policy checks, so the output stays in safe fallback mode."
        contract = build_partial_roadmap(context, fallback_reason=fallback_reason)
        diagnostics["reasoning_signals"] = _reasoning_signals(context, contract.model_dump(exclude_none=True))
        explanation, explanation_meta = build_explanation(contract)
        diagnostics["layer4"] = explanation_meta
        envelope = ServiceAgentEnvelope(
            schema_version=SCHEMA_VERSION,
            agent_id=AGENT_ID,
            agent_version=AGENT_VERSION,
            tool_name=TOOL_NAME,
            status="partial",
            correlation=request.correlation.model_dump(),
            result=ServiceResultSummary(
                summary=explanation.summary,
                roadmap_status=context.readiness_class,
                journey_pattern=contract.journey_pattern,
                current_phase=contract.current_phase,
                phase_sequence=list(contract.phase_sequence),
            ),
            roadmap_contract=contract,
            explanation=explanation,
            ui_explanation=_build_ui_explanation(explanation, contract),
            warnings=[_warning("service_candidate_rejected_fallback", fallback_reason), *warnings],
            diagnostics=diagnostics,
        )
        return envelope.model_dump(exclude_none=True)

    winner = ranked[0]
    diagnostics["selected_candidate"] = {
        "candidate_id": winner.candidate.candidate_id,
        "journey_pattern": winner.candidate.journey_pattern,
        "final_score": winner.final_score,
        "components": winner.components,
    }
    contract = compile_roadmap(context, winner.candidate)
    contract, service_meta = attach_banking_service_recommendations(context, contract)
    contract.visualization_support = build_visualization(contract)
    diagnostics.update(service_meta)
    contract_dump = contract.model_dump(exclude_none=True)
    diagnostics["reasoning_signals"] = _reasoning_signals(context, contract_dump)
    explanation, explanation_meta = build_explanation(contract)
    diagnostics["layer4"] = explanation_meta
    envelope = ServiceAgentEnvelope(
        schema_version=SCHEMA_VERSION,
        agent_id=AGENT_ID,
        agent_version=AGENT_VERSION,
        tool_name=TOOL_NAME,
        status="ok" if context.readiness_class == "ready" else "partial",
        correlation=request.correlation.model_dump(),
        result=ServiceResultSummary(
            summary=explanation.summary,
            roadmap_status=context.readiness_class,
            journey_pattern=contract.journey_pattern,
            current_phase=contract.current_phase,
            phase_sequence=list(contract.phase_sequence),
        ),
        roadmap_contract=contract,
        explanation=explanation,
        ui_explanation=_build_ui_explanation(explanation, contract),
        warnings=warnings,
        diagnostics=diagnostics,
    )
    return envelope.model_dump(exclude_none=True)
