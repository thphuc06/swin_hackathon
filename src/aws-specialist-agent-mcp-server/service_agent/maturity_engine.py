from __future__ import annotations

from typing import List

from service_agent.contracts import MaturityEvent, ProjectionContract
from service_agent.roadmap_context import RoadmapContext


def build_maturity_events(context: RoadmapContext, projection: ProjectionContract) -> List[MaturityEvent]:
    target_amount = context.goal.target_amount or 0.0
    projected_end = projection.projected_end_amount or 0.0
    if target_amount > 0 and projected_end >= target_amount:
        return [
            MaturityEvent(
                event_type="goal_ready_for_execution",
                title="Goal looks reachable within the current plan",
                condition="projected contributions reach the target within the current timeline",
            )
        ]
    return [
        MaturityEvent(
            event_type="readiness_review_required",
            title="A readiness review is needed before final commitment",
            condition="the current contribution pace still falls short of the target path",
        )
    ]
