from __future__ import annotations

import json
import logging
from typing import Any, Dict, Tuple

from service_agent.candidate_schema import parse_candidate_set
from service_agent.constants import (
    CLASS_PARTIAL,
    CLASS_READY,
    JOURNEY_PATTERNS,
    PHASE_ACCUMULATE,
    PHASE_PROTECT,
    PHASE_REVIEW,
    PHASE_STABILIZE,
    RATIONALE_TAGS,
    SERVICE_IDS,
)
from service_agent.contracts import CandidateSet
from service_agent.model_adapter import invoke_json_prompt, resolve_model_id
from service_agent.roadmap_context import RoadmapContext

logger = logging.getLogger(__name__)

_TOOL_NAME = "submit_candidate_set"
_LAYER2_SERVICE_IDS = [service_id for service_id in SERVICE_IDS if service_id != "maturity_options_review"]
_PHASE_SERVICE_RULES = {
    PHASE_STABILIZE: ["budget_controls", "recurring_expense_cleanup", "liquidity_guardrails", "emergency_buffer_setup"],
    PHASE_PROTECT: ["anomaly_review", "liquidity_guardrails", "emergency_buffer_setup"],
    PHASE_ACCUMULATE: ["auto_save_activation", "goal_bucket_setup", "contribution_review"],
    PHASE_REVIEW: ["readiness_check", "contribution_review"],
}


def _system_prompt() -> str:
    return (
        "You are Layer 2 of a financial roadmap service agent.\n"
        "Your job is to propose structured roadmap candidates only.\n"
        "You must respond by calling the provided tool exactly once.\n"
        "Do not answer in prose.\n"
        "Do not generate final milestones, projections, maturity outputs, dates, or the final roadmap contract.\n"
        "Stay inside the provided ontology only.\n"
        "phase_types must match the canonical phase sequence for the selected journey_pattern exactly.\n"
        "service_candidates must only use valid service-phase pairings.\n"
        "The service-phase rules are strict and must be followed exactly.\n"
        "Prefer safer journey structures when anomaly risk, low runway, negative cashflow, or cautious readiness are present.\n"
        "If stock_context is present, use it only as a secondary signal to enrich timing and caution, never to override planner safety.\n"
        "Return one or two or three or four compact grounded candidates only.\n"
        "Keep each field concise. Do not pad tradeoff or assumption lists.\n"
    )


def _candidate_tool_schema() -> Dict[str, Any]:
    required_grounded_fields = [
        "planner_state.cashflow_status",
        "planner_state.savings_capacity.amount_monthly",
        "planner_state.runway_months",
        "planner_state.liquidity_pressure",
        "planner_state.anomaly_state",
        "planner_state.readiness_label",
        "planner_state.feasibility_hint",
        "planner_state.risk_band",
        "goal.goal_type",
        "goal.target_amount",
        "goal.target_timeline_months",
        "goal.priority",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "readiness_class", "candidates"],
        "properties": {
            "schema_version": {"type": "string", "enum": ["service_candidate_set_v1"]},
            "readiness_class": {
                "type": "string",
                "enum": [CLASS_READY, CLASS_PARTIAL, "insufficient_goal_data", "insufficient_financial_state"],
            },
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "candidate_id",
                        "journey_pattern",
                        "phase_types",
                        "current_phase_hint",
                        "service_candidates",
                        "rationale_tags",
                        "candidate_risk_tags",
                        "requires_grounded_fields",
                        "assumption_flags",
                        "tradeoff_notes",
                        "proposal_confidence",
                        "model_fit_score",
                    ],
                    "properties": {
                        "candidate_id": {"type": "string", "minLength": 3, "maxLength": 64},
                        "journey_pattern": {"type": "string", "enum": sorted(JOURNEY_PATTERNS.keys())},
                        "phase_types": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "items": {
                                "type": "string",
                                "enum": [PHASE_STABILIZE, PHASE_PROTECT, PHASE_ACCUMULATE, PHASE_REVIEW],
                            },
                        },
                        "current_phase_hint": {
                            "type": "string",
                            "enum": [PHASE_STABILIZE, PHASE_PROTECT, PHASE_ACCUMULATE, PHASE_REVIEW],
                        },
                        "service_candidates": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["phase_type", "service_ids"],
                                "properties": {
                                    "phase_type": {
                                        "type": "string",
                                        "enum": [PHASE_STABILIZE, PHASE_PROTECT, PHASE_ACCUMULATE, PHASE_REVIEW],
                                    },
                                    "service_ids": {
                                        "type": "array",
                                        "minItems": 1,
                                        "maxItems": 3,
                                        "items": {"type": "string", "enum": sorted(_LAYER2_SERVICE_IDS)},
                                    },
                                },
                            },
                        },
                        "rationale_tags": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {"type": "string", "enum": sorted(RATIONALE_TAGS)},
                        },
                        "candidate_risk_tags": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                        "requires_grounded_fields": {
                            "type": "array",
                            "maxItems": 6,
                            "items": {"type": "string", "enum": required_grounded_fields},
                        },
                        "assumption_flags": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                        "tradeoff_notes": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                        "proposal_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "model_fit_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                },
            },
        },
    }


def _attempt_prompt(context: RoadmapContext, *, retry_reason: str = "") -> str:
    context_payload = {
        "goal": context.goal.model_dump(exclude_none=True),
        "planner_state": context.planner_state.model_dump(exclude_none=True),
        "user_context": context.user_context.model_dump(exclude_none=True),
        "readiness_class": context.readiness_class,
        "canonical_journey_patterns": JOURNEY_PATTERNS,
        "phase_service_rules": _PHASE_SERVICE_RULES,
    }
    instructions = [
        "Return 1 or 2 or 3 or 4 candidate journeys only.",
        "Make the first candidate the safest grounded option for the given planner state.",
        "Do not include maturity_transition in phase_types.",
        "Every candidate must keep phase_types aligned with the selected journey_pattern sequence exactly.",
        "Use no more than 3 services per phase.",
        "Respect phase_service_rules exactly. Never place a service in a phase that is not listed for it.",
        "Let stock_context refine timing and caution only when it is present; never let it overrule planner_state safety.",
        "If the user context is complex, it is acceptable to prefer fuller 3-4 phase journeys over overly compressed paths.",
        "Keep rationale_tags, assumption_flags, and tradeoff_notes short and selective.",
        "Always include at least one valid candidate.",
    ]
    if retry_reason:
        instructions.append(
            f"Previous attempt failed validation: {retry_reason}. Return exactly 1 compact candidate that fully respects the schema and ontology."
        )
    return (
        "Structured candidate request.\n"
        + "\n".join(f"- {item}" for item in instructions)
        + "\nContext:\n"
        + json.dumps(context_payload, ensure_ascii=True, sort_keys=True)
    )


def propose_candidates(context: RoadmapContext) -> Tuple[CandidateSet, Dict[str, Any]]:
    empty = CandidateSet(schema_version="service_candidate_set_v1", readiness_class=context.readiness_class, candidates=[])
    model_id = resolve_model_id("SERVICE_AGENT_MODEL_ID", "BEDROCK_MODEL_ID")
    attempt_errors: list[str] = []

    def _run_attempt(retry_reason: str = "") -> Tuple[CandidateSet, Dict[str, Any]]:
        raw_payload, invoke_meta = invoke_json_prompt(
            _attempt_prompt(context, retry_reason=retry_reason),
            model_id=model_id,
            system_prompt=_system_prompt(),
            tool_name=_TOOL_NAME,
            tool_schema=_candidate_tool_schema(),
            tool_description="Return a structured set of service roadmap candidates.",
            max_tokens=4096,
            temperature=0.1,
        )
        candidate_set = parse_candidate_set(raw_payload)
        if not candidate_set.candidates:
            raise ValueError("candidate set is empty")
        invoke_meta["attempt_errors"] = list(attempt_errors)
        return candidate_set, invoke_meta

    try:
        return _run_attempt()
    except Exception as exc:  # pragma: no cover - runtime path
        attempt_errors.append(str(exc))
        logger.warning("service_candidate_proposal_retrying error=%s", exc)

    try:
        candidate_set, invoke_meta = _run_attempt(retry_reason=attempt_errors[-1])
        invoke_meta["retried"] = True
        return candidate_set, invoke_meta
    except Exception as exc:  # pragma: no cover - runtime path
        attempt_errors.append(str(exc))
        logger.warning("service_candidate_proposal_failed error=%s", exc)
        return empty, {
            "mode": "model_error",
            "model_id": model_id,
            "error": str(exc),
            "attempt_errors": attempt_errors,
        }
