from __future__ import annotations

import re

from .contracts import AdvisoryContextV1, AnswerPlanV2

_FACT_PLACEHOLDER_PATTERN = re.compile(r"\[F:([a-zA-Z0-9._-]+)\]")


def _fact_index(advisory_context: AdvisoryContextV1) -> dict[str, object]:
    return {fact.fact_id: fact for fact in advisory_context.facts}


def _bind_fact_placeholders(text: str, facts: dict[str, object]) -> str:
    def _replace(match: re.Match[str]) -> str:
        fact_id = str(match.group(1) or "").strip()
        fact = facts.get(fact_id)
        if fact is None:
            return "n/a"
        value_text = str(getattr(fact, "value_text", "") or "").strip()
        return value_text or "n/a"

    return _FACT_PLACEHOLDER_PATTERN.sub(_replace, str(text or ""))


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _find_fact_by_prefix(advisory_context: AdvisoryContextV1, prefix: str) -> object | None:
    for fact in advisory_context.facts:
        if fact.fact_id.startswith(prefix):
            return fact
    return None


def _risk_appetite_from_context(advisory_context: AdvisoryContextV1) -> str:
    policy_risk = str((advisory_context.policy_flags or {}).get("risk_appetite") or "").strip().lower()
    if policy_risk in {"conservative", "moderate", "aggressive"}:
        return policy_risk
    for fact in advisory_context.facts:
        if fact.fact_id != "slot.risk_appetite":
            continue
        risk = str(getattr(fact, "value", "") or "").strip().lower()
        if risk in {"conservative", "moderate", "aggressive"}:
            return risk
    return "unknown"


def _service_suggestions(advisory_context: AdvisoryContextV1, *, vi: bool) -> list[str]:
    fact_ids = {fact.fact_id for fact in advisory_context.facts}
    net_fact = _find_fact_by_prefix(advisory_context, "spend.net_cashflow.")
    goal_gap_fact = _find_fact_by_prefix(advisory_context, "goal.gap_amount")
    anomaly_fact = _find_fact_by_prefix(advisory_context, "anomaly.flags_count.")
    overspend_fact = _find_fact_by_prefix(advisory_context, "risk.overspend_propensity.")
    risk_appetite = _risk_appetite_from_context(advisory_context)

    net_value = _safe_float(getattr(net_fact, "value", 0.0) if net_fact is not None else 0.0)
    goal_gap_value = _safe_float(getattr(goal_gap_fact, "value", 0.0) if goal_gap_fact is not None else 0.0)
    anomaly_count = _safe_float(getattr(anomaly_fact, "value", 0.0) if anomaly_fact is not None else 0.0)
    overspend_value = _safe_float(getattr(overspend_fact, "value", 0.0) if overspend_fact is not None else 0.0)

    suggestions: list[str] = []
    if "kb.service_category.savings_deposit" in fact_ids and (net_value >= 0 or risk_appetite == "conservative"):
        suggestions.append(
            "Cân nhắc gói tiết kiệm định kỳ hoặc tiết kiệm kỳ hạn để giữ kỷ luật tích lũy."
            if vi
            else "Consider recurring or term-deposit savings to keep savings discipline."
        )
    if "kb.service_category.loans_credit" in fact_ids and (net_value < 0 or goal_gap_value > 0):
        suggestions.append(
            "Đặt lịch tư vấn vay/tái cơ cấu nợ để giảm áp lực dòng tiền ngắn hạn."
            if vi
            else "Book a loan/debt-restructure consultation to reduce short-term cashflow pressure."
        )
    if "kb.service_category.cards_payments" in fact_ids and (anomaly_count >= 1 or overspend_value >= 0.30):
        suggestions.append(
            "Bật hạn mức chi thẻ và cảnh báo giao dịch để kiểm soát nhóm chi lớn."
            if vi
            else "Enable card spend caps and alerts to control large spending buckets."
        )
    if risk_appetite == "aggressive" and "kb.service_category.loans_credit" in fact_ids and net_value < 0:
        suggestions.append(
            "Nếu chấp nhận rủi ro cao hơn, có thể xem gói tín dụng linh hoạt nhưng cần giới hạn trả nợ rõ ràng."
            if vi
            else "If you accept higher risk, evaluate flexible credit with strict repayment guardrails."
        )
    if not suggestions and "kb.service_category.count" in fact_ids:
        suggestions.append(
            "Đặt lịch tư vấn để chọn gói dịch vụ ngân hàng phù hợp mục tiêu hiện tại."
            if vi
            else "Book a service consultation to map suitable banking products to your current goal."
        )
    return suggestions[:2]


def render_answer_plan(answer_plan: AnswerPlanV2, advisory_context: AdvisoryContextV1) -> str:
    facts = _fact_index(advisory_context)
    vi = answer_plan.language == "vi"
    lines: list[str] = []

    lines.append("**Kết Luận Chính**" if vi else "**Executive Summary**")
    for item in answer_plan.summary_lines:
        lines.append(f"- {_bind_fact_placeholders(item, facts)}")

    lines.append("")
    lines.append("**Số Liệu Trọng Yếu**" if vi else "**Key Metrics**")
    if answer_plan.key_metrics:
        for metric in answer_plan.key_metrics:
            fact = facts.get(metric.fact_id)
            metric_label = metric.label.strip() if metric.label else ""
            if fact is None:
                label = metric_label or metric.fact_id
                lines.append(f"- {label}: n/a")
                continue
            label = metric_label or getattr(fact, "label", metric.fact_id)
            value_text = str(getattr(fact, "value_text", "n/a"))
            timeframe = str(getattr(fact, "timeframe", "") or "").strip()
            timeframe_text = f" ({timeframe})" if timeframe else ""
            lines.append(f"- {label}: {value_text}{timeframe_text}")
    else:
        lines.append("- n/a")

    lines.append("")
    lines.append("**Khuyến Nghị Tư Vấn**" if vi else "**Advisory Actions**")
    for idx, item in enumerate(answer_plan.actions, start=1):
        lines.append(f"{idx}. {_bind_fact_placeholders(item, facts)}")

    lines.append("")
    lines.append("**Giả Định Và Giới Hạn Dữ Liệu**" if vi else "**Assumptions & Limits**")
    if answer_plan.assumptions:
        for item in answer_plan.assumptions:
            text = _bind_fact_placeholders(item, facts)
            lines.append(f"- Giả định: {text}" if vi else f"- Assumption: {text}")
    if answer_plan.limitations:
        for item in answer_plan.limitations:
            text = _bind_fact_placeholders(item, facts)
            lines.append(f"- Giới hạn: {text}" if vi else f"- Limitation: {text}")
    if not answer_plan.assumptions and not answer_plan.limitations:
        lines.append("- n/a")

    lines.append("")
    lines.append("**Disclaimer**")
    lines.append(f"- {answer_plan.disclaimer}")
    return "\n".join(lines)


def render_facts_only_compact_response(
    advisory_context: AdvisoryContextV1,
    *,
    language: str,
    disclaimer: str,
) -> str:
    vi = language == "vi"
    lines: list[str] = []
    lines.append("**Tóm Tắt Nhanh**" if vi else "**Quick Summary**")
    if advisory_context.facts:
        top = advisory_context.facts[:4]
        for fact in top:
            lines.append(f"- {fact.label}: {fact.value_text}")
    else:
        lines.append("- Chưa đủ dữ liệu để đưa ra kết luận đáng tin cậy." if vi else "- Not enough data for a reliable conclusion.")
        lines.append("- Vui lòng đồng bộ thêm giao dịch và hỏi lại." if vi else "- Please sync more transactions and retry.")
        lines.append("- Hệ thống đang dùng chế độ an toàn để tránh suy diễn sai." if vi else "- The system is using safe fallback mode.")

    lines.append("")
    lines.append("**Số Liệu Trọng Yếu**" if vi else "**Key Metrics**")
    if advisory_context.facts:
        for fact in advisory_context.facts[:5]:
            timeframe = f" ({fact.timeframe})" if fact.timeframe else ""
            lines.append(f"- {fact.label}: {fact.value_text}{timeframe}")
    else:
        lines.append("- n/a")

    lines.append("")
    lines.append("**Khuyến Nghị Tư Vấn**" if vi else "**Advisory Actions**")
    actions: list[str] = [
        (
            "Chốt một mục tiêu 30 ngày (an toàn dòng tiền, trả nợ, hoặc tích lũy)."
            if vi
            else "Lock one 30-day priority (cashflow safety, debt control, or savings)."
        ),
        (
            "Đặt hạn mức cho nhóm chi tiêu lớn nhất và theo dõi theo tuần."
            if vi
            else "Set a cap for the largest spending bucket and review weekly."
        ),
        (
            "Rà soát lại sau 14 ngày để cập nhật khuyến nghị."
            if vi
            else "Reassess in 14 days for an updated recommendation."
        ),
    ]
    risk_appetite = _risk_appetite_from_context(advisory_context)
    if risk_appetite == "unknown" and advisory_context.intent in {"planning", "scenario", "invest"}:
        actions.insert(
            0,
            (
                "Bạn ưu tiên khẩu vị rủi ro nào: thấp, vừa hay cao? Mình sẽ tinh chỉnh khuyến nghị ngay sau khi bạn chọn."
                if vi
                else "Which risk appetite fits you best: low, medium, or high? I will refine guidance after your choice."
            ),
        )

    service_actions = _service_suggestions(advisory_context, vi=vi)
    if service_actions:
        actions = [actions[0], service_actions[0], actions[1]]
        if len(service_actions) > 1:
            actions.append(service_actions[1])
    for idx, item in enumerate(actions[:4], start=1):
        lines.append(f"{idx}. {item}")

    lines.append("")
    lines.append("**Giả Định Và Giới Hạn Dữ Liệu**" if vi else "**Assumptions & Limits**")
    lines.append("- Giả định: dữ liệu từ tool là hợp lệ." if vi else "- Assumption: tool outputs are valid.")
    lines.append(
        "- Giới hạn: chế độ fallback chưa thể tạo lập luận dài và cá nhân hóa sâu."
        if vi
        else "- Limitation: fallback mode omits richer narrative and personalization."
    )

    lines.append("")
    lines.append("**Disclaimer**")
    lines.append(f"- {disclaimer}")
    return "\n".join(lines)


def render_facts_only_response(
    advisory_context: AdvisoryContextV1,
    *,
    language: str,
    disclaimer: str,
) -> str:
    return render_facts_only_compact_response(
        advisory_context,
        language=language,
        disclaimer=disclaimer,
    )
