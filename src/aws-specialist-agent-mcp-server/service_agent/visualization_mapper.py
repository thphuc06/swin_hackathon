from __future__ import annotations

from typing import List, Optional

from service_agent.contracts import KeyMetrics, RoadmapContract, StatusBanner, UnlockCondition, VisualizationSupport


def _current_progress_amount(contract: RoadmapContract) -> Optional[float]:
    for point in contract.projection.series:
        if point.month == 0:
            return round(point.projected_amount, 2)
    target_amount = contract.goal.target_amount
    progress_ratio = contract.planner_state.goal_progress_ratio
    if target_amount is None or progress_ratio is None:
        return None
    return round(float(target_amount) * max(0.0, min(1.0, float(progress_ratio))), 2)


def _projection_gap(contract: RoadmapContract) -> Optional[float]:
    target_amount = contract.projection.target_amount
    projected_end_amount = contract.projection.projected_end_amount
    if target_amount is None or projected_end_amount is None:
        return None
    return round(float(target_amount) - float(projected_end_amount), 2)


def _projection_trend(contract: RoadmapContract) -> str:
    if len(contract.projection.series) < 2:
        return "flat"
    first = float(contract.projection.series[0].projected_amount)
    last = float(contract.projection.series[-1].projected_amount)
    if last > first + 1:
        return "improving"
    if last < first - 1:
        return "declining"
    return "flat"


def _status_banner(contract: RoadmapContract) -> StatusBanner:
    planner = contract.planner_state
    monthly_capacity = planner.savings_capacity.amount_monthly
    liquidity_pressure = str(planner.liquidity_pressure or "").strip().lower()
    anomaly_active = str(planner.anomaly_state or "").strip().lower() == "active"
    negative_cashflow = str(planner.cashflow_status or "").strip().lower() == "negative" or (
        monthly_capacity is not None and monthly_capacity < 0
    )
    runway_months = planner.runway_months
    buffer_present = str(planner.buffer_status or "").strip().lower() == "present"
    current_phase_title = next((phase.title for phase in contract.phases if phase.status == "current"), contract.current_phase)

    if liquidity_pressure in {"critical", "high"} or (runway_months is not None and runway_months < 3):
        return StatusBanner(
            tone="urgent",
            title="Stabilize the foundation before pushing the goal",
            message=(
                f"The plan is currently in {current_phase_title.lower()} because short-term liquidity is fragile. "
                "Contain near-term cash risk first so the roadmap does not rely on a weak monthly baseline."
            ),
        )
    if anomaly_active or negative_cashflow or str(planner.feasibility_hint or "").strip().lower() == "low":
        buffer_clause = ""
        if buffer_present or (runway_months is not None and runway_months >= 6):
            buffer_clause = (
                f" You still have some cushion from {'an existing buffer' if buffer_present else 'available runway'}, "
                "which keeps this from being an immediate cash emergency."
            )
        return StatusBanner(
            tone="cautious",
            title="Protect cash flow before pushing the goal",
            message=(
                f"The plan is in {current_phase_title.lower()} because the current monthly pace is not yet strong enough to support the goal."
                f"{buffer_clause}"
            ),
        )
    if contract.current_phase == "accumulate":
        return StatusBanner(
            tone="encouraging",
            title="The plan is ready to build momentum",
            message=(
                "The monthly baseline looks stable enough to fund the goal more directly, so the roadmap can focus on repeatable contributions."
            ),
        )
    return StatusBanner(
        tone="supportive",
        title="The roadmap is moving through a structured sequence",
        message="The current phase is designed to unlock the next one cleanly, without overreaching the financial baseline.",
    )


def _key_metrics(contract: RoadmapContract) -> KeyMetrics:
    return KeyMetrics(
        current_monthly_capacity={
            "amount": round(contract.planner_state.savings_capacity.amount_monthly, 2)
            if contract.planner_state.savings_capacity.amount_monthly is not None
            else None,
            "label": contract.planner_state.savings_capacity.label,
        },
        current_progress_amount=_current_progress_amount(contract),
        current_progress_ratio=contract.planner_state.goal_progress_ratio,
        target_amount=contract.goal.target_amount,
        timeline_months=contract.goal.target_timeline_months,
        projected_end_amount=contract.projection.projected_end_amount,
        feasibility_hint=contract.planner_state.feasibility_hint,
        readiness_label=contract.planner_state.readiness_label,
    )


def _unlock_conditions(contract: RoadmapContract) -> List[UnlockCondition]:
    items: List[UnlockCondition] = []
    current_index = next((index for index, phase in enumerate(contract.phases) if phase.status == "current"), 0)

    if contract.phases:
        current_phase = contract.phases[current_index]
        items.append(
            UnlockCondition(
                phase_type=current_phase.phase_type,
                status="current",
                conditions=list(current_phase.exit_conditions),
            )
        )

    next_index = current_index + 1
    if 0 <= next_index < len(contract.phases):
        next_phase = contract.phases[next_index]
        items.append(
            UnlockCondition(
                phase_type=next_phase.phase_type,
                status="next",
                conditions=list(next_phase.entry_conditions),
            )
        )

    return items


def build_visualization(contract: RoadmapContract) -> VisualizationSupport:
    projection_gap = _projection_gap(contract)

    return VisualizationSupport(
        timeline_nodes=[
            {
                "phase_type": phase.phase_type,
                "title": phase.title,
                "status": phase.status,
                "objective": phase.objective,
            }
            for phase in contract.phases
        ],
        phase_cards=[
            {
                "phase_type": phase.phase_type,
                "title": phase.title,
                "objective": phase.objective,
                "entry_conditions": list(phase.entry_conditions),
                "exit_conditions": list(phase.exit_conditions),
                "expected_results": list(phase.expected_results),
                "status": phase.status,
                "service_ids": list(phase.service_ids),
                "recommended_now": [item.model_dump(exclude_none=True) for item in phase.recommended_now],
                "recommended_services": [item.model_dump(exclude_none=True) for item in phase.recommended_services],
                "future_services_preview": [item.model_dump(exclude_none=True) for item in phase.future_services_preview],
                "service_selection_reason": phase.service_selection_reason,
            }
            for phase in contract.phases
        ],
        milestone_cards=[
            {
                "milestone_id": item.milestone_id,
                "phase_type": item.phase_type,
                "title": item.title,
                "unlock_rule": item.unlock_rule,
                "expected_result": item.expected_result,
                "status": item.status,
                "recommended_now": [service.model_dump(exclude_none=True) for service in item.recommended_now],
                "recommended_services": [service.model_dump(exclude_none=True) for service in item.recommended_services],
                "future_services_preview": [service.model_dump(exclude_none=True) for service in item.future_services_preview],
                "service_selection_reason": item.service_selection_reason,
            }
            for item in contract.milestones
        ],
        projection_chart={
            "confidence_label": contract.projection.confidence_label,
            "series": [point.model_dump() for point in contract.projection.series],
            "target_amount": contract.projection.target_amount,
            "projected_end_amount": contract.projection.projected_end_amount,
            "gap_to_target": projection_gap,
            "trend": _projection_trend(contract),
        },
        next_action_card=contract.next_best_action.model_dump(exclude_none=True) if contract.next_best_action else {},
        status_banner=_status_banner(contract),
        key_metrics=_key_metrics(contract),
        unlock_conditions=_unlock_conditions(contract),
    )
