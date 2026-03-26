from __future__ import annotations

from service_agent.constants import (
    CLASS_INSUFFICIENT_GOAL,
    CLASS_INSUFFICIENT_STATE,
    CLASS_PARTIAL,
    CLASS_READY,
)
from service_agent.roadmap_context import RoadmapContext, classify_missing_fields


def classify_request(context: RoadmapContext) -> RoadmapContext:
    missing_fields = classify_missing_fields(context)
    context.missing_fields = missing_fields

    goal_missing = [field for field in missing_fields if field.startswith("goal.")]
    planner_missing = [field for field in missing_fields if field.startswith("planner_state.")]

    has_goal_core = len(goal_missing) <= 1
    has_planner_core = len(planner_missing) <= 2

    if not goal_missing and not planner_missing:
        context.readiness_class = CLASS_READY
    elif has_goal_core and has_planner_core:
        context.readiness_class = CLASS_PARTIAL
    elif goal_missing:
        context.readiness_class = CLASS_INSUFFICIENT_GOAL
    else:
        context.readiness_class = CLASS_INSUFFICIENT_STATE
    return context
