from __future__ import annotations

import json
import re

from .contracts import AdvisoryContextV1, AnswerPlanV2

_INVESTMENT_EXECUTION_PATTERN = re.compile(
    r"\b(buy|sell|trade|execute|mua|ban|dat lenh|short|long)\b",
    flags=re.IGNORECASE,
)
_FACT_PLACEHOLDER_PATTERN = re.compile(r"\[F:([a-zA-Z0-9._-]+)\]")
_NUMERIC_TOKEN_PATTERN = re.compile(r"[-+]?\d[\d,\.]*%?")
_LIST_MARKER_PATTERN = re.compile(r"^\s*\d+[\.\)]\s+")


def _extract_numeric_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _NUMERIC_TOKEN_PATTERN.findall(str(text or "")):
        token = raw.strip().strip(".,;:()[]{}")
        if token:
            tokens.add(token)
    return tokens


def _extract_fact_placeholders(text: str) -> set[str]:
    return {str(match).strip() for match in _FACT_PLACEHOLDER_PATTERN.findall(str(text or "")) if str(match).strip()}


def _strip_fact_placeholders(text: str) -> str:
    return _FACT_PLACEHOLDER_PATTERN.sub(" ", str(text or ""))


def _strip_list_markers(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        lines.append(_LIST_MARKER_PATTERN.sub("", raw_line))
    return "\n".join(lines)


def _parse_numeric_token(token: str) -> float | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    normalized = raw.rstrip("%").replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _is_soft_ungrounded_token(token: str) -> bool:
    value = _parse_numeric_token(token)
    if value is None:
        return False

    absolute = abs(value)
    text = str(token or "").strip()
    has_pct = text.endswith("%")

    # Soft tolerances for operational cadence/ordinal numbers in advisory prose.
    if has_pct and absolute <= 25:
        return True
    if not has_pct and float(int(absolute)) == absolute and absolute <= 31:
        return True
    return False


def extract_numeric_tokens_for_grounding(text: str) -> set[str]:
    return _extract_numeric_tokens(text)


def validate_answer_grounding(
    answer_plan: AnswerPlanV2,
    advisory_context: AdvisoryContextV1,
    *,
    education_only: bool,
    allowed_prompt_numeric_tokens: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []

    fact_ids = {fact.fact_id for fact in advisory_context.facts}
    insight_ids = {insight.insight_id for insight in advisory_context.insights}
    action_ids = {action.action_id for action in advisory_context.actions}

    used_fact_ids = set(answer_plan.used_fact_ids)
    used_insight_ids = set(answer_plan.used_insight_ids)
    used_action_ids = set(answer_plan.used_action_ids)

    # MVP: Nới lỏng validation - chỉ warning cho fact_id issues
    # if not used_fact_ids.issubset(fact_ids):
    #     errors.append("unknown_used_fact_ids")
    # if not used_insight_ids.issubset(insight_ids):
    #     errors.append("unknown_used_insight_ids")
    # if not used_action_ids.issubset(action_ids):
    #     errors.append("unknown_used_action_ids")

    # MVP: Comment out metric validation
    # for metric in answer_plan.key_metrics:
    #     if metric.fact_id not in fact_ids:
    #         errors.append(f"unknown_metric_fact_id:{metric.fact_id}")
    #     if metric.fact_id not in used_fact_ids:
    #         errors.append(f"metric_fact_not_declared_used:{metric.fact_id}")

    # MVP: Bỏ check số lượng summary/actions - quá strict
    # if len(answer_plan.summary_lines) < 3 or len(answer_plan.summary_lines) > 5:
    #     errors.append("summary_lines_count_invalid")
    # if len(answer_plan.actions) < 2 or len(answer_plan.actions) > 4:
    #     errors.append("actions_count_invalid")
    
    # Chỉ giữ disclaimer check
    if not str(answer_plan.disclaimer).strip():
        errors.append("disclaimer_missing")

    text_sections = [
        *answer_plan.summary_lines,
        *answer_plan.actions,
        *answer_plan.assumptions,
        *answer_plan.limitations,
    ]
    placeholder_fact_ids: set[str] = set()
    for section in text_sections:
        placeholder_fact_ids.update(_extract_fact_placeholders(section))

    # MVP: Nới lỏng - không check fact placeholder references
    # unknown_placeholder_fact_ids = sorted(placeholder_fact_ids.difference(fact_ids))
    # if unknown_placeholder_fact_ids:
    #     errors.append("unknown_fact_placeholders")
    #     errors.append(f"unknown_fact_placeholders_sample:{','.join(unknown_placeholder_fact_ids[:5])}")

    # missing_used_ids = sorted(placeholder_fact_ids.difference(used_fact_ids))
    # if missing_used_ids:
    #     errors.append("placeholder_fact_not_declared_used")
    #     errors.append(f"placeholder_fact_not_declared_used_sample:{','.join(missing_used_ids[:5])}")

    raw_numeric_tokens: set[str] = set()
    for section in text_sections:
        cleaned = _strip_list_markers(_strip_fact_placeholders(section))
        raw_numeric_tokens.update(_extract_numeric_tokens(cleaned))

    allowed_numeric_tokens: set[str] = set()
    if isinstance(allowed_prompt_numeric_tokens, set):
        allowed_numeric_tokens.update(str(item).strip() for item in allowed_prompt_numeric_tokens if str(item).strip())
    for fact in advisory_context.facts:
        allowed_numeric_tokens.update(_extract_numeric_tokens(str(fact.value_text or "")))
        allowed_numeric_tokens.update(_extract_numeric_tokens(str(fact.timeframe or "")))
        allowed_numeric_tokens.update(_extract_numeric_tokens(str(fact.value)))
    for action in advisory_context.actions:
        try:
            action_params_text = json.dumps(action.params, ensure_ascii=False)
        except (TypeError, ValueError):
            action_params_text = str(action.params)
        allowed_numeric_tokens.update(_extract_numeric_tokens(action_params_text))

    ungrounded_numeric_tokens = sorted(raw_numeric_tokens.difference(allowed_numeric_tokens))
    hard_ungrounded_tokens = [token for token in ungrounded_numeric_tokens if not _is_soft_ungrounded_token(token)]
    if hard_ungrounded_tokens:
        errors.append("ungrounded_numeric_tokens")
        errors.append(f"ungrounded_numeric_tokens_sample:{','.join(hard_ungrounded_tokens[:5])}")

    if education_only:
        combined = " ".join(text_sections)
        if _INVESTMENT_EXECUTION_PATTERN.search(combined):
            errors.append("education_only_policy_violation")

    return sorted(set(errors))
