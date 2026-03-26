from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from service_agent.constants import (
    PHASE_ACCUMULATE,
    PHASE_MATURITY,
    PHASE_PROTECT,
    PHASE_REVIEW,
    PHASE_STABILIZE,
    SERVICE_PHASE_ALLOWLIST,
)


@dataclass(frozen=True)
class ServiceCatalogItem:
    service_id: str
    label: str
    phase_types: List[str]
    rationale: str


SERVICE_CATALOG: Dict[str, ServiceCatalogItem] = {
    "anomaly_review": ServiceCatalogItem(
        service_id="anomaly_review",
        label="Anomaly review",
        phase_types=[PHASE_PROTECT],
        rationale="Use when suspicious activity or unusual signals need quick review.",
    ),
    "budget_controls": ServiceCatalogItem(
        service_id="budget_controls",
        label="Budget controls",
        phase_types=[PHASE_STABILIZE],
        rationale="Use to tighten recurring spending and reduce drift.",
    ),
    "recurring_expense_cleanup": ServiceCatalogItem(
        service_id="recurring_expense_cleanup",
        label="Recurring expense cleanup",
        phase_types=[PHASE_STABILIZE],
        rationale="Use to remove unauthorised or low-value recurring costs.",
    ),
    "liquidity_guardrails": ServiceCatalogItem(
        service_id="liquidity_guardrails",
        label="Liquidity guardrails",
        phase_types=[PHASE_PROTECT, PHASE_STABILIZE],
        rationale="Use when runway or daily liquidity looks fragile.",
    ),
    "emergency_buffer_setup": ServiceCatalogItem(
        service_id="emergency_buffer_setup",
        label="Emergency buffer setup",
        phase_types=[PHASE_PROTECT, PHASE_STABILIZE],
        rationale="Use to rebuild short-term resilience before aggressive saving.",
    ),
    "auto_save_activation": ServiceCatalogItem(
        service_id="auto_save_activation",
        label="Auto-save activation",
        phase_types=[PHASE_ACCUMULATE],
        rationale="Use to make contributions steady and low-friction.",
    ),
    "goal_bucket_setup": ServiceCatalogItem(
        service_id="goal_bucket_setup",
        label="Goal bucket setup",
        phase_types=[PHASE_ACCUMULATE],
        rationale="Use to keep the goal separated from daily spending.",
    ),
    "contribution_review": ServiceCatalogItem(
        service_id="contribution_review",
        label="Contribution review",
        phase_types=[PHASE_ACCUMULATE, PHASE_REVIEW],
        rationale="Use to compare current pace with required pace and adjust.",
    ),
    "readiness_check": ServiceCatalogItem(
        service_id="readiness_check",
        label="Readiness check",
        phase_types=[PHASE_REVIEW],
        rationale="Use when the plan is close enough to reassess confidently.",
    ),
    "maturity_options_review": ServiceCatalogItem(
        service_id="maturity_options_review",
        label="Maturity options review",
        phase_types=[PHASE_MATURITY],
        rationale="Use when the goal is near completion and transition decisions matter.",
    ),
}


def is_valid_service_phase_pair(service_id: str, phase_type: str) -> bool:
    return phase_type in SERVICE_PHASE_ALLOWLIST.get(service_id, [])


def default_services_for_phase(phase_type: str) -> List[str]:
    if phase_type == PHASE_PROTECT:
        return ["anomaly_review", "liquidity_guardrails", "emergency_buffer_setup"]
    if phase_type == PHASE_STABILIZE:
        return ["budget_controls", "recurring_expense_cleanup", "liquidity_guardrails"]
    if phase_type == PHASE_ACCUMULATE:
        return ["goal_bucket_setup", "auto_save_activation", "contribution_review"]
    if phase_type == PHASE_REVIEW:
        return ["readiness_check", "contribution_review"]
    if phase_type == PHASE_MATURITY:
        return ["maturity_options_review"]
    return []
