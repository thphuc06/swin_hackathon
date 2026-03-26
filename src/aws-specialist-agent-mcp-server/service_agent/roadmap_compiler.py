from __future__ import annotations

from typing import Dict, List

from service_agent.catalog import default_services_for_phase
from service_agent.constants import (
    PHASE_ACCUMULATE,
    PHASE_MATURITY,
    PHASE_PROTECT,
    PHASE_REVIEW,
    PHASE_STABILIZE,
    PHASE_TITLES,
)
from service_agent.contracts import CandidateProposal, CandidateServiceMap, NextBestAction, PhaseContract, RoadmapContract
from service_agent.maturity_engine import build_maturity_events
from service_agent.milestone_engine import build_milestones
from service_agent.projection_engine import build_projection
from service_agent.roadmap_context import RoadmapContext
from service_agent.visualization_mapper import build_visualization


def _phase_services(candidate: CandidateProposal) -> Dict[str, List[str]]:
    service_map: Dict[str, List[str]] = {}
    for item in candidate.service_candidates:
        service_map[item.phase_type] = list(item.service_ids)
    for phase_type in candidate.phase_types:
        service_map.setdefault(phase_type, default_services_for_phase(phase_type))
    return service_map


def _determine_current_phase(context: RoadmapContext, phase_sequence: List[str]) -> str:
    planner_state = context.planner_state
    if planner_state.anomaly_state == "active" and PHASE_PROTECT in phase_sequence:
        return PHASE_PROTECT
    if planner_state.liquidity_pressure in {"critical", "high"} and PHASE_PROTECT in phase_sequence:
        return PHASE_PROTECT
    if planner_state.cashflow_status == "negative" and PHASE_STABILIZE in phase_sequence:
        return PHASE_STABILIZE
    if planner_state.readiness_label in {"not_ready", "cautious"} and PHASE_STABILIZE in phase_sequence:
        return PHASE_STABILIZE
    if PHASE_ACCUMULATE in phase_sequence:
        return PHASE_ACCUMULATE
    return phase_sequence[0]


def _phase_objectives(phase_type: str) -> tuple[str, List[str], List[str], List[str]]:
    if phase_type == PHASE_PROTECT:
        return (
            "Contain unusual outflows and stop avoidable leakage before the plan loses more ground.",
            [
                "Planner signals show anomaly risk, unreliable cash movement, or liquidity fragility.",
                "The current monthly baseline cannot be trusted enough for aggressive saving yet.",
            ],
            [
                "Protection controls are active and suspicious leakage is reviewed.",
                "Short-term balances are no longer being quietly drained by unresolved outflows.",
            ],
            [
                "Short-term balances are safer and cash outflows are easier to trust.",
                "The roadmap can move into repair with fewer unknown losses.",
            ],
        )
    if phase_type == PHASE_STABILIZE:
        return (
            "Move the monthly position back toward a manageable baseline that can support the goal.",
            [
                "Core spending needs to be more predictable before pushing harder toward the goal.",
                "The current plan still needs a steadier monthly operating range.",
            ],
            [
                "Monthly cashflow is no longer persistently negative.",
                "Core spending is back inside a manageable operating range.",
            ],
            [
                "The plan stops depending on quiet balance drawdown to survive normal months.",
                "The roadmap can move from repair into steady progress.",
            ],
        )
    if phase_type == PHASE_ACCUMULATE:
        return (
            "Turn a repaired monthly baseline into repeatable goal contributions.",
            [
                "The plan has enough stability to start funding the goal more directly.",
                "A contribution amount can be funded without reopening liquidity stress.",
            ],
            [
                "Goal contributions are active and paced against the target.",
                "A dedicated goal bucket is in use and monthly deposits are repeating.",
            ],
            [
                "Progress becomes visible and easier to sustain.",
                "The user can judge the real pace against the goal timeline.",
            ],
        )
    if phase_type == PHASE_REVIEW:
        return (
            "Re-check whether the current pace and assumptions still fit the target timeline.",
            [
                "The roadmap is stable enough to re-check the pace before the final stretch.",
                "A contribution pattern exists and can now be compared with the required pace.",
            ],
            [
                "The plan is recalibrated against the current pace and target timeline.",
                "A clear decision exists on whether the roadmap stays on path or needs a reset.",
            ],
            [
                "The next transition can happen with fewer surprises.",
                "The user gets a more realistic view of execution readiness.",
            ],
        )
    return (
        "Handle the transition once the goal is near execution or needs a final decision checkpoint.",
        [
            "The goal is near maturity or the plan has reached a formal go or no-go review point.",
        ],
        [
            "Execution or post-goal handling is ready to start.",
            "The roadmap has reached a clear decision point instead of drifting forward blindly.",
        ],
        ["The user moves into the next financial state cleanly."],
    )


def _next_best_action(current_phase: str) -> NextBestAction:
    if current_phase == PHASE_PROTECT:
        return NextBestAction(
            title="Verify the highest-risk transactions and tighten liquidity guardrails",
            why="Protecting cashflow comes first when anomaly or liquidity risk is active.",
            timeframe="within 24 hours",
            expected_outcome="The most suspicious or avoidable outflows are either explained, stopped, or contained so the cashflow picture becomes usable again.",
            success_signal="Flagged transactions are reviewed, abnormal leakage is addressed, and the user can describe where cash is leaving with more confidence.",
            follow_on_transition="Once leakage risk is contained, the roadmap can move into stabilize and focus on repairing the monthly baseline.",
        )
    if current_phase == PHASE_STABILIZE:
        return NextBestAction(
            title="Cut or contain the biggest controllable spending leaks",
            why="A steadier monthly baseline makes the rest of the roadmap much more realistic.",
            timeframe="this week",
            expected_outcome="The monthly position becomes easier to manage and less dependent on existing balances.",
            success_signal="Core spending is trimmed enough that monthly cashflow stops staying persistently negative.",
            follow_on_transition="With a steadier monthly baseline, the roadmap can move into accumulate and start goal funding more directly.",
        )
    if current_phase == PHASE_ACCUMULATE:
        return NextBestAction(
            title="Activate a simple recurring contribution into the goal bucket",
            why="Consistency matters more than intensity once the plan is ready to accumulate.",
            timeframe="this week",
            expected_outcome="The goal starts receiving steady deposits from true monthly surplus.",
            success_signal="A recurring transfer is active and the contribution is actually repeating month after month.",
            follow_on_transition="Once the contribution rhythm is stable, the roadmap can enter readiness review and test whether the pace is enough.",
        )
    if current_phase == PHASE_REVIEW:
        return NextBestAction(
            title="Review contribution pace against the goal timeline",
            why="A short review now can prevent drift later in the roadmap.",
            timeframe="this month",
            expected_outcome="The user gets a grounded answer on whether the current pace can still meet the target timeline.",
            success_signal="The roadmap has a clear decision to stay on path, increase pace, or reset the target path.",
            follow_on_transition="That review unlocks the final transition into execution readiness or a deliberate plan reset.",
        )
    return NextBestAction(
        title="Review the maturity options for the goal",
        why="The roadmap is close enough to shift from setup into decision-making.",
        timeframe="next review window",
        expected_outcome="Execution choices become clear and the roadmap ends in a deliberate transition.",
        success_signal="The user reaches a go or no-go decision instead of continuing in an open-ended holding pattern.",
        follow_on_transition="The roadmap closes into execution, post-goal handling, or a fresh planning cycle.",
    )


def build_partial_roadmap(context: RoadmapContext, *, fallback_reason: str) -> RoadmapContract:
    phase_sequence = [PHASE_REVIEW, PHASE_STABILIZE, PHASE_ACCUMULATE]
    contract = RoadmapContract(
        status=context.readiness_class,
        missing_fields=list(context.missing_fields),
        warnings=[
            "This roadmap is still provisional because the required goal or planner inputs are incomplete.",
            fallback_reason,
        ],
        goal=context.goal,
        planner_state=context.planner_state,
        user_context=context.user_context,
        journey_pattern="",
        current_phase=PHASE_REVIEW,
        phase_sequence=phase_sequence,
        phases=[
            PhaseContract(
                phase_type=PHASE_REVIEW,
                title="Confirm the missing setup details",
                objective="Collect the missing goal or planner inputs before making grounded roadmap decisions.",
                entry_conditions=["The current request is missing key goal or financial-state fields."],
                exit_conditions=["The missing goal fields or planner-derived state are available."],
                expected_results=["The next Service run can produce a more grounded roadmap."],
                service_ids=[],
                status="current",
            ),
            PhaseContract(
                phase_type=PHASE_STABILIZE,
                title=PHASE_TITLES[PHASE_STABILIZE],
                objective="Prepare the plan for a stable cashflow baseline once the missing inputs are filled.",
                entry_conditions=["The setup phase is complete."],
                exit_conditions=["Core cashflow can be evaluated against the goal."],
                expected_results=["The roadmap can move from setup into action."],
                service_ids=default_services_for_phase(PHASE_STABILIZE),
                status="locked",
            ),
            PhaseContract(
                phase_type=PHASE_ACCUMULATE,
                title=PHASE_TITLES[PHASE_ACCUMULATE],
                objective="Start the goal-funding path once the setup and stabilization work is done.",
                entry_conditions=["Goal details and planner state are both available."],
                exit_conditions=["The first stable contribution rhythm is active."],
                expected_results=["The roadmap becomes fully actionable."],
                service_ids=default_services_for_phase(PHASE_ACCUMULATE),
                status="locked",
            ),
        ],
        next_best_action=NextBestAction(
            title="Fill the missing roadmap inputs first",
            why="Grounded roadmap decisions need both a clear goal and planner-derived financial state.",
            timeframe="now",
            expected_outcome="The next Service run will have enough grounded context to produce a fuller roadmap.",
            success_signal="Missing goal fields or planner-derived state are available in the request.",
            follow_on_transition="Once the missing inputs are available, the roadmap can move from setup into a real current phase.",
        ),
    )
    contract.milestones = build_milestones(contract.phase_sequence, contract.current_phase)
    contract.projection = build_projection(context)
    contract.maturity_events = build_maturity_events(context, contract.projection)
    contract.visualization_support = build_visualization(contract)
    return contract


def compile_roadmap(context: RoadmapContext, candidate: CandidateProposal) -> RoadmapContract:
    phase_sequence = list(candidate.phase_types)
    if phase_sequence and phase_sequence[-1] != PHASE_MATURITY:
        phase_sequence.append(PHASE_MATURITY)
    current_phase = _determine_current_phase(context, phase_sequence)
    service_map = _phase_services(candidate)
    phase_contracts: List[PhaseContract] = []
    current_seen = False
    for phase_type in phase_sequence:
        objective, entry_conditions, exit_conditions, expected_results = _phase_objectives(phase_type)
        if phase_type == current_phase:
            status = "current"
            current_seen = True
        elif not current_seen:
            status = "completed"
        else:
            status = "upcoming"
        phase_contracts.append(
            PhaseContract(
                phase_type=phase_type,
                title=PHASE_TITLES.get(phase_type, phase_type.replace("_", " ").title()),
                objective=objective,
                entry_conditions=entry_conditions,
                exit_conditions=exit_conditions,
                expected_results=expected_results,
                service_ids=service_map.get(phase_type, []),
                status=status,
            )
        )

    contract = RoadmapContract(
        status=context.readiness_class,
        missing_fields=list(context.missing_fields),
        warnings=list(context.warnings),
        goal=context.goal,
        planner_state=context.planner_state,
        user_context=context.user_context,
        journey_pattern=candidate.journey_pattern,
        current_phase=current_phase,
        phase_sequence=phase_sequence,
        phases=phase_contracts,
        service_recommendations=[
            CandidateServiceMap(phase_type=phase_type, service_ids=service_map.get(phase_type, []))
            for phase_type in phase_sequence
            if service_map.get(phase_type)
        ],
        next_best_action=_next_best_action(current_phase),
    )
    contract.milestones = build_milestones(phase_sequence, current_phase)
    contract.projection = build_projection(context)
    contract.maturity_events = build_maturity_events(context, contract.projection)
    contract.visualization_support = build_visualization(contract)
    return contract
