from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from config import (
    ENCODING_FAILFAST_SCORE_MIN,
    ENCODING_GATE_ENABLED,
    ENCODING_NORMALIZATION_FORM,
    ENCODING_REPAIR_ENABLED,
    ENCODING_REPAIR_MIN_DELTA,
    ENCODING_REPAIR_SCORE_MIN,
    RESPONSE_MAX_RETRIES,
    RESPONSE_MODE,
    RESPONSE_POLICY_VERSION,
    RESPONSE_PROMPT_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ROUTER_INTENT_CONF_MIN,
    ROUTER_MAX_CLARIFY_QUESTIONS,
    ROUTER_MODE,
    ROUTER_POLICY_VERSION,
    ROUTER_SCENARIO_CONF_MIN,
    ROUTER_TOP2_GAP_MIN,
    TOOL_EXECUTION_TIMEOUT,
)
from encoding import apply_prompt_encoding_gate
from router import (
    RouteDecisionV1,
    build_route_decision,
    extract_intent_with_bedrock,
    suggest_intent_override,
    tool_bundle_for_intent,
)
from response import (
    build_advisory_context,
    build_evidence_pack,
    extract_numeric_tokens_for_grounding,
    render_answer_plan,
    render_facts_only_compact_response,
    synthesize_answer_plan_with_bedrock,
    validate_answer_grounding,
)
from tools import (
    anomaly_signals,
    audit_write,
    cashflow_forecast_tool,
    goal_feasibility_tool,
    jar_allocation_suggest_tool,
    kb_retrieve,
    recurring_cashflow_detect_tool,
    risk_profile_non_investment_tool,
    spend_analytics,
    suitability_guard_tool,
    what_if_scenario_tool,
)

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    user_token: str
    user_id: str
    prompt: str
    intent: str
    scenario_request: Dict[str, Any]
    context: Dict[str, Any]
    kb: Dict[str, Any]
    tool_outputs: Dict[str, Any]
    tool_calls: list[str]
    education_only: bool
    user_profile: Dict[str, Any]
    extraction: Dict[str, Any]
    route_decision: Dict[str, Any]
    clarification: Dict[str, Any]
    encoding_meta: Dict[str, Any]
    evidence_pack: Dict[str, Any]
    advisory_context: Dict[str, Any]
    answer_plan_v2: Dict[str, Any]
    response_meta: Dict[str, Any]
    response: str
    trace_id: str


load_dotenv()
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."


def _normalize_text(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )
    return stripped.lower()


def _resolve_risk_appetite(*, prompt: str, slots: Dict[str, Any]) -> str:
    raw_slot = str((slots or {}).get("risk_appetite") or "").strip().lower()
    if raw_slot in {"conservative", "moderate", "aggressive"}:
        return raw_slot

    normalized = _normalize_text(prompt)
    low_terms = [
        "khau vi rui ro thap",
        "rui ro thap",
        "an toan",
        "bao toan",
        "it rui ro",
        "low risk",
        "conservative",
        "safe",
    ]
    medium_terms = [
        "khau vi rui ro vua",
        "rui ro vua",
        "trung binh",
        "can bang",
        "moderate",
        "medium risk",
        "balanced",
    ]
    high_terms = [
        "khau vi rui ro cao",
        "rui ro cao",
        "chap nhan rui ro cao",
        "mao hiem",
        "high risk",
        "aggressive",
    ]

    if any(term in normalized for term in low_terms):
        return "conservative"
    if any(term in normalized for term in medium_terms):
        return "moderate"
    if any(term in normalized for term in high_terms):
        return "aggressive"
    return "unknown"


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _fmt_money(value: float) -> str:
    rounded = round(_safe_float(value), 2)
    if abs(rounded - round(rounded)) < 0.01:
        return f"{int(round(rounded)):,}"
    return f"{rounded:,.2f}"


def _fmt_signed_money(value: float) -> str:
    amount = _fmt_money(abs(_safe_float(value)))
    sign = "-" if _safe_float(value) < 0 else "+"
    return f"{sign}{amount}"


def _fmt_pct(value: float) -> str:
    ratio = _safe_float(value)
    if ratio > 1.0:
        return f"{ratio:.2f}%"
    return f"{ratio * 100:.2f}%"


def _is_vietnamese_prompt(prompt: str) -> bool:
    normalized = _normalize_text(prompt)
    vi_terms = [
        "toi",
        "chi tieu",
        "dong tien",
        "tiet kiem",
        "tich tien",
        "bao lau",
        "mua nha",
        "mua xe",
        "mua pc",
        "gia su",
        "kich ban",
        "dau tu",
        "thang",
        "ngay",
    ]
    return any(term in normalized for term in vi_terms)


def _parse_number_token(raw: str) -> float:
    token = raw.strip().replace(" ", "")
    if token.count(",") > 0 and token.count(".") == 0:
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return 0.0


def _extract_goal_request(prompt: str) -> Dict[str, Any]:
    normalized = _normalize_text(prompt)
    money_pattern = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ty|ti|billion|bn|trieu|tr|million|m|nghin|ngan|k)?\b")
    scale = {
        "ty": 1_000_000_000.0,
        "ti": 1_000_000_000.0,
        "billion": 1_000_000_000.0,
        "bn": 1_000_000_000.0,
        "trieu": 1_000_000.0,
        "tr": 1_000_000.0,
        "million": 1_000_000.0,
        "m": 1_000_000.0,
        "nghin": 1_000.0,
        "ngan": 1_000.0,
        "k": 1_000.0,
    }

    target_amount: float | None = None
    for match in money_pattern.finditer(normalized):
        base_value = _parse_number_token(match.group(1))
        unit = (match.group(2) or "").strip()
        if unit in scale:
            target_amount = base_value * scale[unit]
            break
        if base_value >= 1_000_000:
            target_amount = base_value
            break

    horizon_months: int | None = None
    month_match = re.search(r"(\d+)\s*(thang|month|months)\b", normalized)
    if month_match:
        horizon_months = max(1, _safe_int(month_match.group(1), 1))
    else:
        year_match = re.search(r"(\d+)\s*(nam|year|years)\b", normalized)
        if year_match:
            horizon_months = max(1, _safe_int(year_match.group(1), 1) * 12)
        else:
            week_match = re.search(r"(\d+)\s*(tuan|week|weeks)\b", normalized)
            if week_match:
                weeks = max(1, _safe_int(week_match.group(1), 1))
                horizon_months = max(1, round(weeks / 4))

    eta_terms = ["bao lau", "how long", "eta", "when can", "mat bao lau"]
    is_eta_question = any(term in normalized for term in eta_terms)
    return {
        "target_amount": target_amount,
        "horizon_months": horizon_months,
        "is_eta_question": is_eta_question,
    }


def _scenario_default_variants() -> list[Dict[str, Any]]:
    return [
        {
            "name": "cut_discretionary_spend_15pct",
            "scenario_overrides": {"spend_delta_pct": -0.15},
        },
        {
            "name": "increase_income_10pct",
            "scenario_overrides": {"income_delta_pct": 0.10},
        },
        {
            "name": "balanced_income_up5_spend_down10",
            "scenario_overrides": {"income_delta_pct": 0.05, "spend_delta_pct": -0.10},
        },
    ]


def _scenario_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if "scenario_comparison" in raw or "best_variant_by_goal" in raw:
        return raw
    for key in ["payload", "result", "data", "output"]:
        nested = raw.get(key)
        if not isinstance(nested, dict):
            continue
        if "scenario_comparison" in nested or "best_variant_by_goal" in nested:
            merged = dict(nested)
            if "base_total_net_p50" not in merged and "base_total_net_p50" in raw:
                merged["base_total_net_p50"] = raw.get("base_total_net_p50")
            return merged
    return raw


def _describe_scenario_overrides(overrides: Dict[str, Any], vietnamese: bool) -> str:
    if not isinstance(overrides, dict) or not overrides:
        return ""

    parts: list[str] = []
    income_delta = _safe_float(overrides.get("income_delta_pct"))
    spend_delta = _safe_float(overrides.get("spend_delta_pct"))
    if abs(income_delta) > 0:
        income_pct = int(round(abs(income_delta) * 100))
        if vietnamese:
            direction = "tang" if income_delta > 0 else "giam"
            parts.append(f"thu nhap {direction} {income_pct}%")
        else:
            direction = "up" if income_delta > 0 else "down"
            parts.append(f"income {direction} {income_pct}%")
    if abs(spend_delta) > 0:
        spend_pct = int(round(abs(spend_delta) * 100))
        if vietnamese:
            direction = "tang" if spend_delta > 0 else "giam"
            parts.append(f"chi tieu {direction} {spend_pct}%")
        else:
            direction = "up" if spend_delta > 0 else "down"
            parts.append(f"spend {direction} {spend_pct}%")

    if not parts:
        return ""
    return ", ".join(parts)


def _bucket_days(requested_days: int) -> int:
    days = max(1, requested_days)
    if days <= 45:
        return 30
    if days <= 75:
        return 60
    return 90


def _resolve_summary_range(prompt: str, intent: str) -> str:
    normalized = _normalize_text(prompt)
    requested_days = 0

    day_match = re.search(r"(\d+)\s*(ngay|day|days|d)\b", normalized)
    if day_match:
        requested_days = _safe_int(day_match.group(1), 0)
    else:
        month_match = re.search(r"(\d+)\s*(thang|month|months)\b", normalized)
        if month_match:
            requested_days = _safe_int(month_match.group(1), 0) * 30

    if requested_days <= 0:
        requested_days = 90 if intent == "risk" else 30

    return f"{_bucket_days(requested_days)}d"


def _build_kb_query(prompt: str, intent: str) -> str:
    base = str(prompt or "").strip()
    intent_key = str(intent or "").strip().lower()
    hints = {
        "summary": "service guidance: savings deposit, card spend control, payment alerts, monthly budgeting support",
        "risk": "service guidance: debt restructuring, emergency buffer savings, card control limits, recurring payment check",
        "planning": "service guidance: recurring savings, term deposit, goal-based saving plan, installment loan options",
        "scenario": "service guidance: contingency cashflow services, spend-cap controls, emergency savings, debt support",
        "invest": "service guidance: education-only alternatives, non-investment savings, budgeting and debt health services",
    }
    hint = hints.get(intent_key)
    if not hint:
        return base
    if not base:
        return hint
    return f"{base}\n{hint}"


def _summary_range_days(summary: Dict[str, Any]) -> int:
    raw = str(summary.get("range") or "30d")
    match = re.search(r"\d+", raw)
    if not match:
        return 30
    return _bucket_days(_safe_int(match.group(0), 30))


def _requested_action(prompt: str) -> str:
    normalized = _normalize_text(prompt)
    recommendation_patterns = [
        (r"\b(co nen|nen|should i|is it a good time to)\s*(mua|buy)\b", "recommend_buy"),
        (r"\b(co nen|nen|should i|is it a good time to)\s*(ban|sell)\b", "recommend_sell"),
    ]
    for pattern, action in recommendation_patterns:
        if re.search(pattern, normalized):
            return action

    execution_patterns = [
        (r"\bdat lenh\b", "execute"),
        (r"\bkhop lenh\b", "execute"),
        (r"\bexecute\b", "execute"),
        (r"\border\b", "order"),
        (r"\btrade\b", "trade"),
        (r"\bbuy\b", "buy"),
        (r"\bmua\b", "buy"),
        (r"\bsell\b", "sell"),
        (r"\bban\b", "sell"),
    ]
    for pattern, action in execution_patterns:
        if re.search(pattern, normalized):
            return action
    return "advice"


_RECOMMENDATION_ACTIONS = {"recommend_buy", "recommend_sell", "recommend_trade"}


def _should_override_recommendation_deny(intent: str, requested_action: str, decision: Dict[str, Any]) -> bool:
    if str(intent or "").strip().lower() != "invest":
        return False
    if str(requested_action or "").strip().lower() not in _RECOMMENDATION_ACTIONS:
        return False
    allow = bool(decision.get("allow", True))
    decision_name = str(decision.get("decision") or "").strip().lower()
    return allow or decision_name in {"allow", "education_only"}


def _top_jar(summary: Dict[str, Any]) -> Dict[str, Any]:
    rows = summary.get("jar_splits") or []
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            return first
    return {}


def _top_merchant(summary: Dict[str, Any]) -> Dict[str, Any]:
    rows = summary.get("top_merchants") or []
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            return first
    return {}


def _forecast_stats(forecast: Dict[str, Any]) -> Dict[str, float]:
    points = forecast.get("points") or []
    if not isinstance(points, list):
        points = []
    income_values = [_safe_float(point.get("income_estimate")) for point in points if isinstance(point, dict)]
    spend_values = [_safe_float(point.get("spend_estimate")) for point in points if isinstance(point, dict)]
    p50_values = [_safe_float(point.get("p50")) for point in points if isinstance(point, dict)]
    return {
        "avg_income": _avg(income_values),
        "avg_spend": _avg(spend_values),
        "avg_p50": _avg(p50_values),
        "count": float(len(points)),
    }


def _build_summary_advice(state: AgentState, vietnamese: bool) -> str:
    summary = state.get("context", {}).get("summary", {})
    forecast = state.get("context", {}).get("forecast", {})
    total_spend = _safe_float(summary.get("total_spend"))
    total_income = _safe_float(summary.get("total_income"))
    net_cashflow = _safe_float(summary.get("net_cashflow"), total_income - total_spend)
    range_days = _summary_range_days(summary)
    top_jar = _top_jar(summary)
    top_merchant = _top_merchant(summary)
    forecast_stats = _forecast_stats(forecast)

    if vietnamese:
        lines = [f"**Tong quan {range_days} ngay**"]
        lines.append(f"- Thu nhap: {_fmt_money(total_income)}")
        lines.append(f"- Chi tieu: {_fmt_money(total_spend)}")
        lines.append(f"- Dong tien rong: {_fmt_signed_money(net_cashflow)}")
        if top_jar:
            lines.append(
                "- Nhom chi lon nhat: "
                f"{top_jar.get('jar_name', 'Unknown')} "
                f"({_fmt_money(_safe_float(top_jar.get('amount')))}, {_fmt_pct(_safe_float(top_jar.get('pct_of_spend')))})."
            )
        if top_merchant:
            lines.append(
                "- Counterparty chi cao nhat: "
                f"{top_merchant.get('merchant', 'UNKNOWN')} "
                f"({_fmt_money(_safe_float(top_merchant.get('amount')))})."
            )
        if forecast_stats["count"] > 0:
            lines.extend(
                [
                    "",
                    "**Du bao 12 tuan (trung binh/tuan)**",
                    f"- Thu: {_fmt_money(forecast_stats['avg_income'])}",
                    f"- Chi: {_fmt_money(forecast_stats['avg_spend'])}",
                    f"- Net: {_fmt_signed_money(forecast_stats['avg_p50'])}",
                ]
            )

        lines.extend(["", "**Nhan dinh tu van**"])
        if net_cashflow < 0:
            lines.append(
                "Ban dang tham hut dong tien. Can giam nhom chi lon nhat va xac minh giao dich bat thuong truoc khi chot ETA tiet kiem."
            )
            lines.extend(
                [
                    "",
                    "**Ke hoach hanh dong 7 ngay**",
                    "1. Cat 10-15% o nhom chi lon nhat (uu tien chi tieu linh hoat).",
                    "2. Ra soat top counterparties de loai bo giao dich khong thiet yeu.",
                    "3. Dat han muc chi theo tuan va theo doi lai sau 2 tuan.",
                ]
            )
        else:
            lines.append("Dong tien dang duong va co the phan bo mot phan sang quy muc tieu.")
            lines.extend(
                [
                    "",
                    "**Ke hoach hanh dong 7 ngay**",
                    "1. Trich toi thieu 20-30% net duong vao quy muc tieu ngay khi co thu nhap.",
                    "2. Giu quy du phong toi thieu 3 thang chi tieu thiet yeu.",
                    "3. Theo doi lai sai lech chi tieu de tinh chinh ke hoach hang thang.",
                ]
            )
        return "\n".join(lines)

    lines = [f"**{range_days}-day Snapshot**"]
    lines.append(f"- Income: {_fmt_money(total_income)}")
    lines.append(f"- Spend: {_fmt_money(total_spend)}")
    lines.append(f"- Net cashflow: {_fmt_signed_money(net_cashflow)}")
    if top_jar:
        lines.append(
            "- Largest spend jar: "
            f"{top_jar.get('jar_name', 'Unknown')} "
            f"({_fmt_money(_safe_float(top_jar.get('amount')))}, {_fmt_pct(_safe_float(top_jar.get('pct_of_spend')))})."
        )
    if top_merchant:
        lines.append(
            "- Top spend counterparty: "
            f"{top_merchant.get('merchant', 'UNKNOWN')} "
            f"({_fmt_money(_safe_float(top_merchant.get('amount')))})."
        )
    if forecast_stats["count"] > 0:
        lines.extend(
            [
                "",
                "**12-Week Forecast (Weekly Avg)**",
                f"- Income: {_fmt_money(forecast_stats['avg_income'])}",
                f"- Spend: {_fmt_money(forecast_stats['avg_spend'])}",
                f"- Net: {_fmt_signed_money(forecast_stats['avg_p50'])}",
            ]
        )
    lines.extend(["", "**Advisor View**"])
    if net_cashflow < 0:
        lines.append("Current cashflow is negative; reduce the largest spend bucket before setting a hard savings ETA.")
        lines.extend(
            [
                "",
                "**Recommended Next 7 Days**",
                "1. Reduce discretionary spending in the largest spend bucket by 10-15%.",
                "2. Audit top counterparties for non-essential payments.",
                "3. Re-baseline weekly spending cap and re-check after 2 weeks.",
            ]
        )
    else:
        lines.append("Current cashflow is positive and can support a near-term savings plan.")
        lines.extend(
            [
                "",
                "**Recommended Next 7 Days**",
                "1. Auto-allocate 20-30% of positive net cashflow to your savings goal.",
                "2. Maintain at least 3 months of essential-expense runway.",
                "3. Track budget drift and adjust monthly allocations.",
            ]
        )
    return "\n".join(lines)


def _build_risk_advice(state: AgentState, vietnamese: bool) -> str:
    anomaly = state.get("tool_outputs", {}).get("anomaly_signals_v1", {})
    risk = state.get("tool_outputs", {}).get("risk_profile_non_investment_v1", {})
    risk_band = str(risk.get("risk_band") or "unknown")
    runway = _safe_float(risk.get("emergency_runway_months"))
    volatility = _safe_float(risk.get("cashflow_volatility"))
    overspend = _safe_float(risk.get("overspend_propensity"))
    flags = anomaly.get("flags") or []

    if vietnamese:
        lines = ["**Tong quan rui ro**"]
        lines.append(f"- Muc rui ro: {risk_band}")
        lines.append(f"- Runway uoc tinh: {runway:.2f} thang")
        lines.append(f"- Bien dong dong tien: {_fmt_pct(volatility)}")
        lines.append(f"- Ty le thang vuot chi: {_fmt_pct(overspend)}")
        if flags:
            lines.append(f"- Canh bao anomaly: {', '.join([str(flag) for flag in flags])}")
        else:
            lines.append("- Khong co anomaly nghiem trong trong cua so kiem tra hien tai")
        lines.extend(
            [
                "",
                "**Khuyen nghi uu tien**",
                "1. Duy tri runway toi thieu 3 thang chi tieu thiet yeu.",
                "2. Khoa han muc o cac nhom co bien dong cao.",
                "3. Theo doi lai chi so rui ro sau 2-4 tuan.",
            ]
        )
        return "\n".join(lines)

    lines = ["**Risk Overview**"]
    lines.append(f"- Risk band: {risk_band}")
    lines.append(f"- Estimated runway: {runway:.2f} months")
    lines.append(f"- Cashflow volatility: {_fmt_pct(volatility)}")
    lines.append(f"- Overspend propensity: {_fmt_pct(overspend)}")
    if flags:
        lines.append(f"- Anomaly flags: {', '.join([str(flag) for flag in flags])}")
    else:
        lines.append("- No severe anomaly flags in the current lookback window")
    lines.extend(
        [
            "",
            "**Priority Actions**",
            "1. Keep emergency runway above 3 months.",
            "2. Cap highly volatile spend categories.",
            "3. Re-check risk metrics in 2-4 weeks.",
        ]
    )
    return "\n".join(lines)


def _build_planning_advice(state: AgentState, vietnamese: bool) -> str:
    summary = state.get("context", {}).get("summary", {})
    forecast = state.get("context", {}).get("forecast", {})
    goal = state.get("tool_outputs", {}).get("goal_feasibility_v1", {})
    recurring = state.get("tool_outputs", {}).get("recurring_cashflow_detect_v1", {})
    parsed_goal = _extract_goal_request(state.get("prompt", ""))

    total_spend = _safe_float(summary.get("total_spend"))
    total_income = _safe_float(summary.get("total_income"))
    net_cashflow_30d = _safe_float(summary.get("net_cashflow"), total_income - total_spend)
    fixed_cost_ratio = _safe_float(recurring.get("fixed_cost_ratio"))

    target_amount = _safe_float(goal.get("target_amount"), _safe_float(parsed_goal.get("target_amount")))
    horizon_months = _safe_int(goal.get("horizon_months"), _safe_int(parsed_goal.get("horizon_months"), 12))
    if horizon_months <= 0:
        horizon_months = 12

    required_monthly_saving = _safe_float(goal.get("required_monthly_saving"))
    if required_monthly_saving <= 0 and target_amount > 0:
        required_monthly_saving = target_amount / max(horizon_months, 1)

    feasible = bool(goal.get("feasible"))
    gap_amount = _safe_float(goal.get("gap_amount"))
    forecast_stats = _forecast_stats(forecast)
    monthly_capacity = forecast_stats["avg_p50"] * 4.345 if forecast_stats["count"] > 0 else net_cashflow_30d
    eta_question = bool(parsed_goal.get("is_eta_question"))
    top_jar = _top_jar(summary)
    range_days = _summary_range_days(summary)

    if vietnamese:
        lines = ["**Ke hoach muc tieu tai chinh**"]
        if target_amount > 0:
            lines.append(f"- Muc tieu: tiet kiem {_fmt_money(target_amount)} trong {horizon_months} thang")
        lines.append(
            f"- Trang thai {range_days} ngay: "
            f"thu {_fmt_money(total_income)}, chi {_fmt_money(total_spend)}, net {_fmt_signed_money(net_cashflow_30d)}"
        )
        if required_monthly_saving > 0:
            lines.append(f"- Muc tiet kiem toi thieu can dat: {_fmt_money(required_monthly_saving)}/thang")
        lines.append(f"- Ty trong chi phi co dinh uoc tinh: {_fmt_pct(fixed_cost_ratio)}")

        lines.extend(["", "**Danh gia tu van**"])
        if feasible:
            lines.append("Ke hoach hien tai kha thi neu duy tri ky luat chi tieu.")
        else:
            if gap_amount > 0:
                lines.append(f"Hien chua kha thi, con thieu khoang {_fmt_money(gap_amount)} theo mo hinh hien tai.")
            else:
                lines.append("Hien chua kha thi voi dong tien hien tai.")

        if eta_question and target_amount > 0:
            if monthly_capacity > 0:
                eta_months = target_amount / monthly_capacity
                lines.append(
                    f"ETA theo net du bao hien tai: ~{eta_months:.1f} thang "
                    "(gia dinh dong tien khong xau di)."
                )
            else:
                lines.append("Khong the dua ETA duong vi net forecast dang am. Can dao chieu dong tien truoc.")

        lines.extend(["", "**Hanh dong de xuat**"])
        if top_jar:
            lines.append(
                "1. Uu tien giam truoc o nhom "
                f"{top_jar.get('jar_name', 'Unknown')} "
                f"({_fmt_pct(_safe_float(top_jar.get('pct_of_spend')))} cua tong chi)."
            )
            lines.append("2. Thiet lap han muc chi theo tuan de tranh vuot ngan sach.")
            lines.append("3. Tu dong chuyen tien vao quy muc tieu ngay khi co thu nhap.")
        else:
            lines.append("1. Thiet lap han muc chi theo tuan.")
            lines.append("2. Cat 10-15% chi tieu khong thiet yeu trong 2 tuan dau.")
            lines.append("3. Tu dong chuyen tien vao quy muc tieu ngay khi co thu nhap.")
        return "\n".join(lines)

    lines = ["**Financial Goal Plan**"]
    if target_amount > 0:
        lines.append(f"- Target: save {_fmt_money(target_amount)} within {horizon_months} months")
    lines.append(
        f"- Current {range_days}-day status: "
        f"income {_fmt_money(total_income)}, spend {_fmt_money(total_spend)}, net {_fmt_signed_money(net_cashflow_30d)}"
    )
    if required_monthly_saving > 0:
        lines.append(f"- Minimum monthly saving needed: {_fmt_money(required_monthly_saving)}")
    lines.append(f"- Estimated fixed-cost ratio: {_fmt_pct(fixed_cost_ratio)}")

    lines.extend(["", "**Advisor Assessment**"])
    if feasible:
        lines.append("The current plan is feasible if spending discipline is maintained.")
    else:
        if gap_amount > 0:
            lines.append(f"Not feasible yet, with a projected gap of {_fmt_money(gap_amount)}.")
        else:
            lines.append("Not feasible with the current cashflow profile.")

    if eta_question and target_amount > 0:
        if monthly_capacity > 0:
            eta_months = target_amount / monthly_capacity
            lines.append(f"ETA from current forecast net: ~{eta_months:.1f} months (assuming stable behavior).")
        else:
            lines.append("A positive ETA cannot be estimated because projected net cashflow is negative.")

    lines.extend(["", "**Recommended Actions**"])
    if top_jar:
        lines.append(
            "1. Reduce "
            f"{top_jar.get('jar_name', 'Unknown')} first "
            f"({_fmt_pct(_safe_float(top_jar.get('pct_of_spend')))} of total spend)."
        )
        lines.append("2. Set weekly spending caps and monitor drift.")
        lines.append("3. Auto-transfer savings immediately on income events.")
    else:
        lines.append("1. Set weekly spending caps.")
        lines.append("2. Cut 10-15% non-essential spend in the next 2 weeks.")
        lines.append("3. Auto-transfer savings immediately on income events.")
    return "\n".join(lines)


def _build_scenario_advice(state: AgentState, vietnamese: bool) -> str:
    raw_scenario = state.get("tool_outputs", {}).get("what_if_scenario_v1", {})
    scenario = _scenario_payload(raw_scenario if isinstance(raw_scenario, dict) else {})
    comparison = scenario.get("scenario_comparison") or []
    best_name = str(scenario.get("best_variant_by_goal") or "")
    base_total = _safe_float(scenario.get("base_total_net_p50"))
    request = state.get("scenario_request", {}) or {}
    focus_variant = str(request.get("focus_variant") or "")
    overrides = request.get("overrides") if isinstance(request.get("overrides"), dict) else {}
    focus_label = _describe_scenario_overrides(overrides, vietnamese)

    rows: list[Dict[str, Any]] = []
    for row in comparison:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "name": str(row.get("name") or ""),
                "delta": _safe_float(row.get("delta_vs_base")),
                "total_net_p50": _safe_float(row.get("total_net_p50")),
            }
        )

    best_delta = 0.0
    if best_name and best_name != "base":
        for row in rows:
            if row["name"] == best_name:
                best_delta = _safe_float(row["delta"])
                break

    focus_delta: float | None = None
    if focus_variant:
        for row in rows:
            if row["name"] == focus_variant:
                focus_delta = _safe_float(row["delta"])
                break

    if vietnamese:
        if not rows:
            lines = ["**Phân tích kịch bản**"]
            lines.append("- Chưa nhận được bảng so sánh kịch bản từ tool trong lần gọi này.")
            if focus_label:
                lines.append(f"- Kịch bản đã gửi: {focus_label}.")
            lines.append("- Vui lòng thử lại hoặc kiểm tra trace để debug input/output tool.")
            return "\n".join(lines)

        lines = ["**Phân tích kịch bản**"]
        lines.append(f"- Số kịch bản so sánh: {len(rows)}")
        lines.append(f"- Tổng net P50 cơ sở: {_fmt_money(base_total)}")
        if focus_delta is not None:
            label = focus_label or focus_variant
            lines.append(f"- Kịch bản bạn hỏi ({label}): {_fmt_signed_money(focus_delta)} so với cơ sở.")
        lines.append(f"- Kịch bản tốt nhất theo mục tiêu: {best_name or 'base'}")
        lines.append(f"- Delta của kịch bản tốt nhất: {_fmt_signed_money(best_delta)}")
        lines.append("")
        lines.append("**Chi tiết delta theo kịch bản**")
        for row in rows[:3]:
            lines.append(f"- {row['name'] or 'variant'}: {_fmt_signed_money(row['delta'])}")
        lines.extend(
            [
                "",
                "**Khuyến nghị tư vấn**",
                "1. Ưu tiên phương án có delta dương và bền vững.",
                "2. Theo dõi thực tế 2-4 tuần để xác nhận xu hướng.",
                "3. Cập nhật lại giả định khi thu/chi thay đổi mạnh.",
            ]
        )
        return "\n".join(lines)

    if not rows:
        lines = ["**Scenario Analysis**"]
        lines.append("- No scenario comparison table was returned by tool in this run.")
        if focus_label:
            lines.append(f"- Scenario sent: {focus_label}.")
        lines.append("- Retry and inspect trace logs for tool input/output.")
        return "\n".join(lines)

    lines = ["**Scenario Analysis**"]
    lines.append(f"- Scenarios compared: {len(rows)}")
    lines.append(f"- Base total net P50: {_fmt_money(base_total)}")
    if focus_delta is not None:
        label = focus_label or focus_variant
        lines.append(f"- Your requested scenario ({label}): {_fmt_signed_money(focus_delta)} vs base.")
    lines.append(f"- Best variant by goal: {best_name or 'base'}")
    lines.append(f"- Best-variant delta: {_fmt_signed_money(best_delta)}")
    lines.append("")
    lines.append("**Delta Breakdown**")
    for row in rows[:3]:
        lines.append(f"- {row['name'] or 'variant'}: {_fmt_signed_money(row['delta'])}")
    lines.extend(
        [
            "",
            "**Advisor Recommendation**",
            "1. Apply the positive-delta variant first.",
            "2. Re-check actual outcomes after 2-4 weeks.",
            "3. Recalibrate assumptions if income/spend shifts materially.",
        ]
    )
    return "\n".join(lines)


def _build_education_only_advice(state: AgentState, vietnamese: bool) -> str:
    risk = state.get("tool_outputs", {}).get("risk_profile_non_investment_v1", {})
    risk_band = str(risk.get("risk_band") or "")
    runway = _safe_float(risk.get("emergency_runway_months"))
    base = "I can provide educational financial guidance only and cannot execute buy/sell actions."
    if vietnamese:
        lines = [
            "**Gioi han tu van**",
            "- Toi chi cung cap huong dan tai chinh mang tinh giao duc.",
            "- Toi khong thuc hien hoac khuyen nghi lenh mua/ban.",
        ]
        if risk_band:
            lines.append(f"- Muc rui ro hien tai: {risk_band}")
            if runway > 0:
                lines.append(f"- Runway uoc tinh: {runway:.2f} thang")
        lines.append("")
        lines.append(
            "Ban co the hoi minh ve quan ly dong tien, ngan sach va ke hoach tiet kiem an toan."
        )
        return "\n".join(lines)

    if risk_band:
        base += f" Current non-investment risk band: {risk_band}"
        if runway > 0:
            base += f" (runway {runway:.2f} months)."
        else:
            base += "."
    return base


def _build_out_of_scope_advice(vietnamese: bool) -> str:
    if vietnamese:
        return (
            "**Ngoai pham vi ho tro hien tai**\n"
            "- Tro ly nay tap trung vao dong tien, ngan sach, rui ro phi dau tu va what-if scenario.\n"
            "- Vui long mo ta lai theo mot trong cac huong: tong quan dong tien, canh bao rui ro, "
            "lap ke hoach tiet kiem, hoac so sanh kich ban."
        )
    return (
        "**Out Of Supported Scope**\n"
        "- This assistant focuses on cashflow, budgeting, non-investment risk, and what-if scenarios.\n"
        "- Please rephrase as: cashflow summary, risk analysis, savings planning, or what-if scenario."
    )


def _build_intent_advice(state: AgentState, vietnamese: bool) -> str:
    intent = state.get("intent", "summary")
    if intent == "risk":
        return _build_risk_advice(state, vietnamese)
    if intent == "planning":
        return _build_planning_advice(state, vietnamese)
    if intent == "scenario":
        return _build_scenario_advice(state, vietnamese)
    if intent == "invest":
        return _build_education_only_advice(state, vietnamese)
    if intent == "out_of_scope":
        return _build_out_of_scope_advice(vietnamese)
    return _build_summary_advice(state, vietnamese)


def _finalize_response(body: str, citations: str, trace_id: str, tool_chain: str) -> str:
    lines = [str(body or "").strip()]
    if citations:
        lines.append(f"Citations: {citations}")
    lines.append(f"Trace: {trace_id}")
    if tool_chain:
        lines.append(f"Tools: {tool_chain}")
    return "\n\n".join([line for line in lines if line])


def _resolve_required_disclaimer(state: AgentState) -> str:
    guard = state.get("tool_outputs", {}).get("suitability_guard_v1", {})
    if isinstance(guard, dict):
        value = str(guard.get("required_disclaimer") or "").strip()
        if value:
            return value
    return DEFAULT_DISCLAIMER


def _as_ratio(value: Any) -> float | None:
    if value is None:
        return None
    ratio = _safe_float(value, 0.0)
    if ratio == 0.0:
        return None
    if abs(ratio) > 1.0:
        ratio = ratio / 100.0
    return round(ratio, 4)


def _build_scenario_request_from_slots(slots: Dict[str, Any], fallback: Dict[str, Any] | None = None) -> Dict[str, Any]:
    fallback_payload = fallback or {}
    if not isinstance(slots, dict):
        return fallback_payload

    horizon_months = _safe_int(slots.get("horizon_months"), _safe_int(fallback_payload.get("horizon_months"), 12))
    horizon_months = max(1, min(24, horizon_months or 12))
    goal = str(slots.get("goal") or fallback_payload.get("goal") or "maximize_savings")
    seasonality = bool(slots.get("seasonality", fallback_payload.get("seasonality", True)))

    overrides: Dict[str, Any] = {}
    for key in ["income_delta_pct", "spend_delta_pct"]:
        parsed = _as_ratio(slots.get(key))
        if parsed is not None:
            overrides[key] = parsed

    for key in ["income_delta_amount_vnd", "spend_delta_amount_vnd"]:
        parsed_amount = _safe_float(slots.get(key), 0.0)
        if parsed_amount > 0:
            overrides[key] = parsed_amount

    variants_raw = slots.get("variants")
    variants: list[Dict[str, Any]] = []
    if isinstance(variants_raw, list):
        for item in variants_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip() or "user_variant"
            variant_overrides = item.get("scenario_overrides")
            if not isinstance(variant_overrides, dict):
                continue
            cleaned_overrides: Dict[str, Any] = {}
            for key in ["income_delta_pct", "spend_delta_pct"]:
                parsed = _as_ratio(variant_overrides.get(key))
                if parsed is not None:
                    cleaned_overrides[key] = parsed
            for key in ["income_delta_amount_vnd", "spend_delta_amount_vnd"]:
                parsed_amount = _safe_float(variant_overrides.get(key), 0.0)
                if parsed_amount > 0:
                    cleaned_overrides[key] = parsed_amount
            if cleaned_overrides:
                variants.append({"name": name, "scenario_overrides": cleaned_overrides})

    if not variants:
        if overrides:
            variant_name = str(slots.get("variant_name") or "user_requested_scenario")
            variants = [{"name": variant_name, "scenario_overrides": overrides}]
        elif isinstance(fallback_payload.get("variants"), list):
            variants = fallback_payload.get("variants") or _scenario_default_variants()
        else:
            variants = _scenario_default_variants()

    focus_variant = str(slots.get("focus_variant") or "")
    if not focus_variant and variants:
        first = variants[0]
        if isinstance(first, dict):
            focus_variant = str(first.get("name") or "")

    return {
        "base_scenario_overrides": fallback_payload.get("base_scenario_overrides") or {},
        "variants": variants,
        "focus_variant": focus_variant,
        "overrides": overrides,
        "horizon_months": horizon_months,
        "goal": goal,
        "seasonality": seasonality,
    }


def _goal_request_from_slots(slots: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    parsed_goal = _extract_goal_request(prompt)
    if not isinstance(slots, dict):
        return parsed_goal

    target_amount = parsed_goal.get("target_amount")
    for key in ["target_amount", "target_amount_vnd", "goal_target_amount"]:
        slot_value = _safe_float(slots.get(key), 0.0)
        if slot_value > 0:
            target_amount = slot_value
            break

    horizon_months = parsed_goal.get("horizon_months")
    for key in ["horizon_months", "goal_horizon_months"]:
        slot_value = _safe_int(slots.get(key), 0)
        if slot_value > 0:
            horizon_months = slot_value
            break

    return {
        "target_amount": target_amount,
        "horizon_months": horizon_months,
        "is_eta_question": bool(parsed_goal.get("is_eta_question")),
    }


def _build_clarification_response(state: AgentState, vietnamese: bool) -> str:
    clarification = state.get("clarification", {}) or {}
    question = clarification.get("question") if isinstance(clarification.get("question"), dict) else {}
    question_text = str(question.get("question_text") or "").strip()
    options = question.get("options") if isinstance(question.get("options"), list) else []

    if vietnamese:
        lines = ["**Cần Làm Rõ Để Định Tuyến Đúng Công Cụ**"]
        if question_text:
            lines.append(f"- Câu hỏi: {question_text}")
        if options:
            lines.append("- Lựa chọn: " + " | ".join([f"{idx + 1}) {str(opt)}" for idx, opt in enumerate(options)]))
        lines.append("- Vui lòng trả lời bằng số thứ tự (ví dụ: 1).")
        return "\n".join(lines)

    lines = ["**Need Clarification To Route Correct Tooling**"]
    if question_text:
        lines.append(f"- Question: {question_text}")
    if options:
        lines.append("- Options: " + " | ".join([f"{idx + 1}) {str(opt)}" for idx, opt in enumerate(options)]))
    lines.append("- Reply with the option number (for example: 1).")
    return "\n".join(lines)


def _build_encoding_fail_fast_response(vietnamese: bool) -> str:
    if vietnamese:
        return (
            "**Không Thể Xử Lý Prompt Do Lỗi Mã Hóa Ký Tự**\n"
            "- Hệ thống phát hiện prompt bị lỗi UTF-8/mojibake nên tạm dừng để tránh định tuyến sai công cụ.\n"
            "- Vui lòng gửi lại câu hỏi với tiếng Việt có dấu đầy đủ hoặc viết lại ngắn gọn."
        )
    return (
        "**Cannot process this prompt due to encoding issues**\n"
        "- The system detected UTF-8/mojibake corruption and stopped to avoid incorrect tool routing.\n"
        "- Please resend the question with clean UTF-8 text."
    )


def _record_tool_output(state: AgentState, tool_name: str, output: Dict[str, Any]) -> None:
    state["tool_outputs"][tool_name] = output
    if tool_name not in state["tool_calls"]:
        state["tool_calls"].append(tool_name)


def _record_tool_error(state: AgentState, tool_name: str, exc: Exception) -> None:
    tool_errors = state.get("tool_errors")
    if not isinstance(tool_errors, dict):
        tool_errors = {}
    tool_errors[tool_name] = {
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    state["tool_errors"] = tool_errors

    existing_meta = state.get("response_meta") if isinstance(state.get("response_meta"), dict) else {}
    reason_codes = [str(code).strip() for code in existing_meta.get("reason_codes", []) if str(code).strip()]
    reason_codes.append(f"tool_error:{tool_name}")
    state["response_meta"] = {**existing_meta, "reason_codes": sorted(set(reason_codes))}
    logger.warning("tool_call_failed tool=%s trace=%s error=%s", tool_name, state.get("trace_id"), exc)


def encoding_gate(state: AgentState) -> AgentState:
    prompt = state.get("prompt", "")
    normalized_prompt, encoding_decision = apply_prompt_encoding_gate(
        prompt,
        gate_enabled=ENCODING_GATE_ENABLED,
        repair_enabled=ENCODING_REPAIR_ENABLED,
        repair_score_min=ENCODING_REPAIR_SCORE_MIN,
        failfast_score_min=ENCODING_FAILFAST_SCORE_MIN,
        repair_min_delta=ENCODING_REPAIR_MIN_DELTA,
        normalization_form=ENCODING_NORMALIZATION_FORM,
    )
    state["prompt"] = normalized_prompt
    state["encoding_meta"] = encoding_decision.model_dump(exclude_none=True)

    existing_meta = state.get("response_meta") if isinstance(state.get("response_meta"), dict) else {}
    reason_codes = []
    for item in existing_meta.get("reason_codes", []):
        text = str(item).strip()
        if text:
            reason_codes.append(text)
    reason_codes.extend([str(code).strip() for code in encoding_decision.reason_codes if str(code).strip()])

    response_meta = {
        **existing_meta,
        "encoding_decision": encoding_decision.decision,
        "encoding_score": float(encoding_decision.mojibake_score),
        "encoding_repair_applied": bool(encoding_decision.repair_applied),
        "encoding_reason_codes": list(encoding_decision.reason_codes),
        "encoding_guess": str(encoding_decision.encoding_guess or ""),
        "encoding_input_fingerprint": str(encoding_decision.input_fingerprint or ""),
        "reason_codes": sorted(set(reason_codes)),
    }
    state["response_meta"] = response_meta

    if encoding_decision.decision == "fail_fast":
        vietnamese = _is_vietnamese_prompt(prompt) or _is_vietnamese_prompt(normalized_prompt)
        body = _build_encoding_fail_fast_response(vietnamese)
        response_meta["validation_passed"] = True
        response_meta["fallback_used"] = "encoding_fail_fast"
        response_meta["disclaimer_effective"] = DEFAULT_DISCLAIMER
        response_meta["reason_codes"] = sorted(set([*response_meta["reason_codes"], "encoding_fail_fast"]))
        state["response"] = _finalize_response(body, "", state["trace_id"], "")
        state["response_meta"] = response_meta
    return state


def intent_router(state: AgentState) -> AgentState:
    if state.get("response"):
        return state

    prompt = state.get("prompt", "")
    clarify_round = _safe_int(state.get("clarification", {}).get("round"), 0)
    max_clarify = max(1, _safe_int(ROUTER_MAX_CLARIFY_QUESTIONS, 2))
    effective_mode = "semantic_enforce" if ROUTER_MODE == "rule" else ROUTER_MODE
    if ROUTER_MODE == "rule":
        logger.warning("ROUTER_MODE=rule is deprecated for runtime path; forcing semantic_enforce.")

    state["scenario_request"] = {}
    state["clarification"] = {"pending": False, "round": clarify_round, "max_questions": max_clarify}
    state["extraction"] = {}
    state["route_decision"] = {
        "mode": effective_mode,
        "policy_version": ROUTER_POLICY_VERSION,
        "final_intent": "out_of_scope",
        "tool_bundle": ["suitability_guard_v1"],
        "clarify_needed": False,
        "reason_codes": [],
        "fallback_used": None,
        "source": "semantic",
    }
    state["intent"] = "out_of_scope"

    extraction, extraction_errors, extraction_meta = extract_intent_with_bedrock(prompt, retry_attempts=1)
    if extraction is None:
        fallback_reason_codes = [*extraction_errors, "structured_invalid_no_rule_fallback"]
        fallback = RouteDecisionV1(
            mode=effective_mode if effective_mode in {"semantic_shadow", "semantic_enforce"} else "semantic_enforce",
            policy_version=ROUTER_POLICY_VERSION,
            final_intent="out_of_scope",
            tool_bundle=["suitability_guard_v1"],
            clarify_needed=True,
            reason_codes=fallback_reason_codes,
            fallback_used="structured_invalid_no_rule_fallback",
            source="semantic",
        )
        state["route_decision"] = fallback.model_dump()
        state["intent"] = "out_of_scope"
        state["extraction"] = {"errors": extraction_errors, "meta": extraction_meta}
        state["clarification"] = {
            "pending": True,
            "round": clarify_round + 1,
            "max_questions": max_clarify,
            "question": {
                "question_id": "rephrase_intent",
                "question_text": "Bạn vui lòng chọn mục tiêu để hệ thống định tuyến đúng công cụ?",
                "options": ["Tổng quan dòng tiền", "Đánh giá rủi ro", "Lập kế hoạch/What-if"],
                "max_questions": max_clarify,
            },
        }
        logger.warning("Semantic extraction failed without rule fallback: %s", extraction_errors)
        return state

    override_intent, override_reason = suggest_intent_override(prompt, extraction)
    if override_intent is not None:
        previous_intent = extraction.intent
        extraction = extraction.model_copy(update={"intent": override_intent, "sub_intent": "heuristic_override"})
        extraction_meta = {
            **extraction_meta,
            "intent_override": {
                "from_intent": previous_intent,
                "to_intent": override_intent,
                "reason": override_reason,
            },
        }

    slots = extraction.slots if isinstance(extraction.slots, dict) else {}
    risk_appetite = _resolve_risk_appetite(prompt=prompt, slots=slots)
    if risk_appetite != "unknown":
        slots["risk_appetite"] = risk_appetite
    extraction = extraction.model_copy(update={"slots": slots})
    state["user_profile"] = {"risk_appetite": risk_appetite}

    state["extraction"] = {**extraction.model_dump(), "meta": extraction_meta, "errors": extraction_errors}

    semantic_decision = build_route_decision(
        mode=effective_mode if effective_mode in {"semantic_shadow", "semantic_enforce"} else "semantic_enforce",
        extraction=extraction,
        policy_version=ROUTER_POLICY_VERSION,
        intent_conf_min=ROUTER_INTENT_CONF_MIN,
        top2_gap_min=ROUTER_TOP2_GAP_MIN,
        scenario_conf_min=ROUTER_SCENARIO_CONF_MIN,
        max_clarify_questions=max_clarify,
        clarify_round=clarify_round,
    )
    if override_reason:
        semantic_decision.reason_codes = [*semantic_decision.reason_codes, override_reason]
    if risk_appetite == "unknown" and semantic_decision.final_intent in {"planning", "scenario", "invest"}:
        semantic_decision.reason_codes = [*semantic_decision.reason_codes, "risk_appetite_missing_soft_question"]

    if semantic_decision.fallback_used:
        fallback = RouteDecisionV1(
            mode=effective_mode if effective_mode in {"semantic_shadow", "semantic_enforce"} else "semantic_enforce",
            policy_version=ROUTER_POLICY_VERSION,
            final_intent="out_of_scope",
            tool_bundle=["suitability_guard_v1"],
            clarify_needed=False,
            reason_codes=[*semantic_decision.reason_codes, "semantic_fallback_no_rule"],
            fallback_used=f"{semantic_decision.fallback_used}_no_rule_fallback",
            source="semantic",
        )
        state["route_decision"] = fallback.model_dump()
        state["intent"] = "out_of_scope"
        return state

    if semantic_decision.clarify_needed and semantic_decision.clarifying_question is not None:
        state["clarification"] = {
            "pending": True,
            "round": clarify_round + 1,
            "max_questions": max_clarify,
            "question": semantic_decision.clarifying_question.model_dump(),
        }

    state["route_decision"] = semantic_decision.model_dump()
    state["intent"] = semantic_decision.final_intent
    if semantic_decision.final_intent == "scenario":
        state["scenario_request"] = _build_scenario_request_from_slots(extraction.slots, {})
    return state


def suitability_guard(state: AgentState) -> AgentState:
    if state.get("response"):
        return state

    requested_action = _requested_action(state["prompt"])
    decision = suitability_guard_tool(
        state["user_token"],
        user_id=state["user_id"],
        intent=state.get("intent", ""),
        requested_action=requested_action,
        prompt=state["prompt"],
        trace_id=state["trace_id"],
    )
    if _should_override_recommendation_deny(state.get("intent", ""), requested_action, decision):
        disclaimer = str(decision.get("required_disclaimer") or DEFAULT_DISCLAIMER)
        reason_codes = [str(code).strip() for code in decision.get("reason_codes", []) if str(code).strip()]
        reason_codes.extend(["investment_recommendation_blocked", "agent_recommendation_override"])
        decision = {
            **decision,
            "allow": False,
            "decision": "deny_recommendation",
            "required_disclaimer": disclaimer,
            "refusal_message": (
                "I cannot execute or recommend buy/sell actions. "
                "I can provide educational guidance only."
            ),
            "reason_codes": sorted(set(reason_codes)),
            "education_only": True,
        }
    state["tool_outputs"]["suitability_guard_v1"] = decision
    state["tool_calls"].append("suitability_guard_v1")
    state["education_only"] = bool(decision.get("education_only") or decision.get("decision") == "education_only")
    if not bool(decision.get("allow", True)):
        refusal = str(decision.get("refusal_message") or "Action is not allowed by policy.")
        disclaimer = str(decision.get("required_disclaimer") or DEFAULT_DISCLAIMER)
        existing_meta = state.get("response_meta") if isinstance(state.get("response_meta"), dict) else {}
        reason_codes = [str(code).strip() for code in existing_meta.get("reason_codes", []) if str(code).strip()]
        reason_codes.append("policy_refusal")
        state["response"] = (
            f"{refusal} "
            f"Disclaimer: {disclaimer} "
            f"Trace: {state['trace_id']}. Tools: suitability_guard_v1."
        )
        state["response_meta"] = {
            **existing_meta,
            "mode": RESPONSE_MODE,
            "model_id": "",
            "prompt_version": RESPONSE_PROMPT_VERSION,
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "policy_version": RESPONSE_POLICY_VERSION,
            "validation_passed": True,
            "fallback_used": "suitability_refusal",
            "used_fact_ids": [],
            "used_insight_ids": [],
            "used_action_ids": [],
            "latency_ms": 0,
            "reason_codes": sorted(set(reason_codes)),
            "disclaimer_effective": disclaimer,
        }
    return state


def fetch_context(state: AgentState) -> AgentState:
    if state.get("response"):
        return state
    if bool(state.get("clarification", {}).get("pending")):
        return state

    summary = state.get("tool_outputs", {}).get("spend_analytics_v1", {})
    forecast = state.get("tool_outputs", {}).get("cashflow_forecast_v1", {})
    state["context"] = {"summary": summary, "forecast": forecast}
    return state


def retrieve_kb(state: AgentState) -> AgentState:
    if state.get("response"):
        return state
    if bool(state.get("clarification", {}).get("pending")):
        state["kb"] = {"matches": [], "note": "clarification_pending"}
        return state
    query = _build_kb_query(state.get("prompt", ""), state.get("intent", ""))
    intent = state.get("intent", "")
    state["kb"] = kb_retrieve(query, {"doc_type": "policy"}, state["user_token"], trace_id=state.get("trace_id"), intent=intent)
    return state


def _execute_tool_safe(tool_name: str, state: AgentState, extraction_slots: Dict[str, Any]) -> tuple[str, Dict[str, Any] | Exception]:
    """Execute a single tool with error handling. Returns (tool_name, result_or_exception)."""
    try:
        if tool_name == "suitability_guard_v1":
            # Skip - executed in dedicated suitability node
            return tool_name, {"skipped": True}
        if tool_name == "spend_analytics_v1":
            range_days = _resolve_summary_range(state.get("prompt", ""), state.get("intent", "summary"))
            result = spend_analytics(
                state["user_token"],
                user_id=state["user_id"],
                range_days=range_days,
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "cashflow_forecast_v1":
            horizon_hint = _safe_int(extraction_slots.get("horizon_months"), 0)
            horizon = "daily_30" if horizon_hint == 1 else "weekly_12"
            result = cashflow_forecast_tool(
                state["user_token"],
                user_id=state["user_id"],
                horizon=horizon,
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "anomaly_signals_v1":
            lookback_days = _safe_int(extraction_slots.get("lookback_days"), 90)
            result = anomaly_signals(
                state["user_token"],
                user_id=state["user_id"],
                lookback_days=max(30, min(365, lookback_days or 90)),
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "risk_profile_non_investment_v1":
            lookback_days = _safe_int(extraction_slots.get("lookback_days"), 180)
            result = risk_profile_non_investment_tool(
                state["user_token"],
                user_id=state["user_id"],
                lookback_days=max(60, min(720, lookback_days or 180)),
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "recurring_cashflow_detect_v1":
            result = recurring_cashflow_detect_tool(
                state["user_token"],
                user_id=state["user_id"],
                lookback_months=max(3, min(24, _safe_int(extraction_slots.get("lookback_months"), 6) or 6)),
                min_occurrence_months=max(
                    2,
                    min(12, _safe_int(extraction_slots.get("min_occurrence_months"), 3) or 3),
                ),
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "goal_feasibility_v1":
            goal_request = _goal_request_from_slots(extraction_slots, state.get("prompt", ""))
            result = goal_feasibility_tool(
                state["user_token"],
                user_id=state["user_id"],
                target_amount=goal_request.get("target_amount"),
                horizon_months=goal_request.get("horizon_months") or 12,
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "jar_allocation_suggest_v1":
            result = jar_allocation_suggest_tool(
                state["user_token"],
                user_id=state["user_id"],
                trace_id=state["trace_id"],
            )
            return tool_name, result

        if tool_name == "what_if_scenario_v1":
            scenario_request = state.get("scenario_request", {})
            if not isinstance(scenario_request, dict) or not scenario_request:
                scenario_request = _build_scenario_request_from_slots(extraction_slots, {})
            result = what_if_scenario_tool(
                state["user_token"],
                user_id=state["user_id"],
                horizon_months=max(1, min(24, _safe_int(scenario_request.get("horizon_months"), 12) or 12)),
                seasonality=bool(scenario_request.get("seasonality", True)),
                goal=str(scenario_request.get("goal") or "maximize_savings"),
                base_scenario_overrides=scenario_request.get("base_scenario_overrides") or {},
                variants=scenario_request.get("variants") or [],
                trace_id=state["trace_id"],
            )
            return tool_name, result
        
        return tool_name, {"error": f"Unknown tool: {tool_name}"}
    except Exception as exc:
        logger.warning("Tool execution failed: tool=%s error=%s", tool_name, exc)
        return tool_name, exc


def decision_engine(state: AgentState) -> AgentState:
    if state.get("response"):
        return state
    if bool(state.get("clarification", {}).get("pending")):
        return state

    route_decision = state.get("route_decision", {}) if isinstance(state.get("route_decision"), dict) else {}
    tool_bundle = route_decision.get("tool_bundle")
    if not isinstance(tool_bundle, list) or not tool_bundle:
        tool_bundle = tool_bundle_for_intent(state.get("intent", "summary"))

    extraction_slots = {}
    extraction = state.get("extraction", {})
    if isinstance(extraction, dict):
        slots = extraction.get("slots")
        if isinstance(slots, dict):
            extraction_slots = slots

    # Filter out suitability_guard (executed earlier)
    tools_to_execute = [t for t in tool_bundle if t != "suitability_guard_v1"]
    
    # Execute tools in parallel for better performance
    logger.info("Executing %d tools in parallel: %s", len(tools_to_execute), tools_to_execute)
    with ThreadPoolExecutor(max_workers=min(5, len(tools_to_execute) or 1)) as executor:
        future_to_tool = {
            executor.submit(_execute_tool_safe, tool_name, state, extraction_slots): tool_name
            for tool_name in tools_to_execute
        }
        
        # Use centralized timeout config, remove per-task timeout (requests already have timeouts)
        for future in as_completed(future_to_tool, timeout=TOOL_EXECUTION_TIMEOUT):
            tool_name = future_to_tool[future]
            try:
                result_tool_name, result = future.result()  # No timeout here - requests handle individual timeouts
                if isinstance(result, Exception):
                    _record_tool_error(state, result_tool_name, result)
                elif isinstance(result, dict) and result.get("skipped"):
                    continue
                else:
                    _record_tool_output(state, result_tool_name, result)
                    # Special handling for some tools
                    if result_tool_name == "risk_profile_non_investment_v1" and state.get("intent") == "invest":
                        state["education_only"] = True
                    if result_tool_name == "what_if_scenario_v1":
                        scenario_request = state.get("scenario_request", {})
                        if not isinstance(scenario_request, dict) or not scenario_request:
                            scenario_request = _build_scenario_request_from_slots(extraction_slots, {})
                        state["tool_outputs"]["scenario_request"] = scenario_request
            except Exception as exc:
                logger.warning("Failed to get tool result: tool=%s error=%s", tool_name, exc)
                _record_tool_error(state, tool_name, exc)

    state["context"] = {
        "summary": state.get("tool_outputs", {}).get("spend_analytics_v1", {}),
        "forecast": state.get("tool_outputs", {}).get("cashflow_forecast_v1", {}),
    }
    return state


def _response_mode() -> str:
    mode = str(RESPONSE_MODE or "llm_shadow").strip().lower()
    if mode not in {"template", "llm_shadow", "llm_enforce"}:
        return "llm_shadow"
    return mode


def _repair_grounding_used_fact_ids(answer_plan: Any, validation_errors: list[str]) -> Any | None:
    if answer_plan is None:
        return None
    if not validation_errors:
        return answer_plan

    allowed_tokens = {
        "placeholder_fact_not_declared_used",
    }
    additions: list[str] = []
    for err in validation_errors:
        if err.startswith("metric_fact_not_declared_used:"):
            fact_id = err.split(":", 1)[1].strip()
            if fact_id:
                additions.append(fact_id)
            continue
        if err.startswith("placeholder_fact_not_declared_used_sample:"):
            raw = err.split(":", 1)[1].strip()
            if raw:
                additions.extend(item.strip() for item in raw.split(",") if item.strip())
            continue
        if err in allowed_tokens:
            continue
        return None

    if not additions:
        return None

    merged: list[str] = []
    for item in [*getattr(answer_plan, "used_fact_ids", []), *additions]:
        value = str(item).strip()
        if not value or value in merged:
            continue
        merged.append(value)
    return answer_plan.model_copy(update={"used_fact_ids": merged})


def _legacy_reasoning_body(state: AgentState, vietnamese: bool) -> str:
    if state.get("education_only"):
        return _build_education_only_advice(state, vietnamese)
    return _build_intent_advice(state, vietnamese)


def reasoning(state: AgentState) -> AgentState:
    if state.get("response"):
        return state

    citations = ", ".join([m.get("citation", "") for m in state.get("kb", {}).get("matches", []) if m.get("citation")])
    tool_chain = ", ".join(state.get("tool_calls", []))
    vietnamese = _is_vietnamese_prompt(state.get("prompt", ""))
    language = "vi" if vietnamese else "en"
    mode = _response_mode()
    default_disclaimer = _resolve_required_disclaimer(state)
    existing_meta = state.get("response_meta") if isinstance(state.get("response_meta"), dict) else {}
    encoding_reason_codes = existing_meta.get("encoding_reason_codes")
    if not isinstance(encoding_reason_codes, list):
        encoding_reason_codes = []
    response_meta: Dict[str, Any] = {
        "mode": mode,
        "model_id": "",
        "prompt_version": RESPONSE_PROMPT_VERSION,
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "policy_version": RESPONSE_POLICY_VERSION,
        "validation_passed": False,
        "fallback_used": None,
        "used_fact_ids": [],
        "used_insight_ids": [],
        "used_action_ids": [],
        "latency_ms": 0,
        "reason_codes": [],
        "disclaimer_effective": default_disclaimer,
        "encoding_decision": str(existing_meta.get("encoding_decision") or "pass"),
        "encoding_score": float(existing_meta.get("encoding_score") or 0.0),
        "encoding_repair_applied": bool(existing_meta.get("encoding_repair_applied") or False),
        "encoding_reason_codes": [str(code) for code in encoding_reason_codes if str(code).strip()],
        "encoding_guess": str(existing_meta.get("encoding_guess") or ""),
        "encoding_input_fingerprint": str(existing_meta.get("encoding_input_fingerprint") or ""),
    }
    response_meta["reason_codes"].extend(
        [str(code).strip() for code in existing_meta.get("reason_codes", []) if str(code).strip()]
    )
    route_reason_codes = []
    if isinstance(state.get("route_decision"), dict):
        route_reason_codes = state.get("route_decision", {}).get("reason_codes", [])
    response_meta["reason_codes"].extend([str(code).strip() for code in route_reason_codes if str(code).strip()])

    if bool(state.get("clarification", {}).get("pending")):
        body = _build_clarification_response(state, vietnamese)
        response_meta.update(
            {
                "validation_passed": True,
                "fallback_used": "clarification_pending",
            }
        )
        state["response_meta"] = response_meta
        state["response"] = _finalize_response(body, citations, state["trace_id"], tool_chain)
        return state

    extraction_slots = {}
    extraction = state.get("extraction", {})
    if isinstance(extraction, dict) and isinstance(extraction.get("slots"), dict):
        extraction_slots = extraction.get("slots") or {}
    risk_appetite = str((state.get("user_profile") or {}).get("risk_appetite") or "").strip().lower()
    if risk_appetite not in {"conservative", "moderate", "aggressive", "unknown"}:
        risk_appetite = _resolve_risk_appetite(prompt=state.get("prompt", ""), slots=extraction_slots)
    extraction_slots = dict(extraction_slots)
    if risk_appetite != "unknown":
        extraction_slots["risk_appetite"] = risk_appetite
    state["user_profile"] = {"risk_appetite": risk_appetite}

    policy_flags = {
        "education_only": bool(state.get("education_only")),
        "intent": state.get("intent", ""),
        "required_disclaimer": default_disclaimer,
        "policy_version": RESPONSE_POLICY_VERSION,
        "risk_appetite": risk_appetite,
        "risk_appetite_known": risk_appetite in {"conservative", "moderate", "aggressive"},
    }
    evidence_pack, evidence_reasons = build_evidence_pack(
        intent=state.get("intent", "out_of_scope"),
        language=language,
        tool_outputs=state.get("tool_outputs", {}),
        kb=state.get("kb", {}),
        policy_flags=policy_flags,
        extraction_slots=extraction_slots,
    )
    state["evidence_pack"] = evidence_pack.model_dump()
    response_meta["reason_codes"].extend(evidence_reasons)
    advisory_context, advisory_reasons = build_advisory_context(
        evidence_pack=evidence_pack,
        policy_version=RESPONSE_POLICY_VERSION,
    )
    state["advisory_context"] = advisory_context.model_dump()
    response_meta["reason_codes"].extend(advisory_reasons)
    allowed_prompt_numeric_tokens = extract_numeric_tokens_for_grounding(state.get("prompt", ""))

    if mode == "template":
        body = _legacy_reasoning_body(state, vietnamese)
        response_meta.update(
            {
                "validation_passed": True,
                "fallback_used": "template_mode",
                "disclaimer_effective": default_disclaimer,
            }
        )
        response_meta["reason_codes"] = sorted(set(str(item) for item in response_meta["reason_codes"]))
        state["response_meta"] = response_meta
        state["response"] = _finalize_response(body, citations, state["trace_id"], tool_chain)
        return state

    synthesis_start = time.perf_counter()
    answer_plan, synth_errors, synth_meta = synthesize_answer_plan_with_bedrock(
        user_prompt=state.get("prompt", ""),
        intent=state.get("intent", "out_of_scope"),
        route_decision=state.get("route_decision", {}),
        advisory_context=advisory_context,
        policy_flags=policy_flags,
        retry_attempts=min(1, RESPONSE_MAX_RETRIES),
    )
    response_meta["reason_codes"].extend(synth_errors)
    response_meta["model_id"] = str(synth_meta.get("model_id") or "")
    response_meta["prompt_version"] = str(synth_meta.get("prompt_version") or RESPONSE_PROMPT_VERSION)

    llm_body = ""
    fallback_used: str | None = None
    if answer_plan is None:
        if RESPONSE_MAX_RETRIES > 0:
            retry_plan, retry_errors, retry_meta = synthesize_answer_plan_with_bedrock(
                user_prompt=state.get("prompt", ""),
                intent=state.get("intent", "out_of_scope"),
                route_decision=state.get("route_decision", {}),
                advisory_context=advisory_context,
                policy_flags=policy_flags,
                retry_attempts=0,
                corrective_feedback=", ".join(synth_errors[-4:]) or "invalid_json_or_schema",
            )
            response_meta["reason_codes"].extend(retry_errors)
            response_meta["model_id"] = str(retry_meta.get("model_id") or response_meta["model_id"])
            response_meta["prompt_version"] = str(
                retry_meta.get("prompt_version") or response_meta["prompt_version"]
            )
            if retry_plan is not None:
                answer_plan = retry_plan
        if answer_plan is None:
            fallback_used = "answer_synthesis_failed"
    if answer_plan is not None:
        validation_errors = validate_answer_grounding(
            answer_plan,
            advisory_context,
            education_only=bool(state.get("education_only")),
            allowed_prompt_numeric_tokens=allowed_prompt_numeric_tokens,
        )
        if validation_errors and RESPONSE_MAX_RETRIES > 0:
            retry_plan, retry_errors, retry_meta = synthesize_answer_plan_with_bedrock(
                user_prompt=state.get("prompt", ""),
                intent=state.get("intent", "out_of_scope"),
                route_decision=state.get("route_decision", {}),
                advisory_context=advisory_context,
                policy_flags=policy_flags,
                retry_attempts=0,
                corrective_feedback=", ".join(validation_errors),
            )
            response_meta["reason_codes"].extend(retry_errors)
            response_meta["model_id"] = str(retry_meta.get("model_id") or response_meta["model_id"])
            response_meta["prompt_version"] = str(
                retry_meta.get("prompt_version") or response_meta["prompt_version"]
            )
            if retry_plan is not None:
                answer_plan = retry_plan
                validation_errors = validate_answer_grounding(
                    answer_plan,
                    advisory_context,
                    education_only=bool(state.get("education_only")),
                    allowed_prompt_numeric_tokens=allowed_prompt_numeric_tokens,
                )
        if validation_errors:
            repaired_plan = _repair_grounding_used_fact_ids(answer_plan, validation_errors)
            if repaired_plan is not None:
                repaired_errors = validate_answer_grounding(
                    repaired_plan,
                    advisory_context,
                    education_only=bool(state.get("education_only")),
                    allowed_prompt_numeric_tokens=allowed_prompt_numeric_tokens,
                )
                if not repaired_errors:
                    answer_plan = repaired_plan
                    validation_errors = []
                    response_meta["reason_codes"].append("grounding_used_fact_ids_repaired")
                else:
                    validation_errors = repaired_errors

        if validation_errors:
            response_meta["reason_codes"].extend(validation_errors)
            fallback_used = "grounding_failed"
        else:
            state["answer_plan_v2"] = answer_plan.model_dump(exclude_none=True)
            llm_body = render_answer_plan(answer_plan, advisory_context)
            response_meta["validation_passed"] = True
            response_meta["used_fact_ids"] = list(answer_plan.used_fact_ids)
            response_meta["used_insight_ids"] = list(answer_plan.used_insight_ids)
            response_meta["used_action_ids"] = list(answer_plan.used_action_ids)
            response_meta["disclaimer_effective"] = str(answer_plan.disclaimer or default_disclaimer).strip() or default_disclaimer

    if not llm_body:
        response_meta["fallback_used"] = fallback_used or "facts_only_compact_renderer"
        llm_body = render_facts_only_compact_response(
            advisory_context,
            language=language,
            disclaimer=response_meta["disclaimer_effective"],
        )

    response_meta["latency_ms"] = int((time.perf_counter() - synthesis_start) * 1000)
    response_meta["reason_codes"] = sorted(set(str(item) for item in response_meta["reason_codes"] if str(item).strip()))

    if mode == "llm_shadow":
        legacy_body = _legacy_reasoning_body(state, vietnamese)
        state["response_meta"] = {
            **response_meta,
            "shadow": {
                "enabled": True,
                "validation_passed": response_meta["validation_passed"],
                "fallback_used": response_meta["fallback_used"],
                "used_fact_ids": response_meta["used_fact_ids"],
                "used_insight_ids": response_meta["used_insight_ids"],
                "used_action_ids": response_meta["used_action_ids"],
            },
        }
        state["response"] = _finalize_response(legacy_body, citations, state["trace_id"], tool_chain)
        return state

    state["response_meta"] = response_meta
    state["response"] = _finalize_response(llm_body, citations, state["trace_id"], tool_chain)
    return state


def memory_update(state: AgentState) -> AgentState:
    routing_meta = {
        "intent": state.get("intent", ""),
        "extraction": state.get("extraction", {}),
        "route_decision": state.get("route_decision", {}),
        "clarification": state.get("clarification", {}),
        "encoding_meta": state.get("encoding_meta", {}),
        "user_profile": state.get("user_profile", {}),
    }
    payload = {
        "summary": state.get("response", ""),
        "tool_calls": state.get("tool_calls", []),
        "routing_meta": routing_meta,
        "encoding_meta": state.get("encoding_meta", {}),
        "response_meta": state.get("response_meta", {}),
        "evidence_pack": state.get("evidence_pack", {}),
        "advisory_context": state.get("advisory_context", {}),
        "answer_plan_v2": state.get("answer_plan_v2", {}),
        "user_profile": state.get("user_profile", {}),
    }
    audit_write(state["user_id"], state["trace_id"], payload, state["user_token"])
    return state


def build_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("encoding_gate", encoding_gate)
    graph.add_node("intent_router", intent_router)
    graph.add_node("suitability_guard", suitability_guard)
    graph.add_node("fetch_context", fetch_context)
    graph.add_node("retrieve_kb", retrieve_kb)
    graph.add_node("decision_engine", decision_engine)
    graph.add_node("reasoning", reasoning)
    graph.add_node("memory_update", memory_update)

    graph.set_entry_point("encoding_gate")
    graph.add_conditional_edges(
        "encoding_gate",
        lambda state: "memory_update" if state.get("response") else "intent_router",
        {
            "memory_update": "memory_update",
            "intent_router": "intent_router",
        },
    )
    graph.add_edge("intent_router", "suitability_guard")
    graph.add_edge("suitability_guard", "fetch_context")
    graph.add_edge("fetch_context", "retrieve_kb")
    graph.add_edge("retrieve_kb", "decision_engine")
    graph.add_edge("decision_engine", "reasoning")
    graph.add_edge("reasoning", "memory_update")
    graph.add_edge("memory_update", END)

    return graph.compile()


def run_agent(prompt: str, user_token: str, user_id: str) -> Dict[str, Any]:
    trace_id = f"trc_{uuid.uuid4().hex[:8]}"
    graph = build_graph()
    state = graph.invoke(
        {
            "prompt": prompt,
            "user_token": user_token,
            "user_id": user_id,
            "intent": "",
            "scenario_request": {},
            "context": {},
            "kb": {},
            "tool_outputs": {},
            "tool_calls": [],
            "education_only": False,
            "user_profile": {"risk_appetite": "unknown"},
            "extraction": {},
            "route_decision": {},
            "clarification": {"pending": False, "round": 0, "max_questions": ROUTER_MAX_CLARIFY_QUESTIONS},
            "encoding_meta": {},
            "evidence_pack": {},
            "advisory_context": {},
            "answer_plan_v2": {},
            "response_meta": {
                "mode": _response_mode(),
                "model_id": "",
                "prompt_version": RESPONSE_PROMPT_VERSION,
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "policy_version": RESPONSE_POLICY_VERSION,
                "validation_passed": False,
                "fallback_used": None,
                "used_fact_ids": [],
                "used_insight_ids": [],
                "used_action_ids": [],
                "latency_ms": 0,
                "reason_codes": [],
                "disclaimer_effective": DEFAULT_DISCLAIMER,
                "encoding_decision": "pass",
                "encoding_score": 0.0,
                "encoding_repair_applied": False,
                "encoding_reason_codes": [],
                "encoding_guess": "",
                "encoding_input_fingerprint": "",
            },
            "response": "",
            "trace_id": trace_id,
        }
    )
    return {
        "response": state["response"],
        "trace_id": trace_id,
        "citations": state.get("kb", {}),
        "tool_calls": state.get("tool_calls", []),
        "tool_outputs": state.get("tool_outputs", {}),
        "routing_meta": {
            "intent": state.get("intent", ""),
            "extraction": state.get("extraction", {}),
            "route_decision": state.get("route_decision", {}),
            "clarification": state.get("clarification", {}),
            "encoding_meta": state.get("encoding_meta", {}),
            "user_profile": state.get("user_profile", {}),
        },
        "response_meta": state.get("response_meta", {}),
    }


