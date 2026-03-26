from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

import graph as legacy_graph


def _format_citations(citations: Iterable[Any]) -> str:
    items: List[str] = []
    for citation in citations:
        if isinstance(citation, dict):
            value = str(citation.get("title") or citation.get("source_id") or citation.get("url") or "").strip()
        else:
            value = str(citation or "").strip()
        if value and value not in items:
            items.append(value)
    return ", ".join(items)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "insufficient_data", "not_applicable", "none", "null"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _section(contract: Dict[str, Any], section_name: str) -> Dict[str, Any]:
    sections = contract.get("sections") if isinstance(contract.get("sections"), dict) else {}
    payload = sections.get(section_name) if isinstance(sections.get(section_name), dict) else {}
    return payload if isinstance(payload, dict) else {}


def _append_bullets(lines: List[str], heading: str, items: Iterable[str]) -> None:
    bullet_lines = [str(item).strip() for item in items if str(item).strip()]
    if not bullet_lines:
        return
    lines.append(heading)
    lines.extend([f"- {item}" for item in bullet_lines])


def _clean_internal_text(text: Any) -> str:
    rendered = str(text or "").strip()
    if not rendered:
        return ""
    replacements = {
        "—": "-",
        "–": "-",
        "’": "'",
        "“": '"',
        "”": '"',
    }
    for source, target in replacements.items():
        rendered = rendered.replace(source, target)
    rendered = re.sub(
        r"\s*\((?=[^)]*(?:trust\s*=|usage\s*=|tool\s*=|tool_name|source\s*=|monitoring\s*=|caps\s*=|aic\s*=|bic\s*=|llf\s*=))[^)]*\)",
        "",
        rendered,
        flags=re.IGNORECASE,
    )
    rendered = re.sub(r"\s+", " ", rendered).strip()
    return rendered


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return _clean_internal_text(value)
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{round(numeric):,}"
    return f"{numeric:,.2f}".rstrip("0").rstrip(".")


def _format_percent(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return _clean_internal_text(value)
    if 0 <= numeric <= 1:
        return f"{numeric * 100:.1f}%"
    return f"{numeric:.1f}%"


def _friendly_financial_stability(value: Any) -> str:
    band = str(value or "").strip().lower()
    mapping = {
        "fragile": "A little fragile right now",
        "watch": "Needs a bit of watching",
        "stable": "Fairly stable",
        "insufficient_data": "Insufficient data",
    }
    return mapping.get(band, _clean_internal_text(value))


def _friendly_planning_readiness(value: Any) -> str:
    band = str(value or "").strip().lower()
    mapping = {
        "ready": "Ready",
        "cautious": "Cautious for now",
        "policy_constrained": "Constrained by policy",
        "insufficient_data": "Insufficient data",
    }
    return mapping.get(band, _clean_internal_text(value))


def _big_picture_stability_sentence(value: Any) -> str:
    band = str(value or "").strip().lower()
    mapping = {
        "fragile": "Right now, your finances look a little fragile.",
        "watch": "Right now, your finances look okay, but they need a bit of watching.",
        "stable": "Right now, your finances look fairly stable.",
    }
    return mapping.get(band, "")


def _big_picture_readiness_sentence(value: Any) -> str:
    band = str(value or "").strip().lower()
    mapping = {
        "ready": "You have room to plan more confidently from here.",
        "cautious": "It makes sense to plan a bit cautiously for now.",
        "policy_constrained": "A few policy constraints mean the plan should stay conservative for now.",
    }
    return mapping.get(band, "")


def _humanize_signal_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    mapping = {
        "positive_observed_cashflow": "observed cashflow stayed positive",
        "negative_observed_cashflow": "recent cashflow has been negative",
        "no_active_budget_overrun_detected": "no active budget overrun is showing",
        "budget_overrun_detected": "some categories appear to be running over budget",
        "high_fixed_cost_ratio": "fixed costs are taking up a large share of spending",
        "high_non_investment_risk": "non-investment risk is elevated",
        "concentrated_spend_distribution": "spending is concentrated in a few categories",
        "merchant_spike": "an unusual spike with one merchant",
        "category_spike": "an unusual spike in one spending category",
        "income_drop": "income appears to have dropped",
        "low_balance_risk": "balances may be running a bit tight",
    }
    return mapping.get(code, str(value or "").strip().replace("_", " "))


def _friendly_budget_drift(value: Any) -> str:
    if isinstance(value, list) and value:
        statuses = {str((item or {}).get("status") or "").strip().lower() for item in value if isinstance(item, dict)}
        if "over" in statuses:
            return "Some categories are drifting over budget."
        if "on_track" in statuses:
            return "Budget tracking still looks reasonably on track."
        rendered = _compact_list(value, limit=3)
        return _clean_internal_text(rendered)
    if _has_value(value):
        return _clean_internal_text(value)
    return ""


def _friendly_top_categories(value: Any, limit: int = 3) -> str:
    if not isinstance(value, list) or not value:
        return ""
    parts: List[str] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("category_name") or item.get("name") or item.get("category") or "").strip()
        amount = item.get("amount")
        if name and _has_value(amount):
            parts.append(f"{name} ({_format_number(amount)})")
        elif name:
            parts.append(name)
    return ", ".join(parts)


def _compact_dict_item(item: Dict[str, Any]) -> str:
    preferred_keys = (
        "title",
        "name",
        "category",
        "merchant",
        "service_category",
        "tool_name",
        "jar_name",
        "goal_name",
        "action",
        "code",
        "status",
        "decision",
        "why",
        "message",
    )
    parts: List[str] = []
    for key in preferred_keys:
        value = item.get(key)
        if _has_value(value):
            label = key.replace("_", " ")
            parts.append(f"{label}: {value}")
    if parts:
        return "; ".join(parts[:3])
    fallback_parts = [f"{key.replace('_', ' ')}: {value}" for key, value in item.items() if _has_value(value)]
    return "; ".join(fallback_parts[:3])


def _compact_list(items: Any, limit: int = 4) -> str:
    if not isinstance(items, list) or not items:
        return ""
    rendered: List[str] = []
    for item in items[:limit]:
        if isinstance(item, dict):
            text = _compact_dict_item(item)
        else:
            text = str(item).strip()
        if text:
            rendered.append(text)
    return ", ".join(rendered)


def _append_labeled(items: List[str], label: str, value: Any, *, suffix: str = ".") -> None:
    if not _has_value(value):
        return
    text = str(value).strip()
    if suffix and not text.endswith((".", "!", "?")):
        text = f"{text}{suffix}"
    items.append(f"{label}: {text}")


def _format_confidence_band(band: Any) -> str:
    if not isinstance(band, dict):
        return ""
    parts: List[str] = []
    for key in ("p10_avg", "p50_avg", "p90_avg"):
        if _has_value(band.get(key)):
            parts.append(f"{key}={band[key]}")
    return ", ".join(parts)


def _normalized_text_key(value: Any) -> str:
    rendered = _clean_internal_text(value).lower()
    rendered = re.sub(r"[^a-z0-9]+", " ", rendered)
    return rendered.strip()


def _dedupe_text_items(items: Iterable[str], *, limit: int | None = None) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _clean_internal_text(item)
        if not cleaned:
            continue
        key = _normalized_text_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _clip_text(value: Any, *, max_chars: int = 220) -> str:
    cleaned = _clean_internal_text(value)
    if len(cleaned) <= max_chars:
        return cleaned
    for marker in (". ", "; ", ": ", ", ", " ("):
        idx = cleaned.rfind(marker, 0, max_chars)
        if idx >= int(max_chars * 0.55):
            return cleaned[:idx].rstrip(" ,;:") + "."
    clipped = cleaned[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped}." if clipped else cleaned[:max_chars].rstrip(" ,;:") + "."


def _format_compact_amount(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return _clean_internal_text(value)
    absolute = abs(numeric)
    sign = "-" if numeric < 0 else ""
    if absolute >= 1_000_000:
        rendered = f"{absolute / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{rendered}M"
    if absolute >= 1_000:
        rendered = f"{absolute / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{rendered}K"
    return f"{numeric:.0f}"


def _complete_sentence(value: Any) -> str:
    cleaned = _clean_internal_text(value)
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _sentence_chunks(value: Any) -> List[str]:
    cleaned = _clean_internal_text(value)
    if not cleaned:
        return []
    chunks = re.split(r"(?<=[.!?])\s+", cleaned)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _first_sentences(value: Any, *, max_sentences: int = 1, max_chars: int = 240) -> str:
    sentences = _sentence_chunks(value)
    if not sentences:
        return _clip_text(value, max_chars=max_chars)
    rendered = " ".join(sentences[:max_sentences]).strip()
    return _clip_text(rendered, max_chars=max_chars)


def _lowercase_first(value: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        return ""
    return rendered[:1].lower() + rendered[1:]


def _recommendation_priority_rank(value: Any) -> int:
    priority = str(value or "").strip().lower()
    mapping = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return mapping.get(priority, 9)


def _recommendation_theme(item: Dict[str, Any]) -> str:
    haystack = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("rationale") or ""),
            str(item.get("expected_impact") or ""),
        ]
    ).lower()
    theme_checks = (
        ("fraud", ("fraud", "dispute", "unauthor", "circle k", "card compromise")),
        ("income", ("income", "payroll", "salary", "freelance")),
        ("liquidity", ("emergency", "runway", "liquidity", "buffer", "balance depletion")),
        ("spend", ("spend", "budget", "living jar", "misc", "grocery", "dining")),
        ("goal", ("goal", "saving", "savings automation")),
        ("alerts", ("anomaly", "alert", "confirm", "verification")),
    )
    for theme, markers in theme_checks:
        if any(marker in haystack for marker in markers):
            return theme
    title_key = _normalized_text_key(item.get("title") or "")
    return title_key or f"rec_{abs(hash(haystack)) % 10000}"


def _clean_recommendation_title(value: Any) -> str:
    title = _clean_internal_text(value)
    title = re.sub(r"^[^\w]+", "", title)
    title = re.sub(r"^(urgent|critical)\s*:\s*", lambda m: f"{m.group(1).title()}: ", title, flags=re.IGNORECASE)
    return title


def _recommendation_action(theme: str, item: Dict[str, Any]) -> str:
    title = _clean_recommendation_title(item.get("title"))
    lowered = title.lower()
    if theme == "fraud":
        if "circle k" in lowered or "merchant" in lowered:
            return "Review the flagged merchant spike immediately"
        return "Investigate and dispute suspicious transactions now"
    if theme == "income":
        return "Verify the recent income drop immediately"
    if theme == "liquidity":
        return "Start funding your Emergency jar first"
    if theme == "spend":
        if "jar" in lowered:
            return "Rebalance jar allocations"
        if "misc" in lowered or "discretionary" in lowered:
            return "Cut discretionary and Misc spending"
        return "Tighten spending in high-impact categories"
    if theme == "alerts":
        return "Review and confirm anomaly alerts"
    if theme == "goal":
        return "Keep goal-saving moves simple for now"
    return title or "Follow the highest-priority planner adjustment"


def _recommendation_reason(theme: str, item: Dict[str, Any]) -> str:
    rationale = _clean_internal_text(item.get("rationale"))
    impact = _clean_internal_text(item.get("expected_impact"))
    if theme == "fraud":
        return "suspicious charges are a major immediate drag on cashflow and may be recoverable."
    if theme == "income":
        return "if the drop is real, your runway could shrink quickly."
    if theme == "liquidity":
        return "the missing buffer leaves very little room for shocks while cashflow is under pressure."
    if theme == "spend":
        return "it is one of the clearest levers for stabilising monthly cashflow."
    if theme == "alerts":
        return "this helps separate true issues from false positives and improves future monitoring."
    if theme == "goal":
        return "it supports steady progress once your core cashflow is more stable."
    fallback = _first_sentences(impact or rationale, max_sentences=1, max_chars=140)
    return _lowercase_first(_complete_sentence(fallback)) if fallback else "it supports a steadier plan from here."


def _service_recommendation_bullet(item: Dict[str, Any]) -> str:
    category = str(item.get("service_category") or "").strip().lower()
    mapping = {
        "budget_controls_and_spend_limits": (
            "Tighten budget controls",
            "it helps slow budget drift before it becomes a bigger cashflow problem.",
        ),
        "transaction_alerts_and_manual_verification": (
            "Keep transaction alerts and manual checks on",
            "they make it easier to catch suspicious activity early.",
        ),
        "emergency_buffer_support": (
            "Prioritise emergency-buffer support",
            "a stronger buffer gives you more room to absorb shocks.",
        ),
        "goal_savings_automation": (
            "Use simple goal-savings automation",
            "it helps build consistency once monthly cashflow is steadier.",
        ),
    }
    payload = mapping.get(category)
    if not payload:
        return ""
    action, reason = payload
    return f"**{action}** - {reason}"


def _build_recommendation_bullets(
    recommendations: Any,
    service_recommendations: Any,
    *,
    limit: int = 4,
) -> List[str]:
    if not isinstance(recommendations, list):
        recommendations = []

    grouped: Dict[str, Dict[str, Any]] = {}
    ordered_groups: List[str] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        theme = _recommendation_theme(item)
        existing = grouped.get(theme)
        if existing is None or _recommendation_priority_rank(item.get("priority")) < _recommendation_priority_rank(existing.get("priority")):
            grouped[theme] = item
        if theme not in ordered_groups:
            ordered_groups.append(theme)

    bullets: List[str] = []
    for theme in sorted(
        ordered_groups,
        key=lambda key: (_recommendation_priority_rank(grouped.get(key, {}).get("priority")), ordered_groups.index(key)),
    ):
        item = grouped.get(theme) or {}
        action = _recommendation_action(theme, item)
        reason = _recommendation_reason(theme, item)
        if action and reason:
            bullets.append(f"**{action}** - {reason}")
        if len(bullets) >= limit:
            return bullets

    if isinstance(service_recommendations, list):
        for item in service_recommendations:
            if not isinstance(item, dict):
                continue
            bullet = _service_recommendation_bullet(item)
            if not bullet:
                continue
            deduped = _dedupe_text_items([*bullets, bullet], limit=limit + 1)
            if len(deduped) > len(bullets):
                bullets = deduped
            if len(bullets) >= limit:
                break

    return bullets[:limit]


def _warning_theme(message: str) -> str:
    lowered = str(message or "").lower()
    theme_checks = (
        ("fraud", ("fraud", "unauthor", "dispute", "counterparty")),
        ("income", ("income", "payroll", "salary")),
        ("runway", ("runway", "balance", "liquidity")),
        ("forecast", ("forecast", "directional", "prediction", "uncertainty", "trust score")),
        ("buffer", ("emergency jar", "emergency buffer")),
        ("anomaly", ("anomaly", "confirm", "alert", "outlier")),
    )
    for theme, markers in theme_checks:
        if any(marker in lowered for marker in markers):
            return theme
    return _normalized_text_key(message) or "warning"


def _warning_summary(theme: str, message: str) -> str:
    if theme == "fraud":
        return "Fraud-flagged transactions need immediate review and dispute."
    if theme == "income":
        return "Recent income appears far below baseline, so income receipts should be verified immediately."
    if theme == "runway":
        return "Cash runway looks short, and balance-based estimates should be checked against your real account balance."
    if theme == "forecast":
        return "Forecast and allocation signals are useful for direction, but not precise enough to treat as exact predictions."
    if theme == "buffer":
        return "The Emergency jar is still unfunded, leaving very little protection against shocks."
    if theme == "anomaly":
        return "Anomaly alerts still need your confirmation so the system can separate true issues from expected events."
    return _complete_sentence(_first_sentences(message, max_sentences=1, max_chars=180))


def _build_warning_bullets(human_readable: Dict[str, Any], evidence_grounding: Dict[str, Any], *, limit: int = 4) -> List[str]:
    warnings = human_readable.get("warnings")
    raw_messages: List[str] = []
    if isinstance(warnings, list) and warnings:
        for item in warnings:
            if isinstance(item, dict):
                message = _first_sentences(item.get("message"), max_sentences=1, max_chars=220)
            else:
                message = _first_sentences(item, max_sentences=1, max_chars=220)
            if message:
                raw_messages.append(message)
    else:
        caveats = evidence_grounding.get("caveats")
        if isinstance(caveats, list):
            for item in caveats:
                message = _first_sentences(item, max_sentences=1, max_chars=220)
                if message:
                    raw_messages.append(message)

    grouped: Dict[str, str] = {}
    for message in raw_messages:
        theme = _warning_theme(message)
        if theme not in grouped:
            grouped[theme] = _warning_summary(theme, message)
    ordered_themes = ("fraud", "income", "runway", "forecast", "buffer", "anomaly")
    ordered_messages = [grouped[theme] for theme in ordered_themes if theme in grouped]
    ordered_messages.extend([text for theme, text in grouped.items() if theme not in ordered_themes])
    return _dedupe_text_items(ordered_messages, limit=limit)


def _build_big_picture(
    *,
    header: Dict[str, Any],
    executive_summary: Dict[str, Any],
    human_readable: Dict[str, Any],
) -> str:
    income_total = _number(executive_summary.get("observed_income_total"))
    expense_total = _number(executive_summary.get("observed_expense_total"))
    net_cashflow = _number(executive_summary.get("observed_net_cashflow"))
    stability_band = executive_summary.get("computed_financial_stability_band")
    planning_readiness = executive_summary.get("computed_planning_readiness")
    warnings = human_readable.get("warnings") if isinstance(human_readable.get("warnings"), list) else []

    parts: List[str] = []
    if net_cashflow is not None and income_total is not None and expense_total is not None:
        if net_cashflow < 0:
            parts.append(
                f"Over this period, your finances ran at a deficit of {_format_number(abs(net_cashflow))}, with spending higher than income."
            )
        elif net_cashflow > 0:
            parts.append(
                f"Over this period, your finances stayed slightly positive, with income ahead of spending by {_format_number(net_cashflow)}."
            )
        else:
            parts.append("Over this period, income and spending were roughly balanced.")
    elif _has_value(human_readable.get("summary")):
        parts.append(_first_sentences(human_readable.get("summary"), max_sentences=2, max_chars=260))

    warning_messages = []
    for item in warnings:
        if not isinstance(item, dict):
            continue
        message = _clean_internal_text(item.get("message"))
        if message:
            warning_messages.append(message)
    lowered_warnings = " ".join(warning_messages).lower()
    concerns: List[str] = []
    if "fraud" in lowered_warnings or "unauthor" in lowered_warnings:
        concerns.append("likely fraudulent transactions")
    if "income" in lowered_warnings and "drop" in lowered_warnings:
        concerns.append("a sharp recent income drop")
    if "runway" in lowered_warnings or "balance" in lowered_warnings:
        concerns.append("a short cash runway")
    if concerns:
        if len(concerns) == 1:
            parts.append(f"The biggest concern is {concerns[0]}.")
        elif len(concerns) == 2:
            parts.append(f"The biggest concerns are {concerns[0]} and {concerns[1]}.")
        else:
            parts.append(f"The biggest concerns are {concerns[0]}, {concerns[1]}, and {concerns[2]}.")

    stability_sentence = _big_picture_stability_sentence(stability_band)
    readiness_sentence = _big_picture_readiness_sentence(planning_readiness)
    if stability_sentence:
        parts.append(stability_sentence)
    if readiness_sentence:
        parts.append(readiness_sentence)

    rendered = " ".join(part for part in parts if part).strip()
    return _clip_text(rendered, max_chars=420)


def _render_planner_standardized_contract(contract: Dict[str, Any], fallback_result: Dict[str, Any]) -> str:
    human_readable = _planner_human_readable_from_contract(contract)
    header = _section(contract, "HEADER")
    executive_summary = _section(contract, "EXECUTIVE_SUMMARY")
    core_analysis = _section(contract, "CORE_FINANCIAL_ANALYSIS")
    computed_signals = _section(contract, "PLANNER_CORE_COMPUTED_SIGNALS")
    usage_insight = _section(contract, "FINANCIAL_USAGE_INSIGHT")
    strategy_options = _section(contract, "STRATEGY_OPTIONS")
    service_recommendations = _section(contract, "BANKING_SERVICE_RECOMMENDATIONS")
    next_steps_section = _section(contract, "ACTIONABLE_NEXT_STEPS")
    evidence_grounding = _section(contract, "EVIDENCE_TOOL_GROUNDING")

    lines: List[str] = []
    observed_income = core_analysis.get("observed_income") if isinstance(core_analysis.get("observed_income"), dict) else {}
    observed_expenses = (
        core_analysis.get("observed_expenses") if isinstance(core_analysis.get("observed_expenses"), dict) else {}
    )
    observed_cashflow = (
        core_analysis.get("observed_cashflow") if isinstance(core_analysis.get("observed_cashflow"), dict) else {}
    )

    income_total = executive_summary.get("observed_income_total")
    if not _has_value(income_total):
        income_total = observed_income.get("total_income")

    expense_total = executive_summary.get("observed_expense_total")
    if not _has_value(expense_total):
        expense_total = observed_expenses.get("total_spend")

    net_cashflow = executive_summary.get("observed_net_cashflow")
    if not _has_value(net_cashflow):
        net_cashflow = observed_cashflow.get("net_cashflow")

    baseline_income = executive_summary.get("observed_baseline_monthly_income")
    if not _has_value(baseline_income):
        baseline_income = observed_income.get("baseline_monthly_income")

    stability_band = executive_summary.get("computed_financial_stability_band")
    planning_readiness = executive_summary.get("computed_planning_readiness")
    risk_band = executive_summary.get("computed_risk_band")

    lines.append("## Here's the big picture")
    lines.append(
        _build_big_picture(
            header=header,
            executive_summary=executive_summary,
            human_readable=human_readable,
        )
    )
    lines.append("")

    lines.append("## Snapshot")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    snapshot_rows = [
        ("Analysis window", _clean_internal_text(header.get("analysis_window_label"))),
        ("Total income", _format_number(income_total)),
        ("Total expenses", _format_number(expense_total)),
        ("Observed net cashflow", _format_number(net_cashflow)),
        ("Baseline monthly income", _format_number(baseline_income)),
        ("Financial stability", _friendly_financial_stability(stability_band)),
        ("Planning readiness", _friendly_planning_readiness(planning_readiness)),
    ]
    for label, value in snapshot_rows:
        if _has_value(value):
            lines.append(f"| {label} | {value} |")
    lines.append("")

    lines.append("## What stands out")
    standout_items: List[str] = []
    income_num = _number(income_total)
    expense_num = _number(expense_total)
    if income_num is not None and expense_num is not None:
        difference = expense_num - income_num
        if difference > 0:
            standout_items.append(
                f"Your expenses were higher than your income by about {_format_number(difference)} over this window."
            )
        elif difference < 0:
            standout_items.append(
                f"Your income stayed ahead of expenses by about {_format_number(abs(difference))} over this window."
            )
    budget_drift_text = ""
    expenses = observed_expenses
    if isinstance(expenses, dict):
        top_categories = _friendly_top_categories(expenses.get("category_breakdown"), limit=3)
        if top_categories:
            standout_items.append(f"Your biggest spending categories were {top_categories}.")
        budget_drift_text = _friendly_budget_drift(expenses.get("budget_drift"))
    anomaly = core_analysis.get("observed_anomaly")
    if isinstance(anomaly, dict):
        flags_value = anomaly.get("flags")
        if isinstance(flags_value, list) and flags_value:
            flags = ", ".join(_humanize_signal_code(item) for item in flags_value[:4] if str(item).strip())
            if flags:
                standout_items.append(f"The main unusual signals were {flags}.")
    positive_signals = ""
    if isinstance(usage_insight.get("positive_signals"), list):
        positive_signals = ", ".join(
            _humanize_signal_code(item)
            for item in usage_insight.get("positive_signals", [])[:3]
            if str(item).strip()
        )
    if positive_signals:
        standout_items.append(f"Positive signals: {positive_signals}.")
    attention_signals = ""
    if isinstance(usage_insight.get("attention_signals"), list):
        attention_signals = ", ".join(
            _humanize_signal_code(item)
            for item in usage_insight.get("attention_signals", [])[:3]
            if str(item).strip()
        )
    if attention_signals:
        standout_items.append(f"The main thing to watch is {attention_signals}.")
    elif budget_drift_text:
        standout_items.append(budget_drift_text)
    standout_items = _dedupe_text_items(standout_items, limit=5)
    lines.extend([f"- {item}" for item in standout_items])
    lines.append("")

    lines.append("## Forecast and risk outlook")
    forecast_items: List[str] = []
    cashflow = observed_cashflow
    if isinstance(cashflow, dict):
        forecast_probability = cashflow.get("forecast_probability_negative_net")
        if _has_value(forecast_probability):
            forecast_items.append(
                f"The forecast still leans negative, with about a {_format_percent(forecast_probability)} chance of negative cashflow."
            )
        band = cashflow.get("forecast_confidence_band")
        if isinstance(band, dict):
            p10 = band.get("p10_avg")
            p50 = band.get("p50_avg")
            p90 = band.get("p90_avg")
            if _has_value(p10) and _has_value(p50) and _has_value(p90):
                forecast_items.append(
                    f"The central forecast range is roughly {_format_compact_amount(p10)} to {_format_compact_amount(p90)}, with a midpoint near {_format_compact_amount(p50)}."
                )
    if _has_value(risk_band):
        forecast_items.append(f"Your current risk band is {_clean_internal_text(risk_band)}.")
    trust_core = computed_signals.get("trust_core")
    if isinstance(trust_core, dict):
        confidence = trust_core.get("mean_confidence_score")
        trust = trust_core.get("mean_trust_score")
        if _has_value(confidence) or _has_value(trust):
            confidence_text = _format_number(confidence) if _has_value(confidence) else "n/a"
            trust_text = _format_number(trust) if _has_value(trust) else "n/a"
            forecast_items.append(
                f"Planner confidence is around {confidence_text} and overall trust is around {trust_text}, so treat the forecast as directional only."
            )
    forecast_items = _dedupe_text_items(forecast_items, limit=4)
    lines.extend([f"- {item}" for item in forecast_items])
    lines.append("")

    strategy_items: List[str] = []
    for option_name in ("conservative", "balanced", "growth"):
        option = strategy_options.get(option_name)
        if not isinstance(option, dict):
            continue
        focus = _clean_internal_text(option.get("focus"))
        rationale = _clean_internal_text(option.get("rationale"))
        confidence = _clean_internal_text(option.get("confidence"))
        status = _clean_internal_text(option.get("status"))
        label = option_name.replace("_", " ").title()
        parts = [part for part in [focus, rationale] if part]
        text = " ".join(parts)
        suffix_parts = []
        if confidence:
            suffix_parts.append(f"confidence: {confidence}")
        if status and status != "active":
            suffix_parts.append(f"status: {status}")
        suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
        if text:
            strategy_items.append(f"{label}: {text}{suffix}")
    strategy_items = _dedupe_text_items(strategy_items, limit=3)
    if strategy_items:
        lines.append("## Strategy options")
        lines.extend([f"- {item}" for item in strategy_items])
        lines.append("")

    recommendations = human_readable.get("recommendations", [])
    recommendations_section = service_recommendations.get("recommendations")
    recommendation_bullets = _build_recommendation_bullets(recommendations, recommendations_section, limit=4)
    if recommendation_bullets:
        lines.append("## Recommendations")
        lines.extend([f"- {item}" for item in recommendation_bullets])
        lines.append("")

    rendered_next_steps = False
    steps = next_steps_section.get("steps")
    if isinstance(steps, list) and steps:
        lines.append("## Next steps")
        rendered_steps = 0
        for step in steps[:5]:
            if not isinstance(step, dict):
                continue
            action = _clean_internal_text(step.get("action"))
            timeframe = _clean_internal_text(step.get("timeframe"))
            suffix = timeframe if _has_value(timeframe) else ""
            text = f"{action} ({suffix})" if action and suffix else action or suffix
            if text:
                lines.append(f"- {text}")
                rendered_next_steps = True
                rendered_steps += 1
                if rendered_steps >= 4:
                    break
    if not rendered_next_steps:
        next_actions = human_readable.get("next_actions", [])
        if isinstance(next_actions, list) and next_actions:
            lines.append("## Next steps")
            rendered_steps = 0
            for action in next_actions:
                if not isinstance(action, dict):
                    continue
                text = _clean_internal_text(action.get("action"))
                timeframe = _clean_internal_text(action.get("timeframe"))
                suffix = timeframe if _has_value(timeframe) else ""
                if suffix:
                    text = f"{text} ({suffix})" if text else suffix
                if text:
                    lines.append(f"- {text}")
                    rendered_steps += 1
                    if rendered_steps >= 4:
                        break
    if rendered_next_steps or (isinstance(human_readable.get("next_actions"), list) and human_readable.get("next_actions")):
        lines.append("")

    deduped_notes = _build_warning_bullets(human_readable, evidence_grounding, limit=4)
    if deduped_notes:
        lines.append("## Notes and cautions")
        lines.extend([f"- {item}" for item in deduped_notes])

    return "\n".join([line for line in lines if line])


def _render_planner_result(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.append(summary)

    key_facts = [str(item).strip() for item in result.get("key_facts", []) if str(item).strip()]
    if key_facts:
        lines.append("Key facts:")
        lines.extend([f"- {fact}" for fact in key_facts])

    recommendations = result.get("recommendations", [])
    if isinstance(recommendations, list) and recommendations:
        lines.append("Recommendations:")
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            title = str(rec.get("title") or "").strip()
            rationale = str(rec.get("rationale") or "").strip()
            priority = str(rec.get("priority") or "").strip()
            impact = str(rec.get("expected_impact") or "").strip()
            parts = [part for part in [title, rationale] if part]
            text = " - ".join(parts) if parts else ""
            if priority:
                text = f"{text} (priority: {priority})" if text else f"priority: {priority}"
            if impact:
                text = f"{text}. Impact: {impact}" if text else f"Impact: {impact}"
            if text:
                lines.append(f"- {text}")

    next_actions = result.get("next_actions", [])
    if isinstance(next_actions, list) and next_actions:
        lines.append("Next actions:")
        for action in next_actions:
            if not isinstance(action, dict):
                continue
            text = str(action.get("action") or "").strip()
            owner = str(action.get("owner") or "").strip()
            timeframe = str(action.get("timeframe") or "").strip()
            suffix = ", ".join([part for part in [owner, timeframe] if part])
            if suffix:
                text = f"{text} ({suffix})" if text else suffix
            if text:
                lines.append(f"- {text}")

    warnings = result.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            code = str(warning.get("code") or "").strip()
            message = str(warning.get("message") or "").strip()
            text = f"{code}: {message}" if code and message else message or code
            if text:
                lines.append(f"- {text}")

    return "\n".join([line for line in lines if line])


def _planner_human_readable_from_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
    payload = contract.get("human_readable") if isinstance(contract.get("human_readable"), dict) else {}
    return payload if isinstance(payload, dict) else {}


def _render_stock_result(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.append(summary)

    recommendations = result.get("recommendations", [])
    if isinstance(recommendations, list) and recommendations:
        lines.append("Recommendations:")
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            ticker = str(rec.get("ticker") or "").strip()
            action = str(rec.get("action") or "").strip()
            rationale = str(rec.get("rationale") or "").strip()
            risk = str(rec.get("risk_level") or "").strip()
            parts = [part for part in [ticker, action] if part]
            headline = " / ".join(parts)
            text_parts = [headline, rationale] if headline or rationale else []
            text = " - ".join([part for part in text_parts if part])
            if risk:
                text = f"{text} (risk: {risk})" if text else f"risk: {risk}"
            if text:
                lines.append(f"- {text}")

    alternatives = result.get("alternatives", [])
    if isinstance(alternatives, list) and alternatives:
        lines.append("Alternatives:")
        for alt in alternatives:
            if not isinstance(alt, dict):
                continue
            ticker = str(alt.get("ticker") or "").strip()
            rationale = str(alt.get("rationale") or "").strip()
            text = " - ".join([part for part in [ticker, rationale] if part])
            if text:
                lines.append(f"- {text}")

    notes = [str(item).strip() for item in result.get("market_notes", []) if str(item).strip()]
    if notes:
        lines.append("Market notes:")
        lines.extend([f"- {note}" for note in notes])

    warnings = result.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            code = str(warning.get("code") or "").strip()
            message = str(warning.get("message") or "").strip()
            text = f"{code}: {message}" if code and message else message or code
            if text:
                lines.append(f"- {text}")

    return "\n".join([line for line in lines if line])


_SERVICE_GOAL_LABELS = {
    "vehicle_purchase": "Vehicle purchase",
    "emergency_fund": "Emergency fund",
    "home_purchase": "Home purchase",
    "travel": "Travel goal",
    "education": "Education goal",
    "wedding": "Wedding goal",
    "general_savings": "Savings goal",
}

_SERVICE_PHASE_LABELS = {
    "stabilize": "Stabilize your cash flow",
    "protect_liquidity": "Protect your cash flow",
    "accumulate": "Build steady contributions",
    "readiness_review": "Review your pace",
    "maturity_transition": "Prepare for the transition",
}


def _service_goal_label(value: Any) -> str:
    key = _clean_internal_text(value).lower()
    if not key:
        return ""
    return _SERVICE_GOAL_LABELS.get(key, key.replace("_", " ").title())


def _service_phase_label(value: Any) -> str:
    key = _clean_internal_text(value).lower()
    if not key:
        return ""
    return _SERVICE_PHASE_LABELS.get(key, key.replace("_", " ").title())


def _service_amount_label(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return _clean_internal_text(value)
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{round(numeric):,} VND"
    return f"{numeric:,.2f}".rstrip("0").rstrip(".") + " VND"


def _polish_service_text(value: Any) -> str:
    text = _clean_internal_text(value)
    if not text:
        return ""
    replacements = {
        "protect_liquidity": "protect your cash flow",
        "protect liquidity": "protect your cash flow",
        "readiness_review": "review your pace",
        "readiness review": "review your pace",
        "maturity_transition": "prepare for the transition",
        "maturity transition": "prepare for the transition",
        "journey pattern": "roadmap path",
        "cashflow": "cash flow",
        "â‚¦": "VND ",
        "₦": "VND ",
        "₫": "VND ",
    }
    for source, target in replacements.items():
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    text = re.sub(r"\bVND\s+", "VND ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _render_service_result(envelope: Dict[str, Any]) -> str:
    contract = envelope.get("roadmap_contract") if isinstance(envelope.get("roadmap_contract"), dict) else {}
    explanation = envelope.get("explanation") if isinstance(envelope.get("explanation"), dict) else {}
    lines: List[str] = []

    summary = _polish_service_text(
        explanation.get("summary")
        or ((envelope.get("result") or {}).get("summary") if isinstance(envelope.get("result"), dict) else "")
        or envelope.get("summary")
    )
    if summary:
        lines.append(summary)

    goal = contract.get("goal") if isinstance(contract.get("goal"), dict) else {}
    current_phase = _service_phase_label(contract.get("current_phase"))
    phase_sequence = contract.get("phase_sequence") if isinstance(contract.get("phase_sequence"), list) else []
    next_best_action = contract.get("next_best_action") if isinstance(contract.get("next_best_action"), dict) else {}
    milestones = contract.get("milestones") if isinstance(contract.get("milestones"), list) else []

    if goal:
        goal_bits: List[str] = []
        goal_type = _service_goal_label(goal.get("goal_type"))
        target_amount = goal.get("target_amount")
        timeline = goal.get("target_timeline_months")
        if goal_type:
            goal_bits.append(f"Goal: {goal_type}")
        if _has_value(target_amount):
            goal_bits.append(f"Target: {_service_amount_label(target_amount)}")
        if _has_value(timeline):
            goal_bits.append(f"Timeline: {_format_number(timeline)} months")
        if goal_bits:
            lines.append("")
            lines.append("Roadmap at a glance:")
            lines.extend([f"- {item}" for item in goal_bits])

    snapshot_bits: List[str] = []
    if current_phase:
        snapshot_bits.append(f"Current focus: {current_phase}")
    if phase_sequence:
        rendered_phases = " -> ".join([_service_phase_label(item) for item in phase_sequence if _service_phase_label(item)])
        if rendered_phases:
            snapshot_bits.append(f"Roadmap path: {rendered_phases}")
    if snapshot_bits:
        if "Roadmap at a glance:" not in lines:
            lines.append("")
            lines.append("Roadmap at a glance:")
        lines.extend([f"- {item}" for item in snapshot_bits])

    why_fit = _polish_service_text(explanation.get("why_fit"))
    current_phase_explanation = _polish_service_text(explanation.get("current_phase_explanation"))
    if why_fit or current_phase_explanation:
        lines.append("")
        lines.append("Why this path fits:")
        if why_fit:
            lines.append(f"- {why_fit}")
        if current_phase_explanation:
            lines.append(f"- {current_phase_explanation}")

    next_action_explanation_payload = explanation.get("next_action_explanation")
    if isinstance(next_action_explanation_payload, dict):
        next_action_explanation = _polish_service_text(next_action_explanation_payload.get("why_now"))
    else:
        next_action_explanation = _polish_service_text(next_action_explanation_payload)
    if isinstance(next_best_action, dict) or next_action_explanation:
        title = _polish_service_text(next_best_action.get("title")) if isinstance(next_best_action, dict) else ""
        why = _polish_service_text(next_best_action.get("why")) if isinstance(next_best_action, dict) else ""
        timeframe = _clean_internal_text(next_best_action.get("timeframe"))
        text = title
        if timeframe:
            text = f"{text} ({timeframe})" if text else timeframe
        if text:
            lines.append("")
            lines.append("What to do next:")
            lines.append(f"- {text}")
        why_now = next_action_explanation or why
        if why_now:
            if "What to do next:" not in lines:
                lines.append("")
                lines.append("What to do next:")
            lines.append(f"- Why now: {why_now}")

    rendered_milestones: List[str] = []
    visible_milestones = [
        item
        for item in milestones
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() != "completed"
    ]
    for item in visible_milestones[:4]:
        if not isinstance(item, dict):
            continue
        title = _clean_internal_text(item.get("title"))
        status = _clean_internal_text(item.get("status")).lower()
        prefix = "Now" if status == "current" else "Next"
        if title:
            rendered_milestones.append(f"{prefix}: {title}")
    if rendered_milestones:
        lines.append("")
        lines.append("Milestones ahead:")
        lines.extend([f"- {item}" for item in rendered_milestones])

    cautions = explanation.get("cautions") if isinstance(explanation.get("cautions"), list) else []
    caution_lines = _dedupe_text_items([_polish_service_text(item) for item in cautions], limit=2)
    if caution_lines:
        lines.append("")
        lines.append("Keep in mind:")
        lines.extend([f"- {item}" for item in caution_lines])

    return "\n".join([line for line in lines if line])


def _build_response_meta(state: Dict[str, Any], envelope: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
    existing_meta = state.get("response_meta") if isinstance(state.get("response_meta"), dict) else {}
    encoding_reason_codes = existing_meta.get("encoding_reason_codes")
    if not isinstance(encoding_reason_codes, list):
        encoding_reason_codes = []

    reason_codes = [
        str(code).strip()
        for code in existing_meta.get("reason_codes", [])
        if str(code).strip()
    ]
    reason_codes.append(f"specialist:{agent_id}")

    status = str(envelope.get("status") or "").strip().lower()
    if status:
        reason_codes.append(f"specialist_status:{status}")

    standardized_contract = envelope.get("standardized_contract") if isinstance(envelope.get("standardized_contract"), dict) else {}
    if agent_id == "planner" and standardized_contract:
        reason_codes.append("planner_standardized_contract")
    if agent_id == "service" and isinstance(envelope.get("roadmap_contract"), dict):
        reason_codes.append("service_roadmap_contract")

    response_meta: Dict[str, Any] = {
        "mode": legacy_graph._response_mode(),
        "model_id": "",
        "prompt_version": legacy_graph.RESPONSE_PROMPT_VERSION,
        "schema_version": legacy_graph.RESPONSE_SCHEMA_VERSION,
        "policy_version": legacy_graph.RESPONSE_POLICY_VERSION,
        "validation_passed": True,
        "fallback_used": None,
        "used_fact_ids": [],
        "used_insight_ids": [],
        "used_action_ids": [],
        "latency_ms": 0,
        "reason_codes": sorted(set(reason_codes)),
        "disclaimer_effective": legacy_graph._resolve_required_disclaimer(state),  # type: ignore[attr-defined]
        "encoding_decision": str(existing_meta.get("encoding_decision") or "pass"),
        "encoding_score": float(existing_meta.get("encoding_score") or 0.0),
        "encoding_repair_applied": bool(existing_meta.get("encoding_repair_applied") or False),
        "encoding_reason_codes": [str(code) for code in encoding_reason_codes if str(code).strip()],
        "encoding_guess": str(existing_meta.get("encoding_guess") or ""),
        "encoding_input_fingerprint": str(existing_meta.get("encoding_input_fingerprint") or ""),
        "tool_errors": state.get("tool_errors", {}) if isinstance(state.get("tool_errors"), dict) else {},
        "specialist": {
            "agent_id": envelope.get("agent_id") or agent_id,
            "agent_version": envelope.get("agent_version"),
            "tool_name": envelope.get("tool_name"),
            "schema_version": envelope.get("schema_version"),
            "status": envelope.get("status"),
            "correlation": envelope.get("correlation"),
        },
    }
    if standardized_contract:
        response_meta["specialist"]["standardized_contract"] = {
            "contract_spec_version": standardized_contract.get("contract_spec_version"),
            "txt_render_spec_version": standardized_contract.get("txt_render_spec_version"),
        }
    if agent_id == "service" and isinstance(envelope.get("roadmap_contract"), dict):
        roadmap_contract = envelope.get("roadmap_contract") or {}
        response_meta["specialist"]["roadmap_contract"] = {
            "schema_version": roadmap_contract.get("schema_version"),
            "status": roadmap_contract.get("status"),
            "current_phase": roadmap_contract.get("current_phase"),
        }

    if status in {"partial", "error", "blocked"}:
        response_meta["fallback_used"] = "specialist_partial"

    return response_meta


def apply_specialist_response(state: Dict[str, Any]) -> Dict[str, Any]:
    if state.get("response"):
        return state

    agent_outputs = state.get("agent_outputs")
    if not isinstance(agent_outputs, dict):
        return state

    agent_id = ""
    envelope: Dict[str, Any] | None = None
    selected_specialist_id = str(state.get("selected_specialist_id") or "").strip().lower()
    if selected_specialist_id in {"planner", "service", "stock"} and isinstance(agent_outputs.get(selected_specialist_id), dict):
        agent_id = selected_specialist_id
        envelope = agent_outputs[selected_specialist_id]
    elif isinstance(agent_outputs.get("planner"), dict):
        agent_id = "planner"
        envelope = agent_outputs["planner"]
    elif isinstance(agent_outputs.get("service"), dict):
        agent_id = "service"
        envelope = agent_outputs["service"]
    elif isinstance(agent_outputs.get("stock"), dict):
        agent_id = "stock"
        envelope = agent_outputs["stock"]

    if not envelope:
        return state

    result = envelope.get("result") if isinstance(envelope.get("result"), dict) else {}
    standardized_contract = envelope.get("standardized_contract") if isinstance(envelope.get("standardized_contract"), dict) else {}
    if agent_id == "planner":
        if standardized_contract:
            body = _render_planner_standardized_contract(standardized_contract, result)
        else:
            body = _render_planner_result(result)
        planner_summary = str(result.get("summary") or envelope.get("summary") or "").strip()
        planner_context: Dict[str, Any] = {}
        if planner_summary:
            planner_context["planner_summary"] = planner_summary
        if standardized_contract:
            planner_context["planner_standardized_contract"] = standardized_contract
        if planner_context:
            state["planner_context"] = planner_context
    elif agent_id == "service":
        body = _render_service_result(envelope)
        roadmap_contract = envelope.get("roadmap_contract") if isinstance(envelope.get("roadmap_contract"), dict) else {}
        if roadmap_contract:
            state["roadmap_payload"] = roadmap_contract
    elif agent_id == "stock":
        body = _render_stock_result(result)
    else:
        body = str(envelope.get("summary") or "").strip()

    disclaimer = legacy_graph._resolve_required_disclaimer(state)  # type: ignore[attr-defined]
    if disclaimer and disclaimer not in body:
        body = f"{body}\n\n{disclaimer}" if body else disclaimer

    state["response_meta"] = _build_response_meta(state, envelope, agent_id)
    state["response"] = body.strip()
    return state


__all__ = ["apply_specialist_response"]
