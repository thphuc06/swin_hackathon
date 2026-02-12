from __future__ import annotations

import os
import re
from typing import Any, Dict

from config import SERVICE_MATCHER_MODE
from .contracts import EvidencePackV1, FactV1, LanguageCode
from .normalize import fmt_money, fmt_pct, fmt_signed_money, safe_float


def _sanitize_timeframe(raw: Any, default: str) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return default
    normalized = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"})
    return normalized or default


def _parse_int_from_value(raw: Any, default: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return default
    match = re.search(r"\d+", text)
    if not match:
        return default
    return int(match.group(0))


def _scenario_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if "scenario_comparison" in raw or "best_variant_by_goal" in raw:
        return raw
    for key in ["payload", "result", "data", "output"]:
        nested = raw.get(key)
        if isinstance(nested, dict) and ("scenario_comparison" in nested or "best_variant_by_goal" in nested):
            return nested
    return raw


def _add_fact(
    facts: list[FactV1],
    *,
    fact_id: str,
    label: str,
    value: Any,
    value_text: str,
    unit: str = "",
    timeframe: str = "",
    source_tool: str,
    source_path: str,
) -> None:
    facts.append(
        FactV1(
            fact_id=fact_id,
            label=label,
            value=value,
            value_text=value_text,
            unit=unit,
            timeframe=timeframe,
            source_tool=source_tool,
            source_path=source_path,
        )
    )


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _service_matcher_mode() -> str:
    return str(os.getenv("SERVICE_MATCHER_MODE") or SERVICE_MATCHER_MODE).strip().lower()


_ANOMALY_FLAG_PRIORITY = {
    "change_point": 0,
    "category_spike": 1,
    "spend_outlier": 2,
    "spend_drift": 3,
    "abnormal_spend": 4,
    "income_drop": 5,
    "low_balance_risk": 6,
}
_ANOMALY_REASON_MAX = 5


def _normalize_anomaly_flags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    for item in raw:
        value = str(item or "").strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _sorted_anomaly_flags(flags: list[str]) -> list[str]:
    return sorted(flags, key=lambda item: (_ANOMALY_FLAG_PRIORITY.get(item, 99), item))


def _extract_anomaly_change_points(anomaly: Dict[str, Any]) -> list[str]:
    external_engines = anomaly.get("external_engines")
    ruptures = external_engines.get("ruptures_pelt") if isinstance(external_engines, dict) else None
    change_points_raw = ruptures.get("change_points") if isinstance(ruptures, dict) else None
    if not isinstance(change_points_raw, list):
        change_points_raw = anomaly.get("change_points")
    if not isinstance(change_points_raw, list):
        change_points_raw = []

    change_points: list[str] = []
    for item in change_points_raw:
        value = str(item or "").strip()
        if value and value not in change_points:
            change_points.append(value)
    return change_points


def _build_anomaly_flag_reason(flag: str, anomaly: Dict[str, Any]) -> str:
    external_engines = anomaly.get("external_engines")
    if not isinstance(external_engines, dict):
        external_engines = {}

    if flag == "change_point":
        change_points = _extract_anomaly_change_points(anomaly)
        if change_points:
            return f"Phát hiện điểm đổi chế độ chi tiêu, mốc gần nhất là {change_points[-1]}."
        return "Phát hiện dấu hiệu đổi chế độ chi tiêu theo chuỗi thời gian."

    if flag == "category_spike":
        category_spikes = anomaly.get("category_spikes")
        if not isinstance(category_spikes, list):
            category_spikes = []
        top_spike = category_spikes[0] if category_spikes and isinstance(category_spikes[0], dict) else {}
        category_name = str(top_spike.get("category_name") or "Unknown")
        delta_share = safe_float(top_spike.get("delta_share"))
        recent_amount = safe_float(top_spike.get("recent_amount"))
        if category_name != "Unknown" or delta_share > 0:
            return (
                f"Danh mục {category_name} tăng tỉ trọng {fmt_pct(delta_share)} "
                f"với mức chi {fmt_money(recent_amount)}."
            )
        return "Có danh mục chi tiêu tăng tỉ trọng bất thường so với nền."

    if flag == "spend_outlier":
        pyod = external_engines.get("pyod_ecod")
        pyod = pyod if isinstance(pyod, dict) else {}
        outlier_prob = safe_float(pyod.get("outlier_probability"))
        if outlier_prob > 0:
            return f"Mẫu chi tiêu gần nhất nằm trong nhóm ngoại lệ với xác suất {fmt_pct(outlier_prob)}."
        return "Mẫu chi tiêu gần nhất được đánh dấu là ngoại lệ."

    if flag == "spend_drift":
        river = external_engines.get("river_adwin")
        river = river if isinstance(river, dict) else {}
        drift_points = river.get("drift_points")
        drift_count = len(drift_points) if isinstance(drift_points, list) else 0
        if drift_count > 0:
            return f"Chuỗi chi tiêu xuất hiện dấu hiệu drift với {drift_count} mốc thay đổi."
        return "Chuỗi chi tiêu xuất hiện dấu hiệu drift so với nền."

    if flag == "abnormal_spend":
        abnormal_spend = anomaly.get("abnormal_spend")
        abnormal_spend = abnormal_spend if isinstance(abnormal_spend, dict) else {}
        z_score = safe_float(abnormal_spend.get("z_score"))
        if z_score > 0:
            return f"Mức chi tiêu 7 ngày gần đây lệch mạnh so với trung vị nền (z={z_score:.2f})."
        return "Mức chi tiêu gần đây lệch đáng kể so với nền lịch sử."

    if flag == "income_drop":
        income_drop = anomaly.get("income_drop")
        income_drop = income_drop if isinstance(income_drop, dict) else {}
        drop_pct = safe_float(income_drop.get("drop_pct"))
        if drop_pct > 0:
            return f"Thu nhập trung bình giảm {fmt_pct(drop_pct)} so với giai đoạn nền."
        return "Thu nhập trung bình giảm đáng kể so với giai đoạn nền."

    if flag == "low_balance_risk":
        low_balance = anomaly.get("low_balance_risk")
        low_balance = low_balance if isinstance(low_balance, dict) else {}
        runway_days = safe_float(low_balance.get("runway_days_estimate"))
        if runway_days > 0:
            return f"Runway ước tính còn {runway_days:.2f} ngày, dưới ngưỡng an toàn 90 ngày."
        return "Runway ước tính dưới ngưỡng an toàn 90 ngày."

    return "Phát hiện tín hiệu bất thường cần theo dõi thêm để đánh giá rủi ro."


def _extract_spend_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    summary = tool_outputs.get("spend_analytics_v1")
    if not isinstance(summary, dict):
        return
    timeframe = _sanitize_timeframe(summary.get("range"), "30d")
    total_income = safe_float(summary.get("total_income"))
    total_spend = safe_float(summary.get("total_spend"))
    net_cashflow = safe_float(summary.get("net_cashflow"), total_income - total_spend)
    _add_fact(
        facts,
        fact_id=f"spend.total_income.{timeframe}",
        label="Tổng thu nhập",
        value=total_income,
        value_text=fmt_money(total_income),
        unit="VND",
        timeframe=timeframe,
        source_tool="spend_analytics_v1",
        source_path="total_income",
    )
    _add_fact(
        facts,
        fact_id=f"spend.total_spend.{timeframe}",
        label="Tổng chi tiêu",
        value=total_spend,
        value_text=fmt_money(total_spend),
        unit="VND",
        timeframe=timeframe,
        source_tool="spend_analytics_v1",
        source_path="total_spend",
    )
    _add_fact(
        facts,
        fact_id=f"spend.net_cashflow.{timeframe}",
        label="Dòng tiền ròng",
        value=net_cashflow,
        value_text=fmt_signed_money(net_cashflow),
        unit="VND",
        timeframe=timeframe,
        source_tool="spend_analytics_v1",
        source_path="net_cashflow",
    )


def _extract_forecast_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    forecast = tool_outputs.get("cashflow_forecast_v1")
    if not isinstance(forecast, dict):
        return
    points = forecast.get("points")
    if not isinstance(points, list):
        points = []
    income_values = [safe_float(point.get("income_estimate")) for point in points if isinstance(point, dict)]
    spend_values = [safe_float(point.get("spend_estimate")) for point in points if isinstance(point, dict)]
    net_values = [safe_float(point.get("p50")) for point in points if isinstance(point, dict)]
    if not points:
        return
    _add_fact(
        facts,
        fact_id="forecast.avg_income.weekly_12",
        label="Thu nhập dự báo trung bình/kỳ",
        value=_avg(income_values),
        value_text=fmt_money(_avg(income_values)),
        unit="VND",
        timeframe="weekly_12",
        source_tool="cashflow_forecast_v1",
        source_path="points[].income_estimate",
    )
    _add_fact(
        facts,
        fact_id="forecast.avg_spend.weekly_12",
        label="Chi tiêu dự báo trung bình/kỳ",
        value=_avg(spend_values),
        value_text=fmt_money(_avg(spend_values)),
        unit="VND",
        timeframe="weekly_12",
        source_tool="cashflow_forecast_v1",
        source_path="points[].spend_estimate",
    )
    _add_fact(
        facts,
        fact_id="forecast.avg_net_p50.weekly_12",
        label="Net P50 dự báo trung bình/kỳ",
        value=_avg(net_values),
        value_text=fmt_signed_money(_avg(net_values)),
        unit="VND",
        timeframe="weekly_12",
        source_tool="cashflow_forecast_v1",
        source_path="points[].p50",
    )


def _extract_risk_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    risk = tool_outputs.get("risk_profile_non_investment_v1")
    if not isinstance(risk, dict):
        return
    risk_band = str(risk.get("risk_band") or "unknown")
    runway = safe_float(risk.get("emergency_runway_months"))
    volatility = safe_float(risk.get("cashflow_volatility"))
    overspend = safe_float(risk.get("overspend_propensity"))
    lookback_days = max(60, min(720, _parse_int_from_value(risk.get("lookback_days"), 180)))
    timeframe = f"{lookback_days}d"
    _add_fact(
        facts,
        fact_id=f"risk.risk_band.{timeframe}",
        label="Mức rủi ro",
        value=risk_band,
        value_text=risk_band,
        timeframe=timeframe,
        source_tool="risk_profile_non_investment_v1",
        source_path="risk_band",
    )
    _add_fact(
        facts,
        fact_id=f"risk.runway_months.{timeframe}",
        label="Runway dự phòng",
        value=runway,
        value_text=f"{runway:.2f}",
        unit="months",
        timeframe=timeframe,
        source_tool="risk_profile_non_investment_v1",
        source_path="emergency_runway_months",
    )
    _add_fact(
        facts,
        fact_id=f"risk.cashflow_volatility.{timeframe}",
        label="Biến động dòng tiền",
        value=volatility,
        value_text=fmt_pct(volatility),
        unit="pct",
        timeframe=timeframe,
        source_tool="risk_profile_non_investment_v1",
        source_path="cashflow_volatility",
    )
    _add_fact(
        facts,
        fact_id=f"risk.overspend_propensity.{timeframe}",
        label="Xác suất vượt chi",
        value=overspend,
        value_text=fmt_pct(overspend),
        unit="pct",
        timeframe=timeframe,
        source_tool="risk_profile_non_investment_v1",
        source_path="overspend_propensity",
    )


def _extract_anomaly_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    anomaly = tool_outputs.get("anomaly_signals_v1")
    if not isinstance(anomaly, dict):
        return
    flags = _normalize_anomaly_flags(anomaly.get("flags"))
    prioritized_flags = _sorted_anomaly_flags(flags)
    lookback_days = max(30, min(365, _parse_int_from_value(anomaly.get("lookback_days"), 90)))
    timeframe = f"{lookback_days}d"
    _add_fact(
        facts,
        fact_id=f"anomaly.flags_count.{timeframe}",
        label="Số cảnh báo bất thường",
        value=len(flags),
        value_text=str(len(flags)),
        timeframe=timeframe,
        source_tool="anomaly_signals_v1",
        source_path="flags",
    )
    if prioritized_flags:
        _add_fact(
            facts,
            fact_id=f"anomaly.top_flag.{timeframe}",
            label="Cảnh báo chính",
            value=str(prioritized_flags[0]),
            value_text=str(prioritized_flags[0]),
            timeframe=timeframe,
            source_tool="anomaly_signals_v1",
            source_path="flags[0]",
        )

    highlight_flags = prioritized_flags[:_ANOMALY_REASON_MAX]
    if highlight_flags:
        _add_fact(
            facts,
            fact_id=f"anomaly.top_flags.{timeframe}",
            label="Cảnh báo nổi bật",
            value=highlight_flags,
            value_text=", ".join(highlight_flags),
            timeframe=timeframe,
            source_tool="anomaly_signals_v1",
            source_path="flags",
        )
    for index, flag in enumerate(highlight_flags, start=1):
        _add_fact(
            facts,
            fact_id=f"anomaly.flag_reason.{index}.{timeframe}",
            label=f"Lý do cảnh báo {index}",
            value=flag,
            value_text=_build_anomaly_flag_reason(flag, anomaly),
            timeframe=timeframe,
            source_tool="anomaly_signals_v1",
            source_path=f"flags::{flag}",
        )

    change_points = _extract_anomaly_change_points(anomaly)

    if change_points:
        _add_fact(
            facts,
            fact_id=f"anomaly.change_points.{timeframe}",
            label="Các mốc ngày biến động chi tiêu",
            value=change_points,
            value_text=", ".join(change_points),
            timeframe=timeframe,
            source_tool="anomaly_signals_v1",
            source_path="external_engines.ruptures_pelt.change_points",
        )
        _add_fact(
            facts,
            fact_id=f"anomaly.latest_change_point.{timeframe}",
            label="Ngày bất thường gần nhất",
            value=change_points[-1],
            value_text=change_points[-1],
            timeframe=timeframe,
            source_tool="anomaly_signals_v1",
            source_path="external_engines.ruptures_pelt.change_points[-1]",
        )


def _extract_goal_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    goal = tool_outputs.get("goal_feasibility_v1")
    if not isinstance(goal, dict):
        return
    status = str(goal.get("status") or "").strip().lower()
    if status.startswith("insufficient_"):
        reason_codes = goal.get("reason_codes")
        if not isinstance(reason_codes, list):
            reason_codes = []
        reason_text = ", ".join(str(code).strip() for code in reason_codes if str(code).strip()) or status
        _add_fact(
            facts,
            fact_id="goal.status",
            label="Trang thai du lieu goal feasibility",
            value=status,
            value_text=status,
            source_tool="goal_feasibility_v1",
            source_path="status",
        )
        _add_fact(
            facts,
            fact_id="goal.reason_codes",
            label="Ly do thieu du lieu goal feasibility",
            value=reason_codes,
            value_text=reason_text,
            source_tool="goal_feasibility_v1",
            source_path="reason_codes",
        )
        return

    target_amount = safe_float(goal.get("target_amount"))
    horizon_months = int(safe_float(goal.get("horizon_months")))
    required_monthly = safe_float(goal.get("required_monthly_saving"))
    feasible = bool(goal.get("feasible"))
    gap_amount = safe_float(goal.get("gap_amount"))

    if target_amount > 0:
        _add_fact(
            facts,
            fact_id="goal.target_amount",
            label="Mục tiêu tiết kiệm",
            value=target_amount,
            value_text=fmt_money(target_amount),
            unit="VND",
            timeframe=f"{max(horizon_months, 0)}m",
            source_tool="goal_feasibility_v1",
            source_path="target_amount",
        )
    if horizon_months > 0:
        _add_fact(
            facts,
            fact_id="goal.horizon_months",
            label="Kỳ hạn mục tiêu",
            value=horizon_months,
            value_text=str(horizon_months),
            unit="months",
            timeframe=f"{horizon_months}m",
            source_tool="goal_feasibility_v1",
            source_path="horizon_months",
        )
    if required_monthly > 0:
        _add_fact(
            facts,
            fact_id="goal.required_monthly_saving",
            label="Tiết kiệm tối thiểu mỗi tháng",
            value=required_monthly,
            value_text=fmt_money(required_monthly),
            unit="VND",
            source_tool="goal_feasibility_v1",
            source_path="required_monthly_saving",
        )
    _add_fact(
        facts,
        fact_id="goal.feasible",
        label="Tính khả thi mục tiêu",
        value=feasible,
        value_text="khả thi" if feasible else "chưa khả thi",
        source_tool="goal_feasibility_v1",
        source_path="feasible",
    )
    if gap_amount > 0:
        _add_fact(
            facts,
            fact_id="goal.gap_amount",
            label="Khoảng thiếu so với mục tiêu",
            value=gap_amount,
            value_text=fmt_money(gap_amount),
            unit="VND",
            source_tool="goal_feasibility_v1",
            source_path="gap_amount",
        )


def _extract_recurring_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    recurring = tool_outputs.get("recurring_cashflow_detect_v1")
    if not isinstance(recurring, dict):
        return
    fixed_cost_ratio = safe_float(recurring.get("fixed_cost_ratio"))
    if fixed_cost_ratio <= 0:
        return
    lookback_months = max(3, min(24, _parse_int_from_value(recurring.get("lookback_months"), 6)))
    timeframe = f"{lookback_months}m"
    _add_fact(
        facts,
        fact_id=f"recurring.fixed_cost_ratio.{timeframe}",
        label="Tỷ lệ chi phí cố định",
        value=fixed_cost_ratio,
        value_text=fmt_pct(fixed_cost_ratio),
        unit="pct",
        timeframe=timeframe,
        source_tool="recurring_cashflow_detect_v1",
        source_path="fixed_cost_ratio",
    )


def _extract_jar_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    allocation = tool_outputs.get("jar_allocation_suggest_v1")
    if not isinstance(allocation, dict):
        return
    status = str(allocation.get("status") or "").strip().lower()
    if status.startswith("insufficient_"):
        reason_codes = allocation.get("reason_codes")
        if not isinstance(reason_codes, list):
            reason_codes = []
        reason_text = ", ".join(str(code).strip() for code in reason_codes if str(code).strip()) or status
        _add_fact(
            facts,
            fact_id="jar.status",
            label="Trang thai du lieu jar allocation",
            value=status,
            value_text=status,
            source_tool="jar_allocation_suggest_v1",
            source_path="status",
        )
        _add_fact(
            facts,
            fact_id="jar.reason_codes",
            label="Ly do thieu du lieu jar allocation",
            value=reason_codes,
            value_text=reason_text,
            source_tool="jar_allocation_suggest_v1",
            source_path="reason_codes",
        )
        return
    rows = allocation.get("allocations")
    if not isinstance(rows, list) or not rows:
        return
    first = rows[0] if isinstance(rows[0], dict) else {}
    if not first:
        return
    jar_name = str(first.get("jar_name") or "Unknown")
    ratio = safe_float(first.get("ratio"))
    amount = safe_float(first.get("amount"))
    _add_fact(
        facts,
        fact_id="jar.top.name",
        label="Nhóm phân bổ ưu tiên",
        value=jar_name,
        value_text=jar_name,
        source_tool="jar_allocation_suggest_v1",
        source_path="allocations[0].jar_name",
    )
    if ratio > 0:
        _add_fact(
            facts,
            fact_id="jar.top.ratio",
            label="Tỷ lệ phân bổ nhóm ưu tiên",
            value=ratio,
            value_text=fmt_pct(ratio),
            unit="pct",
            source_tool="jar_allocation_suggest_v1",
            source_path="allocations[0].ratio",
        )
    if amount > 0:
        _add_fact(
            facts,
            fact_id="jar.top.amount",
            label="Số tiền phân bổ nhóm ưu tiên",
            value=amount,
            value_text=fmt_money(amount),
            unit="VND",
            source_tool="jar_allocation_suggest_v1",
            source_path="allocations[0].amount",
        )


def _extract_scenario_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    raw = tool_outputs.get("what_if_scenario_v1")
    if not isinstance(raw, dict):
        return
    scenario = _scenario_payload(raw)
    base_total = safe_float(scenario.get("base_total_net_p50"))
    best_variant = str(scenario.get("best_variant_by_goal") or "")
    comparisons = scenario.get("scenario_comparison")
    if not isinstance(comparisons, list):
        comparisons = []

    _add_fact(
        facts,
        fact_id="scenario.base_total_net_p50",
        label="Tổng net P50 cơ sở",
        value=base_total,
        value_text=fmt_money(base_total),
        unit="VND",
        source_tool="what_if_scenario_v1",
        source_path="base_total_net_p50",
    )
    if best_variant:
        _add_fact(
            facts,
            fact_id="scenario.best_variant.name",
            label="Kịch bản tốt nhất",
            value=best_variant,
            value_text=best_variant,
            source_tool="what_if_scenario_v1",
            source_path="best_variant_by_goal",
        )
        for row in comparisons:
            if not isinstance(row, dict):
                continue
            if str(row.get("name") or "") != best_variant:
                continue
            delta = safe_float(row.get("delta_vs_base"))
            _add_fact(
                facts,
                fact_id="scenario.best_variant.delta",
                label="Delta kịch bản tốt nhất so với cơ sở",
                value=delta,
                value_text=fmt_signed_money(delta),
                unit="VND",
                source_tool="what_if_scenario_v1",
                source_path="scenario_comparison[].delta_vs_base",
            )
            break


def _extract_guard_facts(tool_outputs: Dict[str, Any], facts: list[FactV1]) -> None:
    guard = tool_outputs.get("suitability_guard_v1")
    if not isinstance(guard, dict):
        return
    allow = bool(guard.get("allow", True))
    decision = str(guard.get("decision") or "allow")
    _add_fact(
        facts,
        fact_id="policy.suitability.allow",
        label="Trạng thái policy cho phép",
        value=allow,
        value_text="allow" if allow else "deny",
        source_tool="suitability_guard_v1",
        source_path="allow",
    )
    _add_fact(
        facts,
        fact_id="policy.suitability.decision",
        label="Quyết định suitability",
        value=decision,
        value_text=decision,
        source_tool="suitability_guard_v1",
        source_path="decision",
    )


def _extract_slot_facts(extraction_slots: Dict[str, Any], facts: list[FactV1]) -> None:
    if not isinstance(extraction_slots, dict):
        return

    target_amount = 0.0
    for key in [
        "target_amount_vnd",
        "target_amount",
        "goal_target_amount",
        "savings_goal_vnd",
        "goal_amount",
        "savings_target_vnd",
    ]:
        parsed = safe_float(extraction_slots.get(key), 0.0)
        if parsed > 0:
            target_amount = parsed
            break
    if target_amount > 0:
        _add_fact(
            facts,
            fact_id="slot.target_amount_vnd",
            label="Mục tiêu số tiền từ yêu cầu",
            value=target_amount,
            value_text=fmt_money(target_amount),
            unit="VND",
            source_tool="intent_extraction",
            source_path="slots.target_amount_vnd",
        )

    horizon = 0
    for key in [
        "horizon_months",
        "goal_horizon_months",
        "time_horizon_months",
        "duration_months",
        "saving_horizon_months",
    ]:
        parsed = int(safe_float(extraction_slots.get(key), 0.0))
        if parsed > 0:
            horizon = parsed
            break
    if horizon > 0:
        _add_fact(
            facts,
            fact_id="slot.horizon_months",
            label="Kỳ hạn từ yêu cầu",
            value=horizon,
            value_text=str(horizon),
            unit="months",
            source_tool="intent_extraction",
            source_path="slots.horizon_months",
        )

    risk_appetite = str(extraction_slots.get("risk_appetite") or "").strip().lower()
    if risk_appetite in {"conservative", "moderate", "aggressive"}:
        risk_label_map = {
            "conservative": "than trong",
            "moderate": "can bang",
            "aggressive": "chap nhan rui ro cao",
        }
        _add_fact(
            facts,
            fact_id="slot.risk_appetite",
            label="Khau vi rui ro tu yeu cau",
            value=risk_appetite,
            value_text=risk_label_map.get(risk_appetite, risk_appetite),
            source_tool="intent_extraction",
            source_path="slots.risk_appetite",
        )

    for key in ["income_delta_pct", "spend_delta_pct"]:
        value = extraction_slots.get(key)
        if value is None:
            continue
        parsed = safe_float(value)
        if abs(parsed) > 1.0:
            parsed = parsed / 100.0
        if parsed == 0:
            continue
        _add_fact(
            facts,
            fact_id=f"slot.{key}",
            label=f"{key} từ yêu cầu",
            value=parsed,
            value_text=fmt_pct(parsed),
            unit="pct",
            source_tool="intent_extraction",
            source_path=f"slots.{key}",
        )

    for key in ["income_delta_amount_vnd", "spend_delta_amount_vnd"]:
        value = safe_float(extraction_slots.get(key), 0.0)
        if value <= 0:
            continue
        _add_fact(
            facts,
            fact_id=f"slot.{key}",
            label=f"{key} từ yêu cầu",
            value=value,
            value_text=fmt_money(value),
            unit="VND",
            source_tool="intent_extraction",
            source_path=f"slots.{key}",
        )


def _extract_citations(kb: Dict[str, Any]) -> list[str]:
    citations: list[str] = []
    if not isinstance(kb, dict):
        return citations
    matches = kb.get("matches")
    if not isinstance(matches, list):
        return citations
    for item in matches:
        if not isinstance(item, dict):
            continue
        cite = str(item.get("citation") or "").strip()
        if cite and cite not in citations:
            citations.append(cite)
    return citations


def _extract_kb_service_facts(kb: Dict[str, Any], facts: list[FactV1]) -> None:
    if not isinstance(kb, dict):
        return
    matches = kb.get("matches")
    if not isinstance(matches, list) or not matches:
        return

    corpus_parts: list[str] = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        for key in ["text", "snippet", "context", "citation"]:
            value = str(item.get(key) or "").strip()
            if value:
                corpus_parts.append(value.lower())
    if not corpus_parts:
        return

    corpus = " ".join(corpus_parts)
    service_patterns: list[tuple[str, str, list[str]]] = [
        (
            "savings_deposit",
            "Savings and deposit service category available",
            ["saving", "tiet kiem", "deposit", "term deposit", "recurring savings", "goal bucket"],
        ),
        (
            "loans_credit",
            "Loan and credit service category available",
            ["loan", "vay", "overdraft", "debt consolidation", "installment"],
        ),
        (
            "cards_payments",
            "Card and payment control service category available",
            ["credit card", "debit card", "auto debit", "payment", "spend cap"],
        ),
        (
            "service_playbook",
            "Service advisory playbook available",
            ["advisory playbook", "service suggestion policy", "mapping guide"],
        ),
    ]

    existing_ids = {fact.fact_id for fact in facts}
    matched = 0
    for suffix, label, terms in service_patterns:
        if not any(term in corpus for term in terms):
            continue
        fact_id = f"kb.service_category.{suffix}"
        if fact_id in existing_ids:
            continue
        _add_fact(
            facts,
            fact_id=fact_id,
            label=label,
            value=True,
            value_text="available",
            source_tool="retrieve_from_aws_kb",
            source_path="matches[].text",
        )
        existing_ids.add(fact_id)
        matched += 1

    if matched > 0 and "kb.service_category.count" not in existing_ids:
        _add_fact(
            facts,
            fact_id="kb.service_category.count",
            label="Number of service categories supported by KB context",
            value=matched,
            value_text=str(matched),
            source_tool="retrieve_from_aws_kb",
            source_path="matches[].text",
        )


def _extract_service_signal_facts(
    *,
    facts: list[FactV1],
    policy_flags: Dict[str, Any],
) -> tuple[list[str], list[str]]:
    reason_codes: list[str] = []
    try:
        from service_signals import extract_service_signals
    except Exception:
        reason_codes.append("service_signals_import_failed")
        return [], reason_codes

    signal_set = extract_service_signals(facts=facts, policy_flags=policy_flags)
    for signal in signal_set.signals:
        source_ids = list(signal_set.source_fact_ids.get(signal, []))
        _add_fact(
            facts,
            fact_id=f"service.signal.{signal}",
            label=f"Service signal: {signal}",
            value=True,
            value_text=signal,
            source_tool="service_signal_layer",
            source_path="facts",
        )
        if source_ids:
            _add_fact(
                facts,
                fact_id=f"service.signal.{signal}.sources",
                label=f"Service signal {signal} source facts",
                value=source_ids,
                value_text=", ".join(source_ids),
                source_tool="service_signal_layer",
                source_path="facts",
            )

    _add_fact(
        facts,
        fact_id="service.signal.count",
        label="Number of service signals",
        value=len(signal_set.signals),
        value_text=str(len(signal_set.signals)),
        source_tool="service_signal_layer",
        source_path="facts",
    )
    _add_fact(
        facts,
        fact_id="service.signal.meta",
        label="Service signal layer metadata",
        value={
            "signals": signal_set.signals,
            "source_fact_ids": signal_set.source_fact_ids,
            "thresholds": signal_set.thresholds,
        },
        value_text=str(len(signal_set.signals)),
        source_tool="service_signal_layer",
        source_path="extract_service_signals",
    )
    return signal_set.signals, reason_codes


def _extract_service_match_facts(
    *,
    intent: str,
    user_prompt: str,
    kb: Dict[str, Any],
    facts: list[FactV1],
    policy_flags: Dict[str, Any],
    service_signals: list[str],
) -> list[str]:
    """Populate service.match.* facts from dynamic service catalog matcher."""
    reason_codes: list[str] = []
    try:
        from service_catalog import match_services
    except Exception:
        reason_codes.append("service_catalog_import_failed")
        return reason_codes

    kb_matches = kb.get("matches") if isinstance(kb, dict) else []
    if not isinstance(kb_matches, list):
        kb_matches = []

    selected, meta = match_services(
        intent=intent,
        user_prompt=user_prompt,
        evidence_facts=facts,
        kb_matches=kb_matches,
        policy_flags=policy_flags,
        service_signals=service_signals,
    )

    for code in meta.get("reason_codes", []):
        text = str(code or "").strip()
        if text:
            reason_codes.append(text)

    # Emit compact matcher metadata as a single fact for audit propagation.
    _add_fact(
        facts,
        fact_id="service.match.meta",
        label="Service matcher metadata",
        value={
            "catalog_version": str(meta.get("catalog_version") or ""),
            "mode": str(meta.get("mode") or ""),
            "signals": list(meta.get("signals", [])),
            "selected": [item.service_id for item in selected],
            "candidates": meta.get("candidates", []),
            "embedding_candidates": meta.get("embedding_candidates", []),
            "filtered_by_policy": meta.get("filtered_by_policy", []),
            "clarification_triggered": bool(meta.get("clarification_triggered")),
            "clarification_options": list(meta.get("clarification_options", [])),
            "margin": float(meta.get("margin") or 0.0),
        },
        value_text=str(len(selected)),
        source_tool="service_catalog_matcher",
        source_path="match_services",
    )

    _add_fact(
        facts,
        fact_id="service.match.count",
        label="Number of matched services",
        value=len(selected),
        value_text=str(len(selected)),
        source_tool="service_catalog_matcher",
        source_path="selected",
    )

    for item in selected:
        rank = max(1, int(getattr(item, "rank", 0) or 0))
        prefix = f"service.match.{rank}"
        _add_fact(
            facts,
            fact_id=f"{prefix}.id",
            label=f"Matched service #{rank} id",
            value=item.service_id,
            value_text=item.service_id,
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].service_id",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.family",
            label=f"Matched service #{rank} family",
            value=item.family,
            value_text=item.family,
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].family",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.title",
            label=f"Matched service #{rank} title",
            value=item.title,
            value_text=item.title,
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].title",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.score",
            label=f"Matched service #{rank} score",
            value=float(item.score),
            value_text=f"{float(item.score):.4f}",
            unit="score",
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].score",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.disclosure_refs",
            label=f"Matched service #{rank} disclosures",
            value=list(item.disclosure_refs),
            value_text=", ".join(item.disclosure_refs) if item.disclosure_refs else "none",
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].disclosure_refs",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.policy_reason_codes",
            label=f"Matched service #{rank} policy reason codes",
            value=list(item.reason_codes),
            value_text=", ".join(item.reason_codes) if item.reason_codes else "ok",
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].reason_codes",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.matched_signals",
            label=f"Matched service #{rank} signals",
            value=list(item.matched_signals),
            value_text=", ".join(item.matched_signals) if item.matched_signals else "none",
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].matched_signals",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.embedding_score",
            label=f"Matched service #{rank} embedding score",
            value=float(getattr(item, "embedding_score", 0.0)),
            value_text=f"{float(getattr(item, 'embedding_score', 0.0)):.4f}",
            unit="score",
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].embedding_score",
        )
        _add_fact(
            facts,
            fact_id=f"{prefix}.margin_to_next",
            label=f"Matched service #{rank} margin to next",
            value=float(getattr(item, "margin_to_next", 0.0)),
            value_text=f"{float(getattr(item, 'margin_to_next', 0.0)):.4f}",
            unit="score",
            source_tool="service_catalog_matcher",
            source_path=f"selected[{rank - 1}].margin_to_next",
        )

    return sorted(set(code for code in reason_codes if code))


def _required_prefixes_for_intent(intent: str) -> list[str]:
    if intent == "summary":
        return ["spend.", "forecast."]
    if intent == "risk":
        return ["risk."]
    if intent == "planning":
        return ["goal.", "spend."]
    if intent == "scenario":
        return ["scenario."]
    if intent == "invest":
        return ["policy."]
    return ["policy."]


def build_evidence_pack(
    *,
    intent: str,
    language: LanguageCode,
    user_prompt: str,
    tool_outputs: Dict[str, Any],
    kb: Dict[str, Any],
    policy_flags: Dict[str, Any],
    extraction_slots: Dict[str, Any] | None = None,
) -> tuple[EvidencePackV1, list[str]]:
    facts: list[FactV1] = []
    reason_codes: list[str] = []
    _extract_spend_facts(tool_outputs, facts)
    _extract_forecast_facts(tool_outputs, facts)
    _extract_risk_facts(tool_outputs, facts)
    _extract_anomaly_facts(tool_outputs, facts)
    _extract_goal_facts(tool_outputs, facts)
    _extract_recurring_facts(tool_outputs, facts)
    _extract_jar_facts(tool_outputs, facts)
    _extract_scenario_facts(tool_outputs, facts)
    _extract_guard_facts(tool_outputs, facts)
    _extract_slot_facts(extraction_slots or {}, facts)
    matcher_mode = _service_matcher_mode()
    if matcher_mode in {"dynamic", "dynamic_v2"}:
        service_signals, signal_reasons = _extract_service_signal_facts(
            facts=facts,
            policy_flags=policy_flags,
        )
        reason_codes.extend(signal_reasons)
        reason_codes.extend(
            _extract_service_match_facts(
                intent=intent,
                user_prompt=user_prompt,
                kb=kb,
                facts=facts,
                policy_flags=policy_flags,
                service_signals=service_signals,
            )
        )
    else:
        _extract_kb_service_facts(kb, facts)

    required_prefixes = _required_prefixes_for_intent(intent)
    if not any(any(fact.fact_id.startswith(prefix) for prefix in required_prefixes) for fact in facts):
        reason_codes.append("insufficient_facts")

    evidence = EvidencePackV1(
        intent=intent or "out_of_scope",
        language=language,
        facts=facts,
        citations=_extract_citations(kb),
        policy_flags=policy_flags,
    )
    return evidence, reason_codes
