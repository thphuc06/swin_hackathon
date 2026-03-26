from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from planner_agent.contracts import (
    ErrorItem,
    PolicyOutcome,
    SpecialistRequestEnvelope,
    WarningItem,
)


class SavingsCapacity(BaseModel):
    amount_monthly: Optional[float] = None
    label: str = "unknown"


class PlannerState(BaseModel):
    cashflow_status: str = "unknown"
    savings_capacity: SavingsCapacity = Field(default_factory=SavingsCapacity)
    runway_months: Optional[float] = None
    liquidity_pressure: str = "unknown"
    anomaly_state: str = "unknown"
    readiness_label: str = "unknown"
    feasibility_hint: str = "unknown"
    risk_band: str = "unknown"
    income_stability: Optional[str] = None
    goal_progress_ratio: Optional[float] = None
    buffer_status: Optional[str] = None
    required_pace_vs_current_pace: Optional[float] = None
    source: Optional[str] = None


class GoalInput(BaseModel):
    goal_type: Optional[str] = None
    target_amount: Optional[float] = None
    target_timeline_months: Optional[int] = None
    priority: Optional[str] = None
    target_date: Optional[str] = None


class StockContextInput(BaseModel):
    summary: Optional[str] = None
    suitability_status: Optional[str] = None
    market_tone: Optional[str] = None
    market_notes: List[str] = Field(default_factory=list)
    warning_flags: List[str] = Field(default_factory=list)
    cited_symbols: List[str] = Field(default_factory=list)
    source: Optional[str] = None


class UserContextInput(BaseModel):
    risk_preference: Optional[str] = None
    liquidity_need: Optional[str] = None
    urgency: Optional[str] = None
    life_context: Optional[str] = None
    stock_context: Optional[StockContextInput] = None


class CandidateServiceMap(BaseModel):
    phase_type: str
    service_ids: List[str] = Field(default_factory=list)


class CandidateProposal(BaseModel):
    candidate_id: str
    journey_pattern: str
    phase_types: List[str] = Field(default_factory=list)
    current_phase_hint: Optional[str] = None
    service_candidates: List[CandidateServiceMap] = Field(default_factory=list)
    rationale_tags: List[str] = Field(default_factory=list)
    candidate_risk_tags: List[str] = Field(default_factory=list)
    requires_grounded_fields: List[str] = Field(default_factory=list)
    assumption_flags: List[str] = Field(default_factory=list)
    tradeoff_notes: List[str] = Field(default_factory=list)
    proposal_confidence: float = 0.0
    model_fit_score: float = 0.0


class CandidateSet(BaseModel):
    schema_version: str = "service_candidate_set_v1"
    readiness_class: str = "ready"
    candidates: List[CandidateProposal] = Field(default_factory=list)


class NextBestAction(BaseModel):
    title: str
    why: str
    timeframe: Optional[str] = None
    expected_outcome: Optional[str] = None
    success_signal: Optional[str] = None
    follow_on_transition: Optional[str] = None
    recommended_service: Optional["NextActionRecommendedService"] = None


class RecommendedService(BaseModel):
    service_id: str
    display_name_vi: str
    category: str
    role: Literal["primary", "supporting"]
    why_recommended: str = ""
    expected_benefit: str = ""


class FutureServicePreview(BaseModel):
    service_id: str
    display_name_vi: str
    category: str
    why_not_now: str = ""
    unlock_hint: str = ""
    expected_benefit: str = ""


class NextActionRecommendedService(BaseModel):
    service_id: str
    display_name_vi: str
    category: str
    why_this_service_now: str = ""
    how_it_supports_transition: str = ""


class PhaseContract(BaseModel):
    phase_type: str
    title: str
    objective: str
    entry_conditions: List[str] = Field(default_factory=list)
    exit_conditions: List[str] = Field(default_factory=list)
    expected_results: List[str] = Field(default_factory=list)
    service_ids: List[str] = Field(default_factory=list)
    recommended_now: List[RecommendedService] = Field(default_factory=list)
    recommended_services: List[RecommendedService] = Field(default_factory=list)
    future_services_preview: List[FutureServicePreview] = Field(default_factory=list)
    service_selection_reason: str = ""
    status: Literal["current", "upcoming", "locked", "completed"] = "upcoming"


class MilestoneContract(BaseModel):
    milestone_id: str
    phase_type: str
    title: str
    unlock_rule: str
    expected_result: str
    recommended_now: List[RecommendedService] = Field(default_factory=list)
    recommended_services: List[RecommendedService] = Field(default_factory=list)
    future_services_preview: List[FutureServicePreview] = Field(default_factory=list)
    service_selection_reason: str = ""
    status: Literal["current", "upcoming", "locked", "completed"] = "upcoming"


class ProjectionPoint(BaseModel):
    month: int
    projected_amount: float


class ProjectionContract(BaseModel):
    confidence_label: str = "directional"
    basis: str = ""
    target_amount: Optional[float] = None
    projected_end_amount: Optional[float] = None
    target_timeline_months: Optional[int] = None
    series: List[ProjectionPoint] = Field(default_factory=list)
    caution: Optional[str] = None


class MaturityEvent(BaseModel):
    event_type: str
    title: str
    condition: str


class StatusBanner(BaseModel):
    tone: Literal["supportive", "cautious", "urgent", "encouraging"] = "supportive"
    title: str = ""
    message: str = ""


class KeyMetrics(BaseModel):
    current_monthly_capacity: Dict[str, Any] = Field(default_factory=dict)
    current_progress_amount: Optional[float] = None
    current_progress_ratio: Optional[float] = None
    target_amount: Optional[float] = None
    timeline_months: Optional[int] = None
    projected_end_amount: Optional[float] = None
    feasibility_hint: str = ""
    readiness_label: str = ""


class UnlockCondition(BaseModel):
    phase_type: str
    status: str = ""
    conditions: List[str] = Field(default_factory=list)


class VisualizationSupport(BaseModel):
    timeline_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    phase_cards: List[Dict[str, Any]] = Field(default_factory=list)
    milestone_cards: List[Dict[str, Any]] = Field(default_factory=list)
    projection_chart: Dict[str, Any] = Field(default_factory=dict)
    next_action_card: Dict[str, Any] = Field(default_factory=dict)
    status_banner: StatusBanner = Field(default_factory=StatusBanner)
    key_metrics: KeyMetrics = Field(default_factory=KeyMetrics)
    unlock_conditions: List[UnlockCondition] = Field(default_factory=list)


class RoadmapContract(BaseModel):
    schema_version: str = "service_roadmap_contract_v1"
    status: str
    missing_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    goal: GoalInput = Field(default_factory=GoalInput)
    planner_state: PlannerState = Field(default_factory=PlannerState)
    user_context: UserContextInput = Field(default_factory=UserContextInput)
    journey_pattern: str = ""
    current_phase: str = ""
    phase_sequence: List[str] = Field(default_factory=list)
    phases: List[PhaseContract] = Field(default_factory=list)
    milestones: List[MilestoneContract] = Field(default_factory=list)
    projection: ProjectionContract = Field(default_factory=ProjectionContract)
    next_best_action: Optional[NextBestAction] = None
    maturity_events: List[MaturityEvent] = Field(default_factory=list)
    service_recommendations: List[CandidateServiceMap] = Field(default_factory=list)
    visualization_support: VisualizationSupport = Field(default_factory=VisualizationSupport)


class PhaseExplanation(BaseModel):
    phase_type: str
    why_this_phase_exists: str = ""
    why_it_is_current_or_upcoming: str = ""
    what_success_looks_like: str = ""
    what_unlocks_next_phase: str = ""


class MilestoneExplanation(BaseModel):
    milestone_id: str
    why_it_matters: str = ""
    what_needs_to_happen: str = ""
    what_changes_after_completion: str = ""


class NextActionExplanation(BaseModel):
    why_now: str = ""
    what_to_check: str = ""
    what_success_looks_like: str = ""
    what_happens_next: str = ""


class ProjectionExplanation(BaseModel):
    basis: str = ""
    pace_assessment: str = ""
    target_gap_commentary: str = ""
    trend_commentary: str = ""


class ServiceReference(BaseModel):
    service_id: str
    display_name_vi: str = ""
    role: Literal["primary", "supporting"] = "supporting"


class ServiceSelectionExplanation(BaseModel):
    explanation: str = ""


class PhaseServiceExplanation(ServiceSelectionExplanation):
    phase_type: str
    selected_services: List[ServiceReference] = Field(default_factory=list)


class MilestoneServiceExplanation(ServiceSelectionExplanation):
    milestone_id: str
    selected_services: List[ServiceReference] = Field(default_factory=list)


class NextActionServiceExplanation(BaseModel):
    selected_service: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


class ServiceExplanation(BaseModel):
    summary: str = ""
    why_fit: str = ""
    current_phase_explanation: str = ""
    phase_explanations: List[PhaseExplanation] = Field(default_factory=list)
    milestone_explanations: List[MilestoneExplanation] = Field(default_factory=list)
    next_action_explanation: NextActionExplanation = Field(default_factory=NextActionExplanation)
    projection_explanation: ProjectionExplanation = Field(default_factory=ProjectionExplanation)
    phase_service_explanations: List[PhaseServiceExplanation] = Field(default_factory=list)
    milestone_service_explanations: List[MilestoneServiceExplanation] = Field(default_factory=list)
    next_action_service_explanation: NextActionServiceExplanation = Field(default_factory=NextActionServiceExplanation)
    cautions: List[str] = Field(default_factory=list)
    confidence_note: str = ""


class UIExplanation(BaseModel):
    summary: str = ""
    why_this_roadmap: str = ""
    why_current_phase: str = ""
    what_has_to_change_next: str = ""


class ServiceResultSummary(BaseModel):
    summary: str
    roadmap_status: str
    journey_pattern: str = ""
    current_phase: str = ""
    phase_sequence: List[str] = Field(default_factory=list)


class ServiceAgentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v1"]
    agent_id: Literal["service"]
    agent_version: str
    tool_name: Literal["run_service_agent_v1"]
    status: Literal["ok", "partial", "error", "blocked"]
    correlation: Dict[str, Any]
    result: ServiceResultSummary
    roadmap_contract: RoadmapContract
    explanation: ServiceExplanation = Field(default_factory=ServiceExplanation)
    ui_explanation: UIExplanation = Field(default_factory=UIExplanation)
    policy: Optional[PolicyOutcome] = None
    warnings: List[WarningItem] = Field(default_factory=list)
    errors: List[ErrorItem] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CandidateProposal",
    "CandidateServiceMap",
    "CandidateSet",
    "GoalInput",
    "PlannerState",
    "RoadmapContract",
    "ServiceAgentEnvelope",
    "ServiceExplanation",
    "ServiceResultSummary",
    "SpecialistRequestEnvelope",
    "StockContextInput",
    "UserContextInput",
]
