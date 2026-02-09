from __future__ import annotations

from typing import Any

from .contracts import ActionCandidateV1, AdvisoryContextV1, EvidencePackV1, InsightV1
from .insights import build_insights_from_facts


def _insight_ids(insights: list[InsightV1]) -> set[str]:
    return {item.insight_id for item in insights}


def _service_priority_by_risk(risk_appetite: str) -> dict[str, int]:
    if risk_appetite == "conservative":
        return {"savings": 15, "cards": 20, "loan": 24, "consult": 45}
    if risk_appetite == "moderate":
        return {"savings": 20, "cards": 18, "loan": 19, "consult": 44}
    if risk_appetite == "aggressive":
        return {"savings": 26, "cards": 20, "loan": 15, "consult": 42}
    return {"savings": 22, "cards": 19, "loan": 18, "consult": 46}


def _add_action(
    candidates: list[ActionCandidateV1],
    seen: set[str],
    *,
    action_id: str,
    priority: int,
    action_type: str,
    params: dict[str, Any] | None = None,
    supporting_insight_ids: list[str] | None = None,
) -> None:
    if action_id in seen:
        return
    seen.add(action_id)
    candidates.append(
        ActionCandidateV1(
            action_id=action_id,
            priority=priority,
            action_type=action_type,
            params=params or {},
            supporting_insight_ids=supporting_insight_ids or [],
        )
    )


def build_action_candidates(
    *,
    intent: str,
    insights: list[InsightV1],
    policy_flags: dict[str, Any] | None = None,
) -> list[ActionCandidateV1]:
    candidates: list[ActionCandidateV1] = []
    seen: set[str] = set()
    insight_ids = _insight_ids(insights)
    risk_appetite = str((policy_flags or {}).get("risk_appetite") or "").strip().lower()
    if risk_appetite not in {"conservative", "moderate", "aggressive"}:
        risk_appetite = "unknown"
    service_priorities = _service_priority_by_risk(risk_appetite)

    if "insight.cashflow_pressure" in insight_ids or "insight.cashflow_negative" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="stabilize_cashflow",
            priority=10,
            action_type="cashflow_control",
            params={"window_days": 14},
            supporting_insight_ids=[
                item
                for item in ["insight.cashflow_pressure", "insight.cashflow_negative"]
                if item in insight_ids
            ],
        )

    if "insight.spend_anomaly" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="review_anomaly",
            priority=20,
            action_type="anomaly_review",
            params={"lookback_days": 90},
            supporting_insight_ids=["insight.spend_anomaly"],
        )

    if "insight.savings_capacity" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="buffer_build",
            priority=20,
            action_type="savings_buffer",
            params={"allocation_ratio": 0.2},
            supporting_insight_ids=["insight.savings_capacity"],
        )

    if "insight.jar_focus" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="jar_optimize",
            priority=30,
            action_type="allocation_optimize",
            params={"method": "top_jar_rebalance"},
            supporting_insight_ids=["insight.jar_focus"],
        )

    if "insight.goal_gap" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="goal_replan",
            priority=25,
            action_type="goal_recalibration",
            params={"recheck_weeks": 4},
            supporting_insight_ids=["insight.goal_gap"],
        )

    if "insight.scenario_upside" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="scenario_monitor",
            priority=30,
            action_type="scenario_tracking",
            params={"monitor_weeks": 2},
            supporting_insight_ids=["insight.scenario_upside"],
        )
    if "insight.scenario_no_upside" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="scenario_downside_guard",
            priority=18,
            action_type="scenario_risk_control",
            params={"review_days": 14, "focus": "reduce_top_spend_bucket"},
            supporting_insight_ids=["insight.scenario_no_upside"],
        )

    if "insight.risk_preference_unknown" in insight_ids and str(intent or "") in {"planning", "scenario", "invest"}:
        _add_action(
            candidates,
            seen,
            action_id="capture_risk_appetite",
            priority=8,
            action_type="advisor_question",
            params={
                "question": "Ban uu tien muc rui ro nao?",
                "options": ["thap", "vua", "cao"],
            },
            supporting_insight_ids=["insight.risk_preference_unknown"],
        )

    if "insight.service_loan_support" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="service_loan_healthcheck",
            priority=service_priorities["loan"],
            action_type="service_suggestion",
            params={
                "service_family": "loans_credit",
                "examples": ["loan_restructure", "installment_conversion"],
                "risk_appetite": risk_appetite,
            },
            supporting_insight_ids=["insight.service_loan_support"],
        )

    if "insight.service_spend_control" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="service_spend_control_setup",
            priority=service_priorities["cards"],
            action_type="service_suggestion",
            params={
                "service_family": "cards_payments",
                "examples": ["card_spend_cap", "transaction_alert"],
                "risk_appetite": risk_appetite,
            },
            supporting_insight_ids=["insight.service_spend_control"],
        )

    if "insight.service_savings_option" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="service_savings_setup",
            priority=service_priorities["savings"],
            action_type="service_suggestion",
            params={
                "service_family": "savings_deposit",
                "examples": ["recurring_savings", "term_deposit"],
                "risk_appetite": risk_appetite,
            },
            supporting_insight_ids=["insight.service_savings_option"],
        )

    if "insight.service_catalog_available" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="service_needs_consult",
            priority=service_priorities["consult"],
            action_type="service_suggestion",
            params={"service_family": "catalog", "cadence_days": 7, "risk_appetite": risk_appetite},
            supporting_insight_ids=["insight.service_catalog_available"],
        )

    if "insight.education_only" in insight_ids:
        _add_action(
            candidates,
            seen,
            action_id="education_only_guard",
            priority=5,
            action_type="compliance",
            params={"execution_allowed": False},
            supporting_insight_ids=["insight.education_only"],
        )

    if len(candidates) < 2:
        _add_action(
            candidates,
            seen,
            action_id="review_budget_weekly",
            priority=60,
            action_type="budget_tracking",
            params={"cadence": "weekly"},
            supporting_insight_ids=[],
        )
        _add_action(
            candidates,
            seen,
            action_id="refresh_data_2w",
            priority=65,
            action_type="refresh_data",
            params={"cadence": "2w"},
            supporting_insight_ids=[],
        )

    if str(intent or "") == "invest":
        _add_action(
            candidates,
            seen,
            action_id="education_only_guard",
            priority=5,
            action_type="compliance",
            params={"execution_allowed": False},
            supporting_insight_ids=["insight.education_only"] if "insight.education_only" in insight_ids else [],
        )

    candidates.sort(key=lambda item: (item.priority, item.action_id))
    return candidates


def build_advisory_context(
    *,
    evidence_pack: EvidencePackV1,
    policy_version: str,
) -> tuple[AdvisoryContextV1, list[str]]:
    insights = build_insights_from_facts(
        intent=evidence_pack.intent,
        facts=evidence_pack.facts,
        policy_flags=evidence_pack.policy_flags,
    )
    actions = build_action_candidates(
        intent=evidence_pack.intent,
        insights=insights,
        policy_flags=evidence_pack.policy_flags,
    )

    reason_codes: list[str] = []
    if not insights:
        reason_codes.append("insights_empty")
    if not actions:
        reason_codes.append("action_candidates_empty")

    policy_flags = dict(evidence_pack.policy_flags)
    policy_flags["policy_version"] = policy_version
    context = AdvisoryContextV1(
        intent=evidence_pack.intent,
        language=evidence_pack.language,
        facts=evidence_pack.facts,
        insights=insights,
        actions=actions,
        citations=evidence_pack.citations,
        policy_flags=policy_flags,
    )
    return context, reason_codes
