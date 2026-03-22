"""
income_engine.py
================
Phân tích income vs monthly spend để gợi ý tiết kiệm.

Không import boto3 hay psycopg2 → test offline hoàn toàn.
"""

from dataclasses import dataclass


@dataclass
class SavingSuggestion:
    should_suggest: bool
    income: float
    monthly_spend: float
    surplus: float
    surplus_pct: float
    suggested_saving_amount: float
    # Notification content
    title: str
    detail: str
    severity: str  # 'low' | 'medium' | 'high'


def analyze_income_vs_spend(
    income: float,
    monthly_spend: float,
    min_surplus_pct: float = 10.0,
) -> SavingSuggestion:
    """
    So sánh income mới với tổng chi tiêu 30 ngày.

    Điều kiện gợi ý tiết kiệm:
      - surplus = income - monthly_spend > 0
      - surplus_pct = surplus / income × 100 >= min_surplus_pct (mặc định 10%)

    Công thức số tiền gợi ý:
      - suggested = 70% × surplus, làm tròn xuống 10,000 VND

    Tại sao 70%? Giữ lại 30% buffer cho chi tiêu phát sinh ngoài kế hoạch.
    Tại sao làm tròn 10k? Số đẹp, dễ chuyển khoản.

    Args:
        income: Số tiền giao dịch credit vừa vào (VND)
        monthly_spend: Tổng debit 30 ngày gần nhất của user (VND)
        min_surplus_pct: Ngưỡng thặng dư tối thiểu để gợi ý (mặc định 10%)

    Returns:
        SavingSuggestion với đầy đủ thông tin để ghi tier1_notifications
    """
    if income <= 0:
        return SavingSuggestion(
            should_suggest=False,
            income=income,
            monthly_spend=monthly_spend,
            surplus=0.0,
            surplus_pct=0.0,
            suggested_saving_amount=0.0,
            title="",
            detail="",
            severity="low",
        )

    surplus = income - monthly_spend
    surplus_pct = float(int((surplus / income) * 10_000) / 100)  # 2 decimal places, no round() overload issue
    should_suggest = surplus > 0 and surplus_pct >= min_surplus_pct

    if should_suggest:
        raw = surplus * 0.7
        suggested = (raw // 10_000) * 10_000  # làm tròn xuống 10k

        # Severity dựa trên mức thặng dư
        if surplus_pct >= 50:
            severity = "high"
        elif surplus_pct >= 25:
            severity = "medium"
        else:
            severity = "low"

        title = "💡 Gợi ý tiết kiệm tháng này"
        detail = (
            f"Thu nhập {income:,.0f} VND vượt chi tiêu 30 ngày "
            f"{monthly_spend:,.0f} VND ({surplus_pct:.0f}% thặng dư). "
            f"Bạn nên để dành thêm {suggested:,.0f} VND."
        )
    else:
        suggested = 0.0
        severity = "low"
        title = ""
        detail = ""

    return SavingSuggestion(
        should_suggest=should_suggest,
        income=income,
        monthly_spend=monthly_spend,
        surplus=surplus,
        surplus_pct=surplus_pct,
        suggested_saving_amount=suggested,
        title=title,
        detail=detail,
        severity=severity,
    )
