from __future__ import annotations

import re
from typing import Any, Dict

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


def _extract_service_matches_from_facts(facts: list[FactV1]) -> list[dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for fact in facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        match = re.match(
            r"^service\.match\.(\d+)\.(id|family|title|score|disclosure_refs|policy_reason_codes|matched_signals)$",
            fact_id,
        )
        if not match:
            continue
        rank = int(match.group(1))
        key = match.group(2)
        row = rows.setdefault(rank, {"rank": rank})
        raw = getattr(fact, "value", None)
        if key in {"id", "family", "title"}:
            row[key] = str(raw or "").strip()
        elif key == "score":
            row[key] = safe_float(raw, 0.0)
        elif key in {"disclosure_refs", "policy_reason_codes", "matched_signals"}:
            if isinstance(raw, list):
                row[key] = [str(item).strip() for item in raw if str(item).strip()]
            else:
                row[key] = []
    return [rows[idx] for idx in sorted(rows) if rows[idx].get("id")]


def _extract_service_signals_from_facts(facts: list[FactV1]) -> set[str]:
    signals: set[str] = set()
    for fact in facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        if not fact_id.startswith("service.signal.") or fact_id.endswith(".sources") or fact_id.endswith(".meta"):
            continue
        if fact_id == "service.signal.count":
            continue
        signal = fact_id.replace("service.signal.", "", 1).strip().lower()
        if signal:
            signals.add(signal)
    return signals


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
    anomaly_latest_date_fact = _find_first(facts, "anomaly.latest_change_point.")
    volatility_fact = _find_first(facts, "risk.cashflow_volatility.")
    overspend_fact = _find_first(facts, "risk.overspend_propensity.")
    goal_gap_fact = _find_first(facts, "goal.gap_amount")
    goal_feasible_fact = _find_first(facts, "goal.feasible")
    goal_status_fact = _find_exact(facts, "goal.status")
    jar_ratio_fact = _find_first(facts, "jar.top.ratio")
    jar_status_fact = _find_exact(facts, "jar.status")
    scenario_delta_fact = _find_first(facts, "scenario.best_variant.delta")
    scenario_best_variant_fact = _find_first(facts, "scenario.best_variant.name")
    service_match_rows = _extract_service_matches_from_facts(facts)
    service_match_meta_fact = _find_exact(facts, "service.match.meta")
    service_savings_fact = _find_exact(facts, "kb.service_category.savings_deposit")
    service_loan_fact = _find_exact(facts, "kb.service_category.loans_credit")
    service_cards_fact = _find_exact(facts, "kb.service_category.cards_payments")
    service_playbook_fact = _find_exact(facts, "kb.service_category.service_playbook")
    risk_appetite_fact = _find_exact(facts, "slot.risk_appetite")
    service_signals = _extract_service_signals_from_facts(facts)

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
        if "risk_conservative" in service_signals:
            risk_appetite = "conservative"
        elif "risk_moderate" in service_signals:
            risk_appetite = "moderate"
        elif "risk_aggressive" in service_signals:
            risk_appetite = "aggressive"
    if risk_appetite not in {"conservative", "moderate", "aggressive"}:
        risk_appetite = "unknown"

    if "cashflow_negative" in service_signals and "runway_low" in service_signals and net_fact and runway_fact:
        _add_insight(
            insights,
            seen,
            insight_id="insight.cashflow_pressure",
            kind="cashflow",
            severity="high",
            message_seed="DÃ²ng tiá»n rÃ²ng Ã¢m vÃ  runway dá»± phÃ²ng tháº¥p.",
            supporting_fact_ids=[net_fact.fact_id, runway_fact.fact_id],
        )
    elif "cashflow_negative" in service_signals and net_fact:
        _add_insight(
            insights,
            seen,
            insight_id="insight.cashflow_negative",
            kind="cashflow",
            severity="high",
            message_seed="DÃ²ng tiá»n rÃ²ng Ä‘ang Ã¢m.",
            supporting_fact_ids=[net_fact.fact_id],
        )
    elif "cashflow_positive" in service_signals and net_fact:
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
    if "anomaly_recent" in service_signals and anomaly_count_fact:
        anomaly_support.append(anomaly_count_fact.fact_id)
    if anomaly_latest_date_fact and str(anomaly_latest_date_fact.value_text).strip():
        anomaly_support.append(anomaly_latest_date_fact.fact_id)
    if "volatility_high" in service_signals and volatility_fact:
        anomaly_support.append(volatility_fact.fact_id)
    if "overspend_high" in service_signals and overspend_fact:
        anomaly_support.append(overspend_fact.fact_id)
    if anomaly_support:
        latest_date = str(anomaly_latest_date_fact.value_text).strip() if anomaly_latest_date_fact else ""
        if latest_date:
            anomaly_seed = f"Phat hien bien dong chi tieu bat thuong, moc gan nhat {latest_date}."
        else:
            anomaly_seed = "Phat hien dau hieu bien dong chi tieu bat thuong."
        _add_insight(
            insights,
            seen,
            insight_id="insight.spend_anomaly",
            kind="risk",
            severity="high" if anomaly_count >= 2 else "medium",
            message_seed=anomaly_seed,
            supporting_fact_ids=anomaly_support,
        )

    goal_status_value = str(goal_status_fact.value if goal_status_fact else "").strip().lower()
    if "goal_input_missing" in service_signals or (goal_status_fact and goal_status_value.startswith("insufficient_")):
        _add_insight(
            insights,
            seen,
            insight_id="insight.goal_input_missing",
            kind="planning",
            severity="high",
            message_seed="Thieu thong tin muc tieu de danh gia kha thi, can bo sung so tien muc tieu hoac ky han.",
            supporting_fact_ids=[goal_status_fact.fact_id],
        )

    jar_status_value = str(jar_status_fact.value if jar_status_fact else "").strip().lower()
    if "jar_data_missing" in service_signals or (jar_status_fact and jar_status_value.startswith("insufficient_")):
        _add_insight(
            insights,
            seen,
            insight_id="insight.jar_data_missing",
            kind="planning",
            severity="medium",
            message_seed="Thieu du lieu jar de de xuat phan bo, can hoan tat thiet lap vi ngan sach.",
            supporting_fact_ids=[jar_status_fact.fact_id],
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
    elif ("goal_gap_high" in service_signals and goal_gap_fact) or (goal_gap_fact and goal_gap_value > 0):
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
    dynamic_family_matches: set[str] = set()
    if service_match_rows:
        for row in service_match_rows:
            rank = int(row.get("rank") or 0)
            service_id = str(row.get("id") or "").strip()
            family = str(row.get("family") or "").strip().lower()
            title = str(row.get("title") or service_id or family).strip()
            if not service_id:
                continue
            service_fact_id = f"service.match.{max(1, rank)}.id"
            service_catalog_support.append(service_fact_id)
            dynamic_family_matches.add(family)
            matched_signals = row.get("matched_signals") if isinstance(row.get("matched_signals"), list) else []
            signal_hint = ""
            if matched_signals:
                signal_hint = f" (tin hieu: {', '.join(str(item) for item in matched_signals[:2])})"
            _add_insight(
                insights,
                seen,
                insight_id=f"insight.service_match.{service_id}",
                kind="service",
                severity="medium",
                message_seed=f"Dich vu {title} phu hop voi ngu canh hien tai{signal_hint}.",
                supporting_fact_ids=[service_fact_id],
            )
    else:
        if service_match_meta_fact is not None:
            service_catalog_support.append(service_match_meta_fact.fact_id)
        for fact in [service_savings_fact, service_loan_fact, service_cards_fact, service_playbook_fact]:
            if fact is not None:
                service_catalog_support.append(fact.fact_id)
        if service_savings_fact is not None:
            dynamic_family_matches.add("savings_deposit")
        if service_loan_fact is not None:
            dynamic_family_matches.add("loans_credit")
        if service_cards_fact is not None:
            dynamic_family_matches.add("cards_payments")

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

    has_savings_service = "savings_deposit" in dynamic_family_matches
    has_loan_service = "loans_credit" in dynamic_family_matches
    has_cards_service = "cards_payments" in dynamic_family_matches

    if has_savings_service and (
        "cashflow_positive" in service_signals or net_value > 0 or str(intent or "") in {"planning", "scenario"}
    ):
        support = [item for item in service_catalog_support if item.startswith("service.match.") or item.endswith("savings_deposit")]
        if net_fact and net_value > 0:
            support.append(net_fact.fact_id)
        _add_insight(
            insights,
            seen,
            insight_id="insight.service_savings_option",
            kind="service",
            severity="medium",
            message_seed="Co the can nhac san pham tiet kiem dinh ky hoac tiet kiem ky han de tang ky luat tich luy.",
            supporting_fact_ids=support,
        )

    if has_loan_service and (
        "cashflow_negative" in service_signals
        or "goal_gap_high" in service_signals
        or "overspend_high" in service_signals
        or net_value < 0
        or goal_gap_value > 0
        or overspend_value >= 0.30
    ):
        support = [item for item in service_catalog_support if item.startswith("service.match.") or item.endswith("loans_credit")]
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
            message_seed="Nen danh gia san pham vay tai co cau no hoac khoan vay muc tieu de giam ap luc dong tien.",
            supporting_fact_ids=support,
        )

    if has_cards_service and (
        "anomaly_recent" in service_signals
        or "overspend_high" in service_signals
        or anomaly_support
        or net_value < 0
        or overspend_value >= 0.30
    ):
        support = [item for item in service_catalog_support if item.startswith("service.match.") or item.endswith("cards_payments")]
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
            message_seed="Noi dung tu van gioi han trong giao duc tai chinh, khong huong dan giao dich.",
            supporting_fact_ids=[],
        )

    insights.sort(key=lambda item: (_SEVERITY_ORDER.get(item.severity, 99), item.insight_id))
    return insights

