from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from service_agent.catalog import is_valid_service_phase_pair
from service_agent.constants import PHASE_ACCUMULATE, PHASE_PROTECT, PHASE_STABILIZE, SERVICE_IDS
from service_agent.contracts import CandidateProposal
from service_agent.roadmap_context import RoadmapContext


@dataclass
class CandidatePenalty:
    key: str
    amount: float
    reason: str


@dataclass
class ValidatedCandidate:
    candidate: CandidateProposal
    penalties: List[CandidatePenalty] = field(default_factory=list)
    hard_reject_reasons: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.hard_reject_reasons


def _has_phase(candidate: CandidateProposal, phase_type: str) -> bool:
    return phase_type in candidate.phase_types


def validate_candidate(candidate: CandidateProposal, context: RoadmapContext) -> ValidatedCandidate:
    result = ValidatedCandidate(candidate=candidate)
    planner_state = context.planner_state

    for service_map in candidate.service_candidates:
        for service_id in service_map.service_ids:
            if service_id not in SERVICE_IDS:
                result.hard_reject_reasons.append(f"unknown_service_id:{service_id}")
            elif not is_valid_service_phase_pair(service_id, service_map.phase_type):
                result.hard_reject_reasons.append(f"invalid_service_phase_pair:{service_id}:{service_map.phase_type}")

    runway = planner_state.runway_months
    if runway is not None and runway < 3.0 and not _has_phase(candidate, PHASE_PROTECT):
        result.hard_reject_reasons.append("low_runway_without_protect_liquidity")

    amount_monthly = planner_state.savings_capacity.amount_monthly
    if amount_monthly is not None and amount_monthly <= 0 and candidate.phase_types and candidate.phase_types[0] == PHASE_ACCUMULATE:
        result.hard_reject_reasons.append("non_positive_capacity_with_immediate_accumulate")

    missing_required = [
        field_name
        for field_name in candidate.requires_grounded_fields
        if field_name in context.missing_fields or field_name == ""
    ]
    if missing_required:
        result.hard_reject_reasons.append(f"missing_required_grounded_fields:{','.join(sorted(set(missing_required)))}")

    anomaly_active = planner_state.anomaly_state == "active"
    first_two = candidate.phase_types[:2]
    if anomaly_active and PHASE_PROTECT not in first_two:
        if PHASE_STABILIZE in first_two:
            result.penalties.append(
                CandidatePenalty(
                    key="anomaly_underweighted",
                    amount=0.05,
                    reason="active anomaly state should prioritise protect_liquidity earlier",
                )
            )
        else:
            result.hard_reject_reasons.append("active_anomaly_ignored")

    if len(candidate.phase_types) > 4:
        result.penalties.append(
            CandidatePenalty(
                key="excessive_phase_count",
                amount=0.06,
                reason="candidate carries more phases than the MVP needs",
            )
        )

    if context.readiness_class != "ready" and candidate.proposal_confidence > 0.8:
        result.penalties.append(
            CandidatePenalty(
                key="overconfidence_under_weak_data",
                amount=0.03,
                reason="proposal confidence is too strong for partial data",
            )
        )

    if planner_state.readiness_label in {"not_ready", "cautious"} and candidate.phase_types and candidate.phase_types[0] == PHASE_ACCUMULATE:
        result.penalties.append(
            CandidatePenalty(
                key="readiness_mismatch",
                amount=0.05,
                reason="accumulation-first path is too aggressive for current readiness",
            )
        )

    if planner_state.cashflow_status == "negative" and not any(phase in first_two for phase in (PHASE_STABILIZE, PHASE_PROTECT)):
        result.hard_reject_reasons.append("negative_cashflow_without_early_stabilization")

    return result
