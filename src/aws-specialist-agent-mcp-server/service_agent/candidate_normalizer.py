from __future__ import annotations

from typing import Dict, List

from service_agent.constants import JOURNEY_PATTERNS, PHASE_TYPES, SERVICE_IDS
from service_agent.contracts import CandidateProposal, CandidateServiceMap

_JOURNEY_ALIASES: Dict[str, str] = {
    "stabilization_first": "stabilize_then_accumulate_then_review",
    "stabilize_first": "stabilize_then_accumulate_then_review",
    "protect_then_progress": "protect_then_stabilize_then_accumulate_then_review",
    "protect_then_accumulate_then_review": "protect_then_accumulate",
}

_PHASE_ALIASES: Dict[str, str] = {
    "protect": "protect_liquidity",
    "verify_and_protect": "protect_liquidity",
    "build_buffer": "stabilize",
    "goal_funding": "accumulate",
    "review": "readiness_review",
}

_SERVICE_ALIASES: Dict[str, str] = {
    "transaction_alerts": "anomaly_review",
    "transaction_alerts_and_manual_verification": "anomaly_review",
    "manual_verification": "anomaly_review",
    "spend_limits": "budget_controls",
    "goal_savings_automation": "auto_save_activation",
}


def _normalize_journey(value: str) -> str:
    key = str(value or "").strip().lower()
    canonical = _JOURNEY_ALIASES.get(key, key)
    if canonical not in JOURNEY_PATTERNS:
        raise ValueError(f"unknown journey_pattern: {value}")
    return canonical


def _normalize_phase(value: str) -> str:
    key = str(value or "").strip().lower()
    canonical = _PHASE_ALIASES.get(key, key)
    if canonical not in PHASE_TYPES:
        raise ValueError(f"unknown phase_type: {value}")
    return canonical


def _normalize_service(value: str) -> str:
    key = str(value or "").strip().lower()
    canonical = _SERVICE_ALIASES.get(key, key)
    if canonical not in SERVICE_IDS:
        raise ValueError(f"unknown service_id: {value}")
    return canonical


def normalize_candidate(candidate: CandidateProposal) -> CandidateProposal:
    journey_pattern = _normalize_journey(candidate.journey_pattern)
    phase_types = candidate.phase_types or list(JOURNEY_PATTERNS[journey_pattern])
    normalized_phases: List[str] = []
    for phase in phase_types:
        canonical = _normalize_phase(phase)
        if canonical not in normalized_phases:
            normalized_phases.append(canonical)

    normalized_service_candidates: List[CandidateServiceMap] = []
    for item in candidate.service_candidates:
        phase_type = _normalize_phase(item.phase_type)
        service_ids = []
        for service_id in item.service_ids:
            canonical = _normalize_service(service_id)
            if canonical not in service_ids:
                service_ids.append(canonical)
        normalized_service_candidates.append(CandidateServiceMap(phase_type=phase_type, service_ids=service_ids))

    current_phase_hint = candidate.current_phase_hint
    if current_phase_hint:
        current_phase_hint = _normalize_phase(current_phase_hint)

    return candidate.model_copy(
        update={
            "journey_pattern": journey_pattern,
            "phase_types": normalized_phases,
            "current_phase_hint": current_phase_hint,
            "service_candidates": normalized_service_candidates,
            "rationale_tags": [str(item).strip().lower() for item in candidate.rationale_tags if str(item).strip()],
            "candidate_risk_tags": [str(item).strip().lower() for item in candidate.candidate_risk_tags if str(item).strip()],
            "proposal_confidence": max(0.0, min(1.0, float(candidate.proposal_confidence or 0.0))),
            "model_fit_score": max(0.0, min(1.0, float(candidate.model_fit_score or 0.0))),
        }
    )
