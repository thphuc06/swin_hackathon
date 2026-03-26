from __future__ import annotations

from typing import List

from service_agent.contracts import ProjectionContract, ProjectionPoint
from service_agent.roadmap_context import RoadmapContext


def build_projection(context: RoadmapContext) -> ProjectionContract:
    target_amount = context.goal.target_amount
    timeline = context.goal.target_timeline_months
    monthly_capacity = context.planner_state.savings_capacity.amount_monthly
    progress_ratio = context.planner_state.goal_progress_ratio or 0.0
    starting_amount = (target_amount or 0.0) * max(0.0, min(1.0, progress_ratio))

    if not target_amount or not timeline or monthly_capacity is None:
        return ProjectionContract(
            confidence_label="provisional",
            basis="missing_target_or_capacity",
            target_amount=target_amount,
            target_timeline_months=timeline,
            projected_end_amount=None,
            series=[],
            caution="A grounded projection needs both a usable goal target and planner-derived savings capacity.",
        )

    checkpoints = sorted(set([0, max(1, timeline // 3), max(1, (2 * timeline) // 3), timeline]))
    series: List[ProjectionPoint] = []
    for month in checkpoints:
        projected_amount = max(0.0, starting_amount + (monthly_capacity * month))
        series.append(ProjectionPoint(month=month, projected_amount=round(projected_amount, 2)))

    feasibility = context.planner_state.feasibility_hint
    if context.readiness_class != "ready":
        confidence = "provisional"
    elif feasibility in {"high", "medium"}:
        confidence = "directional"
    else:
        confidence = "cautious"

    projected_end_amount = max(0.0, starting_amount + (monthly_capacity * timeline))

    return ProjectionContract(
        confidence_label=confidence,
        basis="planner_state_monthly_capacity",
        target_amount=float(target_amount),
        projected_end_amount=round(projected_end_amount, 2),
        target_timeline_months=timeline,
        series=series,
        caution="Projection values are planning guides, not guaranteed outcomes.",
    )
