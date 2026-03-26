from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from service_agent.contracts import RoadmapContract, ServiceExplanation
from service_agent.model_adapter import invoke_json_prompt, resolve_model_id

logger = logging.getLogger(__name__)

_GOAL_LABELS = {
    "vehicle_purchase": "vehicle purchase",
    "emergency_fund": "emergency fund",
    "home_purchase": "home purchase",
    "travel": "travel goal",
    "education": "education goal",
    "wedding": "wedding goal",
    "general_savings": "savings goal",
}

_PHASE_LABELS = {
    "stabilize": "stabilize monthly cash flow",
    "protect_liquidity": "protect your cash flow",
    "accumulate": "build steady contributions",
    "readiness_review": "review whether the pace is enough",
    "maturity_transition": "prepare for execution or reset the target path",
}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _friendly_goal_label(value: Any) -> str:
    key = _compact_text(value).lower()
    if not key:
        return ""
    return _GOAL_LABELS.get(key, key.replace("_", " "))


def _friendly_phase_label(value: Any) -> str:
    key = _compact_text(value).lower()
    if not key:
        return ""
    return _PHASE_LABELS.get(key, key.replace("_", " "))


def _format_amount_display(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _compact_text(value)
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{round(numeric):,} VND"
    return f"{numeric:,.2f}".rstrip("0").rstrip(".") + " VND"


def _target_gap(contract: RoadmapContract) -> float | None:
    if contract.projection.target_amount is None or contract.projection.projected_end_amount is None:
        return None
    return round(float(contract.projection.target_amount) - float(contract.projection.projected_end_amount), 2)


def _projection_trend(contract: RoadmapContract) -> str:
    series = contract.projection.series
    if len(series) < 2:
        return "flat"
    first = float(series[0].projected_amount)
    last = float(series[-1].projected_amount)
    if last > first + 1:
        return "improving"
    if last < first - 1:
        return "declining"
    return "flat"


def _fact_pack(contract: RoadmapContract) -> Dict[str, Any]:
    goal = contract.goal.model_dump(exclude_none=True)
    planner = contract.planner_state.model_dump(exclude_none=True)
    savings_capacity = planner.get("savings_capacity") if isinstance(planner.get("savings_capacity"), dict) else {}
    next_action = contract.next_best_action.model_dump(exclude_none=True) if contract.next_best_action else {}
    projection_gap = _target_gap(contract)

    cautions: List[str] = []
    for item in [*contract.warnings, contract.projection.caution]:
        text = _compact_text(item)
        if text and text not in cautions:
            cautions.append(text)

    selected_service_recommendations = [
        {
            "phase_type": phase.phase_type,
            "service_ids": [item.service_id for item in phase.recommended_services],
        }
        for phase in contract.phases
        if phase.recommended_services
    ]

    return {
        "status": contract.status,
        "missing_fields": list(contract.missing_fields),
        "goal_snapshot": {
            "goal_type_code": goal.get("goal_type"),
            "goal_type_label": _friendly_goal_label(goal.get("goal_type")),
            "target_amount_value": goal.get("target_amount"),
            "target_amount_display": _format_amount_display(goal.get("target_amount")),
            "timeline_months": goal.get("target_timeline_months"),
            "timeline_display": f"{goal.get('target_timeline_months')} months" if goal.get("target_timeline_months") else "",
            "priority": _compact_text(goal.get("priority")),
        },
        "planner_snapshot": {
            "cashflow_status": _compact_text(planner.get("cashflow_status")),
            "savings_capacity_label": _compact_text(savings_capacity.get("label")),
            "savings_capacity_monthly_value": savings_capacity.get("amount_monthly"),
            "savings_capacity_monthly_display": _format_amount_display(savings_capacity.get("amount_monthly")),
            "runway_months": planner.get("runway_months"),
            "liquidity_pressure": _compact_text(planner.get("liquidity_pressure")),
            "anomaly_state": _compact_text(planner.get("anomaly_state")),
            "readiness_label": _compact_text(planner.get("readiness_label")),
            "feasibility_hint": _compact_text(planner.get("feasibility_hint")),
            "risk_band": _compact_text(planner.get("risk_band")),
            "buffer_status": _compact_text(planner.get("buffer_status")),
            "goal_progress_ratio": planner.get("goal_progress_ratio"),
        },
        "journey_pattern": contract.journey_pattern,
        "current_phase": {
            "phase_type": contract.current_phase,
            "phase_label": _friendly_phase_label(contract.current_phase),
        },
        "phases": [
            {
                "phase_type": phase.phase_type,
                "title": phase.title,
                "status": phase.status,
                "objective": phase.objective,
                "entry_conditions": list(phase.entry_conditions),
                "exit_conditions": list(phase.exit_conditions),
                "expected_results": list(phase.expected_results),
                "service_ids": list(phase.service_ids),
                "recommended_services": [item.model_dump(exclude_none=True) for item in phase.recommended_services],
                "service_selection_reason": phase.service_selection_reason,
            }
            for phase in contract.phases
        ],
        "milestones": [
            {
                "milestone_id": item.milestone_id,
                "phase_type": item.phase_type,
                "phase_label": _friendly_phase_label(item.phase_type),
                "title": item.title,
                "unlock_rule": item.unlock_rule,
                "expected_result": item.expected_result,
                "status": item.status,
                "recommended_services": [service.model_dump(exclude_none=True) for service in item.recommended_services],
                "service_selection_reason": item.service_selection_reason,
            }
            for item in contract.milestones
        ],
        "projection": {
            "confidence_label": contract.projection.confidence_label,
            "basis": contract.projection.basis,
            "target_amount_value": contract.projection.target_amount,
            "target_amount_display": _format_amount_display(contract.projection.target_amount),
            "projected_end_amount_value": contract.projection.projected_end_amount,
            "projected_end_amount_display": _format_amount_display(contract.projection.projected_end_amount),
            "timeline_months": contract.projection.target_timeline_months,
            "target_gap_value": projection_gap,
            "target_gap_display": _format_amount_display(projection_gap) if projection_gap is not None else "",
            "trend": _projection_trend(contract),
            "series": [point.model_dump() for point in contract.projection.series],
            "caution": _compact_text(contract.projection.caution),
        },
        "next_best_action": next_action,
        "service_recommendations": selected_service_recommendations,
        "cautions": cautions[:3],
    }


def _prompt(contract: RoadmapContract) -> str:
    return (
        "Return JSON only.\n"
        "You are the read-only explanation layer for a financial roadmap contract.\n"
        "You must not change roadmap structure, phase order, milestone order, numbers, warnings, or projections.\n"
        "You must not invent facts that are not present in the supplied contract facts.\n"
        "Use calm, polished, professional English that feels specific, trustworthy, and product-ready.\n"
        "Avoid robotic phrasing, motivational filler, and repeated sentences.\n"
        "Do not use internal enum names in user-facing prose. Keep `phase_type` and `milestone_id` exact only where they act as identifiers.\n"
        "If you mention money, use 'VND' and never currency symbols.\n"
        "If a phase, milestone, or next action has no selected banking service, return an empty selected_services list or empty selected_service object instead of inventing one.\n"
        "The summary must start with the goal and timeline, explain the current phase in plain language, state whether the pace is enough or not, and mention the main blocker when there is one.\n"
        "If cashflow is negative but liquidity pressure is low, explain that carefully using runway or buffer facts when they are present.\n"
        "If feasibility is low, keep the projection commentary realistically off pace.\n"
        "Keep every field EXTREMELY concise and punchy to guarantee successful JSON generation. Use these strict hard budgets:\n"
        "- summary: max 35 words\n"
        "- why_fit: max 30 words\n"
        "- current_phase_explanation: max 30 words\n"
        "- each phase explanation field: max 15 words\n"
        "- each milestone explanation field: max 12 words\n"
        "- each next_action_explanation field: max 15 words\n"
        "- each projection_explanation field: max 15 words\n"
        "- each phase_service_explanations explanation: max 15 words\n"
        "- each milestone_service_explanations explanation: max 15 words\n"
        "- next_action_service_explanation.explanation: max 15 words\n"
        "- each caution: max 10 words\n"
        "- confidence_note: max 15 words\n"
        "Output shape:\n"
        '{"summary":"","why_fit":"","current_phase_explanation":"","phase_explanations":[{"phase_type":"","why_this_phase_exists":"","why_it_is_current_or_upcoming":"","what_success_looks_like":"","what_unlocks_next_phase":""}],"milestone_explanations":[{"milestone_id":"","why_it_matters":"","what_needs_to_happen":"","what_changes_after_completion":""}],"next_action_explanation":{"why_now":"","what_to_check":"","what_success_looks_like":"","what_happens_next":""},"projection_explanation":{"basis":"","pace_assessment":"","target_gap_commentary":"","trend_commentary":""},"phase_service_explanations":[{"phase_type":"","selected_services":[{"service_id":"","display_name_vi":"","role":"primary"}],"explanation":""}],"milestone_service_explanations":[{"milestone_id":"","selected_services":[{"service_id":"","display_name_vi":"","role":"supporting"}],"explanation":""}],"next_action_service_explanation":{"selected_service":{},"explanation":""},"cautions":[""],"confidence_note":""}\n'
        f"Contract facts:\n{json.dumps(_fact_pack(contract), ensure_ascii=True, sort_keys=True)}"
    )


def _tool_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "summary",
            "why_fit",
            "current_phase_explanation",
            "phase_explanations",
            "milestone_explanations",
            "next_action_explanation",
            "projection_explanation",
            "phase_service_explanations",
            "milestone_service_explanations",
            "next_action_service_explanation",
            "cautions",
            "confidence_note",
        ],
        "properties": {
            "summary": {"type": "string"},
            "why_fit": {"type": "string"},
            "current_phase_explanation": {"type": "string"},
            "phase_explanations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "phase_type",
                        "why_this_phase_exists",
                        "why_it_is_current_or_upcoming",
                        "what_success_looks_like",
                        "what_unlocks_next_phase",
                    ],
                    "properties": {
                        "phase_type": {"type": "string"},
                        "why_this_phase_exists": {"type": "string"},
                        "why_it_is_current_or_upcoming": {"type": "string"},
                        "what_success_looks_like": {"type": "string"},
                        "what_unlocks_next_phase": {"type": "string"},
                    },
                },
            },
            "milestone_explanations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "milestone_id",
                        "why_it_matters",
                        "what_needs_to_happen",
                        "what_changes_after_completion",
                    ],
                    "properties": {
                        "milestone_id": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "what_needs_to_happen": {"type": "string"},
                        "what_changes_after_completion": {"type": "string"},
                    },
                },
            },
            "next_action_explanation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "why_now",
                    "what_to_check",
                    "what_success_looks_like",
                    "what_happens_next",
                ],
                "properties": {
                    "why_now": {"type": "string"},
                    "what_to_check": {"type": "string"},
                    "what_success_looks_like": {"type": "string"},
                    "what_happens_next": {"type": "string"},
                },
            },
            "projection_explanation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "basis",
                    "pace_assessment",
                    "target_gap_commentary",
                    "trend_commentary",
                ],
                "properties": {
                    "basis": {"type": "string"},
                    "pace_assessment": {"type": "string"},
                    "target_gap_commentary": {"type": "string"},
                    "trend_commentary": {"type": "string"},
                },
            },
            "phase_service_explanations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["phase_type", "selected_services", "explanation"],
                    "properties": {
                        "phase_type": {"type": "string"},
                        "selected_services": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["service_id", "display_name_vi", "role"],
                                "properties": {
                                    "service_id": {"type": "string"},
                                    "display_name_vi": {"type": "string"},
                                    "role": {"type": "string", "enum": ["primary", "supporting"]},
                                },
                            },
                        },
                        "explanation": {"type": "string"},
                    },
                },
            },
            "milestone_service_explanations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["milestone_id", "selected_services", "explanation"],
                    "properties": {
                        "milestone_id": {"type": "string"},
                        "selected_services": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["service_id", "display_name_vi", "role"],
                                "properties": {
                                    "service_id": {"type": "string"},
                                    "display_name_vi": {"type": "string"},
                                    "role": {"type": "string", "enum": ["primary", "supporting"]},
                                },
                            },
                        },
                        "explanation": {"type": "string"},
                    },
                },
            },
            "next_action_service_explanation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["selected_service", "explanation"],
                "properties": {
                    "selected_service": {"type": "object", "additionalProperties": True},
                    "explanation": {"type": "string"},
                },
            },
            "cautions": {"type": "array", "items": {"type": "string"}},
            "confidence_note": {"type": "string"},
        },
    }


def build_explanation(contract: RoadmapContract) -> Tuple[ServiceExplanation, Dict[str, Any]]:
    model_id = resolve_model_id("SERVICE_AGENT_SUMMARY_MODEL_ID", "SERVICE_AGENT_MODEL_ID", "BEDROCK_MODEL_ID")
    try:
        raw_payload, invoke_meta = invoke_json_prompt(
            _prompt(contract),
            model_id=model_id,
            max_tokens=2200,
            temperature=0.2,
            tool_name="submit_explanation",
            tool_schema=_tool_schema(),
            tool_description="Submit the structured explanation object for the final roadmap contract.",
        )
        explanation = ServiceExplanation.model_validate(raw_payload)
        return explanation, invoke_meta
    except Exception as exc:  # pragma: no cover - runtime path
        logger.warning("service_explanation_layer_failed error=%s", exc)
        return ServiceExplanation(), {"mode": "model_error", "model_id": model_id, "error": str(exc)}
