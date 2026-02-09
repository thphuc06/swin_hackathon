from __future__ import annotations

from .contracts import ClarifyingQuestionV1, IntentExtractionV1


def build_clarifying_question(
    extraction: IntentExtractionV1,
    reason_codes: list[str],
    *,
    max_questions: int = 2,
) -> ClarifyingQuestionV1:
    reasons = set(reason_codes)
    top_intents = [item.intent for item in extraction.top2]

    if "scenario_horizon_missing" in reasons:
        return ClarifyingQuestionV1(
            question_id="scenario_horizon",
            question_text="Bạn muốn phân tích kịch bản trong khoảng thời gian nào?",
            options=["3 tháng", "6 tháng", "12 tháng"],
            max_questions=max_questions,
        )

    if "scenario_delta_missing" in reasons:
        return ClarifyingQuestionV1(
            question_id="scenario_delta_dimension",
            question_text="Bạn muốn thay đổi biến nào trong kịch bản?",
            options=["Thu nhập", "Chi tiêu", "Cả hai"],
            max_questions=max_questions,
        )

    if {"planning", "scenario"} == set(top_intents):
        return ClarifyingQuestionV1(
            question_id="planning_vs_scenario",
            question_text="Bạn đang muốn lập kế hoạch tiết kiệm hay so sánh kịch bản what-if?",
            options=["Lập kế hoạch tiết kiệm", "So sánh kịch bản what-if"],
            max_questions=max_questions,
        )

    if {"summary", "risk"} == set(top_intents):
        return ClarifyingQuestionV1(
            question_id="summary_vs_risk",
            question_text="Bạn muốn xem tổng quan dòng tiền hay cảnh báo rủi ro?",
            options=["Tổng quan dòng tiền", "Cảnh báo rủi ro"],
            max_questions=max_questions,
        )

    return ClarifyingQuestionV1(
        question_id="generic_intent",
        question_text="Để tư vấn chính xác, bạn vui lòng chọn mục tiêu chính:",
        options=["Tổng quan dòng tiền", "Kế hoạch tiết kiệm", "Phân tích kịch bản"],
        max_questions=max_questions,
    )
