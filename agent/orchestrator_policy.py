from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import unicodedata
from typing import Any, Callable


ORCHESTRATOR_POLICY_VERSION = "v1"
HEURISTIC_RECOVERY_POLICY_VERSION = "v1"


@dataclass(frozen=True)
class ScenarioVariant:
    name: str
    scenario_overrides: dict[str, float]


@dataclass(frozen=True)
class TimeframeWindowPolicy:
    default_value: int
    min_value: int
    max_value: int


@dataclass(frozen=True)
class HeuristicRecoveryRule:
    rule_id: str
    owner: str
    classification: str
    target_intent: str
    evaluator: Callable[[str, str], bool]


@dataclass(frozen=True)
class DegradationPolicyEntry:
    app_env: str
    owner: str
    tool_unavailable_fallback_enabled: bool
    clarification_fallback: str
    template_fallback: str
    llm_failure_fallback: str
    grounding_failure_fallback: str
    facts_only_fallback: str
    default_response_mode: str
    allowed_response_modes: tuple[str, ...]


DEFAULT_SCENARIO_HORIZON_MONTHS = 12
SCENARIO_VARIANTS: tuple[ScenarioVariant, ...] = (
    ScenarioVariant("cut_discretionary_spend_15pct", {"spend_delta_pct": -0.15}),
    ScenarioVariant("increase_income_10pct", {"income_delta_pct": 0.10}),
    ScenarioVariant("balanced_income_up5_spend_down10", {"income_delta_pct": 0.05, "spend_delta_pct": -0.10}),
)

SUMMARY_RANGE_DEFAULT_DAYS = {
    "summary": 30,
    "risk": 90,
    "planning": 30,
    "scenario": 30,
    "invest": 30,
    "out_of_scope": 30,
}
LOOKBACK_DAY_POLICIES = {
    "anomaly_signals_v1": TimeframeWindowPolicy(default_value=90, min_value=30, max_value=365),
    "risk_profile_non_investment_v1": TimeframeWindowPolicy(default_value=180, min_value=60, max_value=720),
}
LOOKBACK_MONTH_POLICIES = {
    "recurring_cashflow_detect_v1": TimeframeWindowPolicy(default_value=6, min_value=3, max_value=24),
}

DEGRADATION_POLICY_MATRIX = {
    "local": DegradationPolicyEntry(
        app_env="local",
        owner="platform-orchestrator",
        tool_unavailable_fallback_enabled=True,
        clarification_fallback="clarification_pending",
        template_fallback="template_mode",
        llm_failure_fallback="answer_synthesis_failed",
        grounding_failure_fallback="grounding_failed",
        facts_only_fallback="facts_only_compact_renderer",
        default_response_mode="llm_shadow",
        allowed_response_modes=("template", "llm_shadow", "llm_enforce"),
    ),
    "demo": DegradationPolicyEntry(
        app_env="demo",
        owner="platform-orchestrator",
        tool_unavailable_fallback_enabled=True,
        clarification_fallback="clarification_pending",
        template_fallback="template_mode",
        llm_failure_fallback="answer_synthesis_failed",
        grounding_failure_fallback="grounding_failed",
        facts_only_fallback="facts_only_compact_renderer",
        default_response_mode="llm_shadow",
        allowed_response_modes=("template", "llm_shadow", "llm_enforce"),
    ),
    "staging": DegradationPolicyEntry(
        app_env="staging",
        owner="platform-orchestrator",
        tool_unavailable_fallback_enabled=True,
        clarification_fallback="clarification_pending",
        template_fallback="template_mode",
        llm_failure_fallback="answer_synthesis_failed",
        grounding_failure_fallback="grounding_failed",
        facts_only_fallback="facts_only_compact_renderer",
        default_response_mode="llm_shadow",
        allowed_response_modes=("template", "llm_shadow", "llm_enforce"),
    ),
    "prod": DegradationPolicyEntry(
        app_env="prod",
        owner="platform-orchestrator",
        tool_unavailable_fallback_enabled=True,
        clarification_fallback="clarification_pending",
        template_fallback="template_mode",
        llm_failure_fallback="answer_synthesis_failed",
        grounding_failure_fallback="grounding_failed",
        facts_only_fallback="facts_only_compact_renderer",
        default_response_mode="llm_shadow",
        allowed_response_modes=("template", "llm_shadow", "llm_enforce"),
    ),
}


def default_scenario_variants() -> list[dict[str, Any]]:
    return [
        {
            "name": variant.name,
            "scenario_overrides": dict(variant.scenario_overrides),
        }
        for variant in SCENARIO_VARIANTS
    ]


def scenario_default_horizon_months() -> int:
    return DEFAULT_SCENARIO_HORIZON_MONTHS


def _normalize_prompt(prompt: str) -> str:
    base = str(prompt or "").replace("Ä‘", "d").replace("Ä", "D")
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", base) if unicodedata.category(ch) != "Mn"
    )
    return stripped.lower()


def _safe_int(raw: Any, default: int) -> int:
    try:
        if raw is None:
            return default
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _days_since_month_start(now_utc: datetime | None = None) -> int:
    ref = now_utc or _now_utc()
    month_start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(1, (ref - month_start).days + 1)


def _days_in_previous_month(now_utc: datetime | None = None) -> int:
    ref = now_utc or _now_utc()
    month_start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_last_day = month_start - timedelta(days=1)
    return max(1, int(prev_month_last_day.day))


def _days_since_quarter_start(now_utc: datetime | None = None) -> int:
    ref = now_utc or _now_utc()
    quarter_start_month = ((ref.month - 1) // 3) * 3 + 1
    quarter_start = ref.replace(month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(1, (ref - quarter_start).days + 1)


def _extract_requested_days(normalized_prompt: str) -> int:
    if not normalized_prompt:
        return 0

    explicit_day_patterns = (
        r"\b(\d{1,4})\s*(ngay|day|days)\b",
        r"\b(\d{1,4})d\b",
    )
    for pattern in explicit_day_patterns:
        match = re.search(pattern, normalized_prompt)
        if match:
            return max(1, _safe_int(match.group(1), 0))

    week_match = re.search(r"\b(\d{1,3})\s*(tuan|week|weeks|w)\b", normalized_prompt)
    if week_match:
        return max(1, _safe_int(week_match.group(1), 0) * 7)

    month_match = re.search(r"\b(\d{1,3})\s*(thang|month|months)\b", normalized_prompt)
    if month_match:
        return max(1, _safe_int(month_match.group(1), 0) * 30)

    year_match = re.search(r"\b(\d{1,2})\s*(nam|year|years)\b", normalized_prompt)
    if year_match:
        return max(1, _safe_int(year_match.group(1), 0) * 365)

    quarter_match = re.search(r"\b(\d{1,2})\s*(quy|quarter|quarters)\b", normalized_prompt)
    if quarter_match:
        return max(1, _safe_int(quarter_match.group(1), 0) * 90)

    if any(term in normalized_prompt for term in ["thang nay", "this month", "month to date", "mtd"]):
        return _days_since_month_start()
    if any(term in normalized_prompt for term in ["thang truoc", "last month", "previous month"]):
        return _days_in_previous_month()
    if any(term in normalized_prompt for term in ["quy nay", "this quarter"]):
        return _days_since_quarter_start()
    if any(term in normalized_prompt for term in ["gan day", "gan nhat", "recent", "lately"]):
        return 30
    return 0


def _extract_requested_months(normalized_prompt: str) -> int:
    if not normalized_prompt:
        return 0

    month_match = re.search(r"\b(\d{1,3})\s*(thang|month|months)\b", normalized_prompt)
    if month_match:
        return max(1, _safe_int(month_match.group(1), 0))

    year_match = re.search(r"\b(\d{1,2})\s*(nam|year|years)\b", normalized_prompt)
    if year_match:
        return max(1, _safe_int(year_match.group(1), 0) * 12)

    quarter_match = re.search(r"\b(\d{1,2})\s*(quy|quarter|quarters)\b", normalized_prompt)
    if quarter_match:
        return max(1, _safe_int(quarter_match.group(1), 0) * 3)

    days = _extract_requested_days(normalized_prompt)
    if days > 0:
        return max(1, (days + 29) // 30)

    if any(term in normalized_prompt for term in ["thang nay", "this month", "thang truoc", "last month", "previous month"]):
        return 1
    if any(term in normalized_prompt for term in ["quy nay", "this quarter"]):
        return 3
    if any(term in normalized_prompt for term in ["gan day", "gan nhat", "recent", "lately"]):
        return 1
    return 0


def _slot_range_days(slots: dict[str, Any] | None) -> int:
    if not isinstance(slots, dict):
        return 0
    for key in ["range_days", "summary_days", "lookback_days", "days"]:
        parsed = _safe_int(slots.get(key), 0)
        if parsed > 0:
            return parsed
    for key in ["range", "summary_range", "lookback_range"]:
        value = slots.get(key)
        if value is None:
            continue
        match = re.search(r"\d+", str(value))
        if match:
            parsed = _safe_int(match.group(0), 0)
            if parsed > 0:
                return parsed
    return 0


def _slot_lookback_months(slots: dict[str, Any] | None) -> int:
    if not isinstance(slots, dict):
        return 0
    for key in ["lookback_months", "months", "window_months"]:
        parsed = _safe_int(slots.get(key), 0)
        if parsed > 0:
            return parsed
    return 0


def resolve_summary_range(prompt: str, intent: str, slots: dict[str, Any] | None = None) -> str:
    normalized = _normalize_prompt(prompt)
    requested_days = _extract_requested_days(normalized)
    if requested_days <= 0:
        requested_days = _slot_range_days(slots)
    if requested_days <= 0:
        requested_days = SUMMARY_RANGE_DEFAULT_DAYS.get(str(intent or "").strip().lower(), SUMMARY_RANGE_DEFAULT_DAYS["summary"])
    requested_days = max(1, min(365, requested_days))
    return f"{requested_days}d"


def resolve_lookback_days(*, prompt: str, slots: dict[str, Any] | None, policy_key: str) -> int:
    policy = LOOKBACK_DAY_POLICIES[policy_key]
    requested_days = _extract_requested_days(_normalize_prompt(prompt))
    if requested_days <= 0:
        requested_days = _slot_range_days(slots)
    if requested_days <= 0:
        requested_days = policy.default_value
    return max(policy.min_value, min(policy.max_value, requested_days))


def resolve_lookback_months(*, prompt: str, slots: dict[str, Any] | None, policy_key: str) -> int:
    policy = LOOKBACK_MONTH_POLICIES[policy_key]
    requested_months = _extract_requested_months(_normalize_prompt(prompt))
    if requested_months <= 0:
        requested_months = _slot_lookback_months(slots)
    if requested_months <= 0:
        requested_months = policy.default_value
    return max(policy.min_value, min(policy.max_value, requested_months))


def _strip_accents(value: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _rule_scenario(flat: str, original: str) -> bool:
    scenario_markers = ("neu", "gia su", "what if", "what-if", "if i", "ra sao", "how would", "what would")
    delta_markers = ("giam", "tang", "delta", "%", "pct", "thay doi", "reduce", "increase", "cut")
    has_scenario = any(marker in flat for marker in scenario_markers)
    has_delta = any(marker in flat for marker in delta_markers)
    if not has_scenario and "%" in original and ("ra sao" in flat or "thay" in flat):
        has_scenario = True
        has_delta = True
    return has_scenario and has_delta


def _rule_risk(flat: str, _: str) -> bool:
    return any(marker in flat for marker in ("rui ro", "risk", "canh bao", "warning", "anomaly", "bat thuong"))


def _rule_planning(flat: str, _: str) -> bool:
    return any(marker in flat for marker in ("ke hoach", "muc tieu", "tiet kiem", "goal", "plan", "feasibility"))


def _rule_summary(flat: str, _: str) -> bool:
    return any(marker in flat for marker in ("summary", "overview", "tom tat", "tong quan", "spending", "cashflow", "chi tieu"))


def _rule_summary_window(flat: str, _: str) -> bool:
    return bool(re.search(r"\b(30|60|90)\b", flat)) and ("chi" in flat or "spend" in flat)


HEURISTIC_RECOVERY_RULES: tuple[HeuristicRecoveryRule, ...] = (
    HeuristicRecoveryRule("scenario_markers", "platform-orchestrator", "temporary_heuristic", "scenario", _rule_scenario),
    HeuristicRecoveryRule("risk_markers", "platform-orchestrator", "temporary_heuristic", "risk", _rule_risk),
    HeuristicRecoveryRule("planning_markers", "platform-orchestrator", "temporary_heuristic", "planning", _rule_planning),
    HeuristicRecoveryRule("summary_markers", "platform-orchestrator", "temporary_heuristic", "summary", _rule_summary),
    HeuristicRecoveryRule("summary_window_last_resort", "platform-orchestrator", "temporary_heuristic", "summary", _rule_summary_window),
)


def recover_intent_from_prompt(prompt: str) -> tuple[str | None, str]:
    text = str(prompt or "").strip().lower()
    if not text:
        return None, ""
    text_ascii = _strip_accents(text)
    flat = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9% ]+", " ", text_ascii)).strip()
    for rule in HEURISTIC_RECOVERY_RULES:
        if rule.evaluator(flat, text):
            return rule.target_intent, rule.rule_id
    return None, ""


def heuristic_rule_snapshot() -> list[dict[str, str]]:
    return [
        {
            "rule_id": rule.rule_id,
            "owner": rule.owner,
            "classification": rule.classification,
            "target_intent": rule.target_intent,
        }
        for rule in HEURISTIC_RECOVERY_RULES
    ]


def get_degradation_policy(app_env: str) -> DegradationPolicyEntry:
    normalized = str(app_env or "").strip().lower() or "local"
    return DEGRADATION_POLICY_MATRIX.get(normalized, DEGRADATION_POLICY_MATRIX["local"])
