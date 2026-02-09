from __future__ import annotations

from typing import Dict

from .contracts import FactV1, InsightV1
from .normalize import safe_float

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _find_first(facts: list[FactV1], prefix: str) -> FactV1 | None:
    for fact in facts:
        if fact.fact_id.startswith(prefix):
            return fact
    return None


def _find_exact(facts: list[FactV1], fact_id: str) -> FactV1 | None:
    for fact in facts:
        if fact.fact_id == fact_id:
            return fact
    return None


def _add_insight(
    insights: list[InsightV1],
    seen: set[str],
    *,
    insight_id: str,
    kind: str,
    severity: str,
    message_seed: str,
    supporting_fact_ids: list[str],
) -> None:
    if insight_id in seen:
        return
    seen.add(insight_id)
    insights.append(
        InsightV1(
            insight_id=insight_id,
            kind=kind,
            severity=severity,
            message_seed=message_seed,
            supporting_fact_ids=[item for item in supporting_fact_ids if item],
        )
    )


def build_insights_from_facts(
    *,
    intent: str,
    facts: list[FactV1],
    policy_flags: Dict[str, object] | None = None,
) -> list[InsightV1]:
    insights: list[InsightV1] = []
    seen: set[str] = set()

    net_fact = _find_first(facts, "spend.net_cashflow.")
    runway_fact = _find_first(facts, "risk.runway_months.")
    anomaly_count_fact = _find_first(facts, "anomaly.flags_count.")
    volatility_fact = _find_first(facts, "risk.cashflow_volatility.")
    overspend_fact = _find_first(facts, "risk.overspend_propensity.")
    goal_gap_fact = _find_first(facts, "goal.gap_amount")
    goal_feasible_fact = _find_first(facts, "goal.feasible")
    jar_ratio_fact = _find_first(facts, "jar.top.ratio")
    scenario_delta_fact = _find_first(facts, "scenario.best_variant.delta")
    scenario_best_variant_fact = _find_first(facts, "scenario.best_variant.name")
    service_savings_fact = _find_exact(facts, "kb.service_category.savings_deposit")
    service_loan_fact = _find_exact(facts, "kb.service_category.loans_credit")
    service_cards_fact = _find_exact(facts, "kb.service_category.cards_payments")
    service_playbook_fact = _find_exact(facts, "kb.service_category.service_playbook")
    risk_appetite_fact = _find_exact(facts, "slot.risk_appetite")

    net_value = safe_float(net_fact.value if net_fact else 0.0)
    runway_value = safe_float(runway_fact.value if runway_fact else 0.0)
    anomaly_count = safe_float(anomaly_count_fact.value if anomaly_count_fact else 0.0)
    volatility_value = safe_float(volatility_fact.value if volatility_fact else 0.0)
    overspend_value = safe_float(overspend_fact.value if overspend_fact else 0.0)
    goal_gap_value = safe_float(goal_gap_fact.value if goal_gap_fact else 0.0)
    scenario_delta_value = safe_float(scenario_delta_fact.value if scenario_delta_fact else 0.0)
    risk_appetite = str((policy_flags or {}).get("risk_appetite") or "").strip().lower()
    if risk_appetite not in {"conservative", "moderate", "aggressive"} and risk_appetite_fact is not None:
        risk_appetite = str(risk_appetite_fact.value or "").strip().lower()
    if risk_appetite not in {"conservative", "moderate", "aggressive"}:
        risk_appetite = "unknown"

    if net_fact and net_value < 0 and runway_fact and 0 < runway_value < 3:
        _add_insight(
            insights,
            seen,
            insight_id="insight.cashflow_pressure",
            kind="cashflow",
            severity="high",
            message_seed="DÃ²ng tiá»n rÃ²ng Ã¢m vÃ  runway dá»± phÃ²ng tháº¥p.",
            supporting_fact_ids=[net_fact.fact_id, runway_fact.fact_id],
        )
    elif net_fact and net_value < 0:
        _add_insight(
            insights,
            seen,
            insight_id="insight.cashflow_negative",
            kind="cashflow",
            severity="high",
            message_seed="DÃ²ng tiá»n rÃ²ng Ä‘ang Ã¢m.",
            supporting_fact_ids=[net_fact.fact_id],
        )
    elif net_fact and net_value > 0:
        _add_insight(
            insights,
            seen,
            insight_id="insight.savings_capacity",
            kind="planning",
            severity="medium",
            message_seed="DÃ²ng tiá»n rÃ²ng dÆ°Æ¡ng cho tháº¥y cÃ²n dÆ° Ä‘á»‹a Ä‘á»ƒ tiáº¿t kiá»‡m.",
            supporting_fact_ids=[net_fact.fact_id],
        )

    anomaly_support: list[str] = []
    if anomaly_count_fact and anomaly_count >= 1:
        anomaly_support.append(anomaly_count_fact.fact_id)
    if volatility_fact and abs(volatility_value) >= 0.35:
        anomaly_support.append(volatility_fact.fact_id)
    if overspend_fact and abs(overspend_value) >= 0.30:
        anomaly_support.append(overspend_fact.fact_id)
    if anomaly_support:
        _add_insight(
            insights,
            seen,
            insight_id="insight.spend_anomaly",
            kind="risk",
            severity="high" if anomaly_count >= 2 else "medium",
            message_seed="PhÃ¡t hiá»‡n dáº¥u hiá»‡u biáº¿n Ä‘á»™ng chi tiÃªu báº¥t thÆ°á»ng.",
            supporting_fact_ids=anomaly_support,
        )

    if goal_feasible_fact and str(goal_feasible_fact.value_text).strip().lower() in {"chua kha thi", "false"}:
        support = [goal_feasible_fact.fact_id]
        if goal_gap_fact:
            support.append(goal_gap_fact.fact_id)
        _add_insight(
            insights,
            seen,
            insight_id="insight.goal_gap",
            kind="planning",
            severity="high",
            message_seed="Má»¥c tiÃªu hiá»‡n táº¡i chÆ°a kháº£ thi vá»›i thÃ´ng sá»‘ hiá»‡n cÃ³.",
            supporting_fact_ids=support,
        )
    elif goal_gap_fact and goal_gap_value > 0:
        _add_insight(
            insights,
            seen,
            insight_id="insight.goal_gap",
            kind="planning",
            severity="medium",
            message_seed="CÃ²n khoáº£ng thiáº¿u Ä‘á»ƒ Ä‘áº¡t má»¥c tiÃªu tÃ i chÃ­nh.",
            supporting_fact_ids=[goal_gap_fact.fact_id],
        )

    if scenario_delta_fact and scenario_delta_value > 0:
        _add_insight(
            insights,
            seen,
            insight_id="insight.scenario_upside",
            kind="scenario",
            severity="medium",
            message_seed="Ká»‹ch báº£n tá»‘i Æ°u cho tháº¥y delta dÆ°Æ¡ng so vá»›i cÆ¡ sá»Ÿ.",
            supporting_fact_ids=[scenario_delta_fact.fact_id],
        )
    elif scenario_best_variant_fact:
        support = [scenario_best_variant_fact.fact_id]
        if scenario_delta_fact:
            support.append(scenario_delta_fact.fact_id)
        _add_insight(
            insights,
            seen,
            insight_id="insight.scenario_no_upside",
            kind="scenario",
            severity="high",
            message_seed="Kich ban hien tai chua tao upside ro rang so voi co so.",
            supporting_fact_ids=support,
        )

    if jar_ratio_fact:
        _add_insight(
            insights,
            seen,
            insight_id="insight.jar_focus",
            kind="planning",
            severity="low",
            message_seed="CÃ³ thÃ´ng tin nhÃ³m phÃ¢n bá»• chi tiÃªu Æ°u tiÃªn Ä‘á»ƒ tá»‘i Æ°u ngÃ¢n sÃ¡ch.",
            supporting_fact_ids=[jar_ratio_fact.fact_id],
        )

    risk_support = [risk_appetite_fact.fact_id] if risk_appetite_fact is not None else []
    if risk_appetite == "conservative":
        _add_insight(
            insights,
            seen,
            insight_id="insight.risk_preference_conservative",
            kind="profile",
            severity="medium",
            message_seed="Nguoi dung uu tien an toan va on dinh dong tien.",
            supporting_fact_ids=risk_support,
        )
    elif risk_appetite == "moderate":
        _add_insight(
            insights,
            seen,
            insight_id="insight.risk_preference_moderate",
            kind="profile",
            severity="low",
            message_seed="Nguoi dung uu tien can bang giua an toan va toc do dat muc tieu.",
            supporting_fact_ids=risk_support,
        )
    elif risk_appetite == "aggressive":
        _add_insight(
            insights,
            seen,
            insight_id="insight.risk_preference_aggressive",
            kind="profile",
            severity="low",
            message_seed="Nguoi dung chap nhan rui ro cao hon de toi uu muc tieu tai chinh.",
            supporting_fact_ids=risk_support,
        )
    elif str(intent or "") in {"planning", "scenario", "invest"}:
        _add_insight(
            insights,
            seen,
            insight_id="insight.risk_preference_unknown",
            kind="profile",
            severity="medium",
            message_seed="Chua co thong tin khau vi rui ro, can hoi them de ca nhan hoa khuyen nghi.",
            supporting_fact_ids=risk_support,
        )

    service_catalog_support: list[str] = []
    for fact in [service_savings_fact, service_loan_fact, service_cards_fact, service_playbook_fact]:
        if fact is not None:
            service_catalog_support.append(fact.fact_id)
    if service_catalog_support:
        _add_insight(
            insights,
            seen,
            insight_id="insight.service_catalog_available",
            kind="service",
            severity="low",
            message_seed="Co du lieu kho dich vu ngan hang de de xuat theo tinh huong.",
            supporting_fact_ids=service_catalog_support,
        )

    if service_savings_fact and (net_value > 0 or str(intent or "") in {"planning", "scenario"}):
        support = [service_savings_fact.fact_id]
        if net_fact and net_value > 0:
            support.append(net_fact.fact_id)
        _add_insight(
            insights,
            seen,
            insight_id="insight.service_savings_option",
            kind="service",
            severity="medium",
            message_seed="Co the can nhac goi tiet kiem dinh ky hoac tiet kiem ky han de tang ky luat tich luy.",
            supporting_fact_ids=support,
        )

    if service_loan_fact and (net_value < 0 or goal_gap_value > 0 or overspend_value >= 0.30):
        support = [service_loan_fact.fact_id]
        if net_fact and net_value < 0:
            support.append(net_fact.fact_id)
        if goal_gap_fact and goal_gap_value > 0:
            support.append(goal_gap_fact.fact_id)
        _add_insight(
            insights,
            seen,
            insight_id="insight.service_loan_support",
            kind="service",
            severity="medium",
            message_seed="Nen danh gia goi vay tai co cau no hoac khoan vay muc tieu de giam ap luc dong tien.",
            supporting_fact_ids=support,
        )

    if service_cards_fact and (anomaly_support or net_value < 0 or overspend_value >= 0.30):
        support = [service_cards_fact.fact_id]
        support.extend(anomaly_support)
        if overspend_fact and overspend_value >= 0.30:
            support.append(overspend_fact.fact_id)
        _add_insight(
            insights,
            seen,
            insight_id="insight.service_spend_control",
            kind="service",
            severity="medium",
            message_seed="Nen bat han muc chi the va canh bao giao dich de kiem soat nhom chi lon.",
            supporting_fact_ids=support,
        )

    if str(intent or "") == "invest" or bool((policy_flags or {}).get("education_only")):
        _add_insight(
            insights,
            seen,
            insight_id="insight.education_only",
            kind="compliance",
            severity="high",
            message_seed="Ná»™i dung tÆ° váº¥n giá»›i háº¡n trong giÃ¡o dá»¥c tÃ i chÃ­nh, khÃ´ng hÆ°á»›ng dáº«n giao dá»‹ch.",
            supporting_fact_ids=[],
        )

    insights.sort(key=lambda item: (_SEVERITY_ORDER.get(item.severity, 99), item.insight_id))
    return insights

