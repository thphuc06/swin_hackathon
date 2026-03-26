from __future__ import annotations

from typing import List

from service_agent.constants import PHASE_ACCUMULATE, PHASE_MATURITY, PHASE_PROTECT, PHASE_REVIEW, PHASE_STABILIZE
from service_agent.contracts import MilestoneContract


def build_milestones(phase_sequence: List[str], current_phase: str) -> List[MilestoneContract]:
    milestones: List[MilestoneContract] = []
    current_index = phase_sequence.index(current_phase) if current_phase in phase_sequence else 0
    milestone_specs = {
        PHASE_PROTECT: (
            "Resolve the immediate leakage or anomaly risk",
            "Flagged activity is reviewed and protection controls are active",
            "cash outflows stop leaking through avoidable or suspicious activity",
        ),
        PHASE_STABILIZE: (
            "Bring monthly cashflow back under control",
            "core spending is within a manageable range",
            "monthly cashflow is steadier and easier to plan around",
        ),
        PHASE_ACCUMULATE: (
            "Start a repeatable monthly contribution rhythm",
            "goal bucket and contribution flow are both active",
            "goal funding begins to move at a steady pace",
        ),
        PHASE_REVIEW: (
            "Check whether the current pace is still enough",
            "the plan is stable enough for a structured review",
            "the roadmap can be adjusted before the final stretch",
        ),
        PHASE_MATURITY: (
            "Prepare for the goal transition cleanly",
            "the goal is near completion or has reached its readiness gate",
            "the user can move into execution or post-goal handling",
        ),
    }

    for index, phase_type in enumerate(phase_sequence, start=1):
        title, unlock_rule, expected_result = milestone_specs.get(
            phase_type,
            ("Reach the next roadmap checkpoint", "the prior phase is complete", "the plan advances cleanly"),
        )
        zero_based_index = index - 1
        if zero_based_index < current_index:
            status = "completed"
        elif phase_type == current_phase:
            status = "current"
        else:
            status = "upcoming"
        milestones.append(
            MilestoneContract(
                milestone_id=f"ms_{index}",
                phase_type=phase_type,
                title=title,
                unlock_rule=unlock_rule,
                expected_result=expected_result,
                status=status,
            )
        )
    return milestones
