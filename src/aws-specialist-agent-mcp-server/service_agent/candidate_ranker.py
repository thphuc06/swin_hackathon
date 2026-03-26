from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from service_agent.catalog import is_valid_service_phase_pair
from service_agent.constants import (
    PHASE_ACCUMULATE,
    PHASE_PROTECT,
    PHASE_REVIEW,
    PHASE_STABILIZE,
    SCORE_TIE_TOLERANCE,
    SCORE_WEIGHTS,
)
from service_agent.contracts import CandidateProposal
from service_agent.candidate_validator import ValidatedCandidate
from service_agent.roadmap_context import RoadmapContext


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class ScoredCandidate:
    candidate: CandidateProposal
    validation: ValidatedCandidate
    components: Dict[str, float]
    final_score: float


def _feasibility_score(context: RoadmapContext) -> float:
    mapping = {"high": 0.9, "medium": 0.72, "low": 0.45, "stretch": 0.3, "unknown": 0.55}
    base = mapping.get(context.planner_state.feasibility_hint, 0.55)
    pace_ratio = context.planner_state.required_pace_vs_current_pace
    if pace_ratio is not None:
        if pace_ratio <= 0.8:
            base += 0.08
        elif pace_ratio <= 1.2:
            base += 0.03
        elif pace_ratio >= 1.8:
            base -= 0.15
        elif pace_ratio >= 1.3:
            base -= 0.08
    return _clamp(base)


def _liquidity_safety_score(candidate: CandidateProposal, context: RoadmapContext) -> float:
    pressure = context.planner_state.liquidity_pressure
    first_two = candidate.phase_types[:2]
    base = 0.55
    if pressure in {"high", "critical"}:
        if PHASE_PROTECT in first_two:
            base = 0.95
        elif PHASE_STABILIZE in first_two:
            base = 0.8
        else:
            base = 0.25
    elif pressure == "medium":
        if any(phase in first_two for phase in (PHASE_PROTECT, PHASE_STABILIZE)):
            base = 0.82
        else:
            base = 0.45
    else:
        if candidate.phase_types and candidate.phase_types[0] == PHASE_ACCUMULATE:
            base = 0.62
        elif PHASE_STABILIZE in first_two:
            base = 0.72
    return _clamp(base)


def _goal_alignment_score(candidate: CandidateProposal, context: RoadmapContext) -> float:
    score = 0.5
    if context.goal.goal_type:
        score += 0.1
    if context.goal.target_timeline_months and context.goal.target_timeline_months <= 12 and PHASE_REVIEW in candidate.phase_types:
        score += 0.05
    if PHASE_ACCUMULATE in candidate.phase_types:
        score += 0.2
    if context.user_context.liquidity_need == "high" and candidate.phase_types and candidate.phase_types[0] == PHASE_PROTECT:
        score += 0.1
    return _clamp(score)


def _planner_alignment_score(candidate: CandidateProposal, context: RoadmapContext) -> float:
    score = 0.45
    planner_state = context.planner_state
    first_two = candidate.phase_types[:2]
    if planner_state.cashflow_status == "negative" and PHASE_STABILIZE in first_two:
        score += 0.2
    if planner_state.anomaly_state == "active" and PHASE_PROTECT in first_two:
        score += 0.2
    if planner_state.readiness_label == "ready" and PHASE_ACCUMULATE in candidate.phase_types:
        score += 0.1
    if planner_state.readiness_label in {"not_ready", "cautious"} and candidate.phase_types and candidate.phase_types[0] == PHASE_ACCUMULATE:
        score -= 0.15
    return _clamp(score)


def _stock_context_alignment_score(candidate: CandidateProposal, context: RoadmapContext) -> float:
    stock_context = context.user_context.stock_context
    if stock_context is None:
        return 0.55

    suitability_status = str(stock_context.suitability_status or "").strip().lower()
    market_tone = str(stock_context.market_tone or "").strip().lower()
    caution_terms = {"warn", "deny", "fail", "blocked", "cautious", "volatile", "risk_off", "bearish"}
    constructive_terms = {"pass", "ok", "constructive", "supportive", "bullish"}
    first_two = candidate.phase_types[:2]
    warning_count = len(stock_context.warning_flags) + len(stock_context.market_notes)

    base = 0.55
    if suitability_status in caution_terms or market_tone in caution_terms or warning_count >= 2:
        if PHASE_PROTECT in first_two:
            base = 0.92
        elif PHASE_STABILIZE in first_two:
            base = 0.8
        elif candidate.phase_types and candidate.phase_types[0] == PHASE_ACCUMULATE:
            base = 0.28
        else:
            base = 0.45
    elif suitability_status in constructive_terms or market_tone in constructive_terms:
        if PHASE_ACCUMULATE in candidate.phase_types:
            base = 0.72
        elif PHASE_STABILIZE in first_two:
            base = 0.64
    return _clamp(base)


def _service_coherence_score(candidate: CandidateProposal) -> float:
    if not candidate.service_candidates:
        return 0.55
    total_pairs = 0
    valid_pairs = 0
    for item in candidate.service_candidates:
        for service_id in item.service_ids:
            total_pairs += 1
            if is_valid_service_phase_pair(service_id, item.phase_type):
                valid_pairs += 1
    if total_pairs == 0:
        return 0.55
    return _clamp(valid_pairs / total_pairs)


def _journey_richness_score(candidate: CandidateProposal, context: RoadmapContext) -> float:
    planner_state = context.planner_state
    phase_count = len(candidate.phase_types)
    score = 0.45
    if phase_count >= 3:
        score += 0.16
    if phase_count >= 4:
        score += 0.08
    if PHASE_REVIEW in candidate.phase_types:
        score += 0.08
    if planner_state.anomaly_state == "active" and PHASE_PROTECT in candidate.phase_types:
        score += 0.08
    if planner_state.cashflow_status == "negative" and PHASE_STABILIZE in candidate.phase_types:
        score += 0.08
    if planner_state.readiness_label in {"cautious", "not_ready"} and phase_count >= 3:
        score += 0.05
    if context.goal.target_timeline_months and context.goal.target_timeline_months <= 12 and phase_count >= 4:
        score -= 0.06
    return _clamp(score)


def _complexity_penalty(candidate: CandidateProposal) -> float:
    if len(candidate.phase_types) <= 4:
        return 0.0
    return _clamp(max(0, len(candidate.phase_types) - 4) * 0.05)


def _partial_data_penalty(validation: ValidatedCandidate, context: RoadmapContext) -> float:
    total = sum(item.amount for item in validation.penalties)
    if context.readiness_class != "ready":
        total += 0.05
    return _clamp(total)


def score_candidate(validation: ValidatedCandidate, context: RoadmapContext) -> ScoredCandidate:
    candidate = validation.candidate
    feasibility = _feasibility_score(context)
    liquidity = _liquidity_safety_score(candidate, context)
    goal_alignment = _goal_alignment_score(candidate, context)
    planner_alignment = _planner_alignment_score(candidate, context)
    service_coherence = _service_coherence_score(candidate)
    stock_context_alignment = _stock_context_alignment_score(candidate, context)
    journey_richness = _journey_richness_score(candidate, context)
    complexity_penalty = _complexity_penalty(candidate)
    partial_penalty = _partial_data_penalty(validation, context)
    bounded_model_bonus = min(
        SCORE_WEIGHTS["model_bonus_max"],
        SCORE_WEIGHTS["model_bonus_max"] * max(0.0, float(candidate.model_fit_score or 0.0)),
    )

    final_score = (
        SCORE_WEIGHTS["feasibility"] * feasibility
        + SCORE_WEIGHTS["liquidity_safety"] * liquidity
        + SCORE_WEIGHTS["goal_alignment"] * goal_alignment
        + SCORE_WEIGHTS["planner_alignment"] * planner_alignment
        + SCORE_WEIGHTS["service_coherence"] * service_coherence
        + SCORE_WEIGHTS["stock_context_alignment"] * stock_context_alignment
        + SCORE_WEIGHTS["journey_richness"] * journey_richness
        - SCORE_WEIGHTS["complexity_penalty"] * complexity_penalty
        - SCORE_WEIGHTS["partial_penalty"] * partial_penalty
        + bounded_model_bonus
    )
    components = {
        "feasibility_score": feasibility,
        "liquidity_safety_score": liquidity,
        "goal_alignment_score": goal_alignment,
        "planner_state_alignment_score": planner_alignment,
        "service_phase_coherence_score": service_coherence,
        "stock_context_alignment_score": stock_context_alignment,
        "journey_richness_score": journey_richness,
        "complexity_penalty": complexity_penalty,
        "partial_data_penalty": partial_penalty,
        "bounded_model_fit_bonus": bounded_model_bonus,
    }
    return ScoredCandidate(candidate=candidate, validation=validation, components=components, final_score=round(final_score, 6))


def _tie_break_key(item: ScoredCandidate) -> tuple:
    return (
        -round(item.components["liquidity_safety_score"], 6),
        -round(item.components["feasibility_score"], 6),
        -round(item.components["journey_richness_score"], 6),
        len(item.candidate.phase_types),
        -round(item.components["goal_alignment_score"], 6),
        tuple(item.candidate.phase_types),
        item.candidate.candidate_id,
    )


def rank_candidates(validated_candidates: Iterable[ValidatedCandidate], context: RoadmapContext) -> List[ScoredCandidate]:
    scored = [score_candidate(item, context) for item in validated_candidates if item.is_valid]
    if not scored:
        return []

    def _sort_key(item: ScoredCandidate) -> tuple:
        return (-round(item.final_score, 6),) + _tie_break_key(item)

    scored.sort(key=_sort_key)
    if len(scored) > 1 and abs(scored[0].final_score - scored[1].final_score) <= SCORE_TIE_TOLERANCE:
        top_band = [item for item in scored if abs(item.final_score - scored[0].final_score) <= SCORE_TIE_TOLERANCE]
        top_band.sort(key=_tie_break_key)
        remainder = [item for item in scored if item not in top_band]
        scored = top_band + remainder
    return scored
