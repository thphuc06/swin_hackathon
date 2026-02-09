from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable

import boto3
from pydantic import ValidationError

from config import AWS_REGION, BEDROCK_MODEL_ID

from .contracts import AdvisoryContextV1, AnswerPlanV2
from .schemas import validate_answer_plan_payload

logger = logging.getLogger(__name__)
PROMPT_VERSION = "answer_synth_v2"
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."
_FACT_PLACEHOLDER_PATTERN = re.compile(r"\[F:([a-zA-Z0-9._-]+)\]")


def _build_prompt(
    *,
    user_prompt: str,
    intent: str,
    route_decision: Dict[str, Any],
    advisory_context: AdvisoryContextV1,
    policy_flags: Dict[str, Any],
    corrective_feedback: str = "",
) -> str:
    context_json = json.dumps(
        {
            "schema_version": advisory_context.schema_version,
            "intent": advisory_context.intent,
            "language": advisory_context.language,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "label": fact.label,
                    "value_text": fact.value_text,
                    "timeframe": fact.timeframe,
                    "source_tool": fact.source_tool,
                }
                for fact in advisory_context.facts
            ],
            "insights": [
                {
                    "insight_id": insight.insight_id,
                    "kind": insight.kind,
                    "severity": insight.severity,
                    "message_seed": insight.message_seed,
                    "supporting_fact_ids": insight.supporting_fact_ids,
                }
                for insight in advisory_context.insights
            ],
            "actions": [
                {
                    "action_id": action.action_id,
                    "priority": action.priority,
                    "action_type": action.action_type,
                    "params": action.params,
                    "supporting_insight_ids": action.supporting_insight_ids,
                }
                for action in advisory_context.actions
            ],
            "citations": advisory_context.citations,
            "policy_flags": advisory_context.policy_flags,
        },
        ensure_ascii=True,
    )
    route_json = json.dumps(route_decision, ensure_ascii=True)
    policy_json = json.dumps(policy_flags, ensure_ascii=True)
    correction = f"\nPrevious attempt issues: {corrective_feedback}" if corrective_feedback else ""

    return (
        "You are a compliant fintech advisor response synthesizer.\n"
        "Return ONLY one valid JSON object. No markdown.\n"
        "The object must follow schema answer_plan_v2 with no extra properties.\n"
        "schema_version must be 'answer_plan_v2'.\n"
        "language must be 'vi' or 'en'.\n"
        "summary_lines must contain 3 to 5 concise lines.\n"
        "actions must contain 2 to 4 concise items.\n"
        "Use plain, persuasive advisory wording (bank-advisor style), but keep every claim grounded.\n"
        "You are NOT allowed to invent new numbers.\n"
        "For any metric number in free text, use fact placeholders [F:fact_id] only.\n"
        "Small operational cadence numbers (for example 2 weeks, 14 days) are allowed only if they are in user prompt/policy context.\n"
        "Do not print raw numeric literals in summary_lines/actions/assumptions/limitations.\n"
        "key_metrics must be array of {fact_id,label} referencing known fact_ids.\n"
        "used_fact_ids must include every fact referenced by key_metrics or placeholders.\n"
        "used_insight_ids must reference provided insight IDs only.\n"
        "used_action_ids must reference provided action IDs only.\n"
        "If education_only is true, avoid buy/sell/trade execution advice.\n"
        "If intent is invest and user asks buy/sell recommendation, refuse recommendation and redirect to non-investment planning.\n"
        "Personalize suggestions with policy_flags.risk_appetite: conservative -> prioritize safety/liquidity; "
        "moderate -> balance stability and progress; aggressive -> accept higher uncertainty while staying non-investment.\n"
        "If risk_appetite is unknown and intent is planning/scenario/invest, include one concise follow-up question "
        "asking user to choose risk appetite (thap/vua/cao) and keep guidance provisional.\n"
        "For Vietnamese output, use simple daily wording and avoid internal tool names/IDs.\n"
        "When facts include kb.service_category.*, include at least one practical banking service suggestion in actions.\n"
        "Map service suggestion to context: savings_capacity -> savings/deposit; goal_gap or negative cashflow -> loan/credit support; spend anomaly -> card/payment control.\n"
        "Do not expose internal fact IDs, insight IDs, action IDs, or tool IDs in prose.\n"
        "When scenario best variant is base, still provide concrete next actions grounded by available facts.\n"
        "If data is missing, write it in limitations without inventing facts.\n"
        "JSON example:\n"
        "{\"schema_version\":\"answer_plan_v2\",\"language\":\"vi\","
        "\"summary_lines\":[\"DÃ²ng tiá»n rÃ²ng [F:spend.net_cashflow.30d]\",\"...\",\"...\"],"
        "\"key_metrics\":[{\"fact_id\":\"spend.net_cashflow.30d\",\"label\":\"DÃ²ng tiá»n rÃ²ng\"}],"
        "\"actions\":[\"Æ¯u tiÃªn á»•n Ä‘á»‹nh dÃ²ng tiá»n theo [F:spend.net_cashflow.30d]\",\"...\"],"
        "\"assumptions\":[],\"limitations\":[],"
        "\"disclaimer\":\"Educational guidance only. We do not provide investment advice.\","
        "\"used_fact_ids\":[\"spend.net_cashflow.30d\"],"
        "\"used_insight_ids\":[\"insight.cashflow_pressure\"],"
        "\"used_action_ids\":[\"stabilize_cashflow\"]}\n"
        f"{correction}\n"
        f"User prompt: {user_prompt}\n"
        f"Intent: {intent}\n"
        f"Route decision: {route_json}\n"
        f"Policy flags: {policy_json}\n"
        f"Advisory context: {context_json}\n"
    )


def _extract_text_from_converse_payload(payload: Dict[str, Any]) -> str:
    output = payload.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    texts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return "\n".join(texts).strip()


def _try_parse_json(raw_text: str) -> Dict[str, Any] | None:
    text = _normalize_json_text(raw_text or "")
    if not text:
        return None

    direct = _load_json_candidate(text)
    if isinstance(direct, dict):
        return direct

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        parsed = _load_json_candidate(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]
    parsed = _load_json_candidate(candidate)
    return parsed if isinstance(parsed, dict) else None


def _normalize_json_text(text: str) -> str:
    normalized = str(text or "").strip().lstrip("\ufeff")
    replacements = {
        "\u201c": "\"",
        "\u201d": "\"",
        "\u2018": "'",
        "\u2019": "'",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"^\s*json\s*[:\-]?\s*", "", normalized, flags=re.IGNORECASE)
    return normalized.strip()


def _load_json_candidate(text: str) -> Dict[str, Any] | None:
    candidate = _normalize_json_text(text)
    if not candidate:
        return None

    candidates = [candidate, re.sub(r",(\s*[}\]])", r"\1", candidate)]
    for item in candidates:
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]
        if isinstance(parsed, str):
            try:
                nested = json.loads(parsed)
            except json.JSONDecodeError:
                continue
            if isinstance(nested, dict):
                return nested
    return None


def _invoke_bedrock_converse(prompt: str, *, model_id: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0.0, "topP": 0.01, "maxTokens": 900},
    )
    return _extract_text_from_converse_payload(response)


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = str(item).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_key_metrics(value: Any) -> list[Dict[str, str]]:
    metrics: list[Dict[str, str]] = []
    if value is None:
        return metrics

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            fact_id = str(item.get("fact_id") or "").strip()
            if not fact_id:
                continue
            metrics.append(
                {
                    "fact_id": fact_id,
                    "label": str(item.get("label") or "").strip(),
                }
            )
        return metrics

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            if isinstance(item, dict):
                metrics.append(
                    {
                        "fact_id": str(item.get("fact_id") or key_text).strip(),
                        "label": str(item.get("label") or "").strip(),
                    }
                )
                continue
            metrics.append({"fact_id": key_text, "label": ""})
    return metrics


def _fallback_summary_lines(language: str) -> list[str]:
    if language == "vi":
        return [
            "Da tong hop thong tin tu cac fact da xac thuc.",
            "Noi dung dang gioi han trong pham vi du lieu tu tool.",
            "Ban co the bo sung muc tieu cu the de nhan khuyen nghi sac net hon.",
        ]
    return [
        "The response is synthesized from verified facts only.",
        "Guidance is constrained to tool-grounded evidence.",
        "You can provide a more specific goal for a sharper recommendation.",
    ]


def _fallback_actions(language: str) -> list[str]:
    if language == "vi":
        return [
            "Xac nhan uu tien tai chinh ngan han (an toan dong tien, tra no, hay tich luy).",
            "Cap nhat du lieu moi va danh gia lai sau hai tuan.",
        ]
    return [
        "Confirm your top short-term financial priority.",
        "Refresh your data and re-evaluate in two weeks.",
    ]


def _sanitize_answer_payload(
    payload: Dict[str, Any],
    *,
    intent: str,
    risk_appetite: str,
    default_language: str,
    default_disclaimer: str,
    valid_fact_ids: set[str],
    valid_insight_ids: set[str],
    valid_action_ids: set[str],
) -> Dict[str, Any]:
    allowed_keys = {
        "schema_version",
        "language",
        "summary_lines",
        "key_metrics",
        "actions",
        "assumptions",
        "limitations",
        "disclaimer",
        "used_fact_ids",
        "used_insight_ids",
        "used_action_ids",
    }
    normalized = {key: value for key, value in dict(payload).items() if key in allowed_keys}
    language = str(normalized.get("language") or default_language or "en").strip().lower()
    if language not in {"vi", "en"}:
        language = default_language if default_language in {"vi", "en"} else "en"
    normalized["language"] = language
    normalized["schema_version"] = "answer_plan_v2"

    summary_lines = _coerce_str_list(normalized.get("summary_lines"))
    if len(summary_lines) < 3:
        summary_lines = [*summary_lines, *_fallback_summary_lines(language)]
    normalized["summary_lines"] = summary_lines[:5]

    key_metrics = _coerce_key_metrics(normalized.get("key_metrics"))
    key_metrics = [item for item in key_metrics if str(item.get("fact_id") or "").strip() in valid_fact_ids]
    if not key_metrics and valid_fact_ids:
        key_metrics = [{"fact_id": fact_id, "label": ""} for fact_id in sorted(valid_fact_ids)[:3]]
    normalized["key_metrics"] = key_metrics

    actions = _coerce_str_list(normalized.get("actions"))
    normalized_intent = str(intent or "").strip().lower()
    normalized_risk = str(risk_appetite or "").strip().lower()
    if normalized_risk not in {"conservative", "moderate", "aggressive"}:
        normalized_risk = "unknown"
    if normalized_risk == "unknown" and normalized_intent in {"planning", "scenario", "invest"}:
        follow_up_line = (
            "Ban uu tien khau vi rui ro nao: thap, vua hay cao? Toi se tinh chinh ke hoach sau khi ban chon."
            if language == "vi"
            else "Which risk appetite fits you best: low, medium, or high? I will refine the plan after your choice."
        )
        follow_up_markers = ["khau vi rui ro", "risk appetite", "low, medium, or high", "thap, vua hay cao"]
        if not any(any(marker in item.lower() for marker in follow_up_markers) for item in actions):
            actions = [follow_up_line, *actions]
    if len(actions) < 2:
        actions = [*actions, *_fallback_actions(language)]
    normalized["actions"] = actions[:4]
    normalized["assumptions"] = _coerce_str_list(normalized.get("assumptions"))
    normalized["limitations"] = _coerce_str_list(normalized.get("limitations"))

    text_sections = [
        *normalized["summary_lines"],
        *normalized["actions"],
        *normalized["assumptions"],
        *normalized["limitations"],
    ]
    placeholder_fact_ids = [
        fact_id
        for fact_id in _extract_placeholder_fact_ids(text_sections)
        if fact_id in valid_fact_ids
    ]
    metric_fact_ids = [
        str(item.get("fact_id") or "").strip()
        for item in key_metrics
        if str(item.get("fact_id") or "").strip() in valid_fact_ids
    ]
    used_fact_ids = _coerce_str_list(normalized.get("used_fact_ids"))
    used_fact_ids = _dedupe_keep_order([*used_fact_ids, *metric_fact_ids, *placeholder_fact_ids])
    used_fact_ids = _dedupe_keep_order(item for item in used_fact_ids if item in valid_fact_ids)
    if not used_fact_ids and key_metrics:
        used_fact_ids = _dedupe_keep_order(
            str(item.get("fact_id") or "").strip()
            for item in key_metrics
            if str(item.get("fact_id") or "").strip() in valid_fact_ids
        )
    normalized["used_fact_ids"] = used_fact_ids

    used_insight_ids = _dedupe_keep_order(
        item for item in _coerce_str_list(normalized.get("used_insight_ids")) if item in valid_insight_ids
    )
    if not used_insight_ids and valid_insight_ids:
        used_insight_ids = sorted(valid_insight_ids)[:2]
    normalized["used_insight_ids"] = used_insight_ids

    used_action_ids = _dedupe_keep_order(
        item for item in _coerce_str_list(normalized.get("used_action_ids")) if item in valid_action_ids
    )
    if not used_action_ids and valid_action_ids:
        used_action_ids = sorted(valid_action_ids)[: min(4, max(2, len(valid_action_ids)))]
    normalized["used_action_ids"] = used_action_ids

    disclaimer = str(normalized.get("disclaimer") or "").strip()
    normalized["disclaimer"] = disclaimer or default_disclaimer or DEFAULT_DISCLAIMER
    return normalized


def _extract_placeholder_fact_ids(sections: Iterable[str]) -> list[str]:
    found: list[str] = []
    for section in sections:
        text = str(section or "")
        for fact_id in _FACT_PLACEHOLDER_PATTERN.findall(text):
            value = str(fact_id).strip()
            if value:
                found.append(value)
    return _dedupe_keep_order(found)


def synthesize_answer_plan_with_bedrock(
    *,
    user_prompt: str,
    intent: str,
    route_decision: Dict[str, Any],
    advisory_context: AdvisoryContextV1,
    policy_flags: Dict[str, Any],
    allowed_numeric_tokens: set[str] | None = None,
    retry_attempts: int = 1,
    model_id: str | None = None,
    corrective_feedback: str = "",
) -> tuple[AnswerPlanV2 | None, list[str], Dict[str, Any]]:
    errors: list[str] = []
    runtime_meta: Dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "attempts": retry_attempts + 1,
        "raw_text": "",
    }
    _ = allowed_numeric_tokens
    resolved_model = (model_id or BEDROCK_MODEL_ID or "").strip()
    runtime_meta["model_id"] = resolved_model
    if not resolved_model:
        errors.append("model_not_configured")
        return None, errors, runtime_meta

    prompt_text = _build_prompt(
        user_prompt=user_prompt,
        intent=intent,
        route_decision=route_decision,
        advisory_context=advisory_context,
        policy_flags=policy_flags,
        corrective_feedback=corrective_feedback,
    )

    valid_fact_ids = {fact.fact_id for fact in advisory_context.facts}
    valid_insight_ids = {insight.insight_id for insight in advisory_context.insights}
    valid_action_ids = {action.action_id for action in advisory_context.actions}

    for attempt in range(retry_attempts + 1):
        runtime_meta["attempt"] = attempt + 1
        try:
            raw_text = _invoke_bedrock_converse(prompt_text, model_id=resolved_model)
            runtime_meta["raw_text"] = raw_text
        except Exception as exc:  # pragma: no cover - runtime/network path
            errors.append(f"bedrock_invoke_error:{type(exc).__name__}")
            logger.warning("Answer synthesis invoke failed on attempt %s: %s", attempt + 1, exc)
            continue

        payload = _try_parse_json(raw_text)
        if payload is None:
            errors.append("answer_invalid_json")
            continue

        payload = _sanitize_answer_payload(
            payload,
            intent=intent,
            risk_appetite=str(policy_flags.get("risk_appetite") or ""),
            default_language=advisory_context.language,
            default_disclaimer=str(policy_flags.get("required_disclaimer") or DEFAULT_DISCLAIMER),
            valid_fact_ids=valid_fact_ids,
            valid_insight_ids=valid_insight_ids,
            valid_action_ids=valid_action_ids,
        )
        schema_errors = validate_answer_plan_payload(payload)
        if schema_errors:
            errors.append("answer_invalid_schema")
            errors.extend([f"schema:{msg}" for msg in schema_errors[:3]])
            continue

        try:
            answer_plan = AnswerPlanV2.model_validate(payload)
            return answer_plan, errors, runtime_meta
        except ValidationError as exc:
            errors.append("answer_invalid_contract")
            errors.append(str(exc))
            continue

    return None, errors, runtime_meta

