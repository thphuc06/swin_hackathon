from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import boto3
from pydantic import ValidationError

from config import AWS_REGION, BEDROCK_MODEL_ID

from .contracts import IntentExtractionV1
from .schemas import validate_intent_extraction_payload

logger = logging.getLogger(__name__)
PROMPT_VERSION = "intent_extractor_v1"


def _build_prompt(user_prompt: str) -> str:
    return (
        "You are an intent+slot extractor for a fintech advisor.\n"
        "Return ONLY one valid JSON object.\n"
        "Do not add markdown, comments, or explanation.\n"
        "Use schema_version='intent_extraction_v1'.\n"
        "Allowed intent values: summary, risk, planning, scenario, invest, out_of_scope.\n"
        "top2 must contain exactly two intent+score entries.\n"
        "scores must be between 0 and 1.\n"
        "domain_relevance must be between 0 and 1 and represent how related the prompt is to personal-finance advisory scope.\n"
        "slots should include structured values when present.\n"
        "Classify as scenario only for explicit what-if/counterfactual prompts (e.g., neu/gia su/what-if with changes).\n"
        "If user asks current-state analysis by period (30/60/90 days) without hypothetical changes, prefer summary or risk.\n"
        "If user asks feasibility of goals (buy house/save target), prefer planning unless explicit what-if deltas are requested.\n"
        "If prompt is not about personal finance advisory (cashflow, budgeting, non-investment risk, planning, what-if), classify as out_of_scope.\n"
        "For scenario intent, extract if possible: horizon_months, income_delta_pct, spend_delta_pct, "
        "income_delta_amount_vnd, spend_delta_amount_vnd.\n"
        "If user states risk preference, extract slots.risk_appetite with one of: conservative, moderate, aggressive.\n"
        "If missing values, keep slots empty rather than hallucinating.\n"
        "Output JSON fields: schema_version, intent, sub_intent, confidence, domain_relevance, top2, slots, scenario_confidence, reason.\n"
        f"User prompt: {user_prompt}"
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
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _invoke_bedrock_converse(prompt: str, *, model_id: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0.0, "topP": 0.01, "maxTokens": 400},
    )
    return _extract_text_from_converse_payload(response)


def _sanitize_extraction_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    if normalized.get("sub_intent") is None:
        normalized["sub_intent"] = ""
    if normalized.get("reason") is None:
        normalized["reason"] = ""
    if normalized.get("scenario_confidence") is None:
        normalized.pop("scenario_confidence", None)

    domain_relevance = normalized.get("domain_relevance")
    if isinstance(domain_relevance, (int, float)):
        normalized["domain_relevance"] = max(0.0, min(1.0, float(domain_relevance)))
    else:
        top2 = normalized.get("top2")
        out_of_scope_score = 0.0
        if isinstance(top2, list):
            for item in top2:
                if not isinstance(item, dict):
                    continue
                if str(item.get("intent") or "").strip() != "out_of_scope":
                    continue
                raw_score = item.get("score")
                if isinstance(raw_score, (int, float)):
                    out_of_scope_score = max(0.0, min(1.0, float(raw_score)))
                    break
        if out_of_scope_score > 0:
            normalized["domain_relevance"] = 1.0 - out_of_scope_score
        elif str(normalized.get("intent") or "") == "out_of_scope":
            normalized["domain_relevance"] = 0.2
        else:
            confidence = normalized.get("confidence")
            if isinstance(confidence, (int, float)):
                normalized["domain_relevance"] = max(0.0, min(1.0, float(confidence)))
            else:
                normalized["domain_relevance"] = 0.5

    slots = normalized.get("slots")
    if isinstance(slots, dict):
        normalized["slots"] = {key: value for key, value in slots.items() if value is not None}
    return normalized


def extract_intent_with_bedrock(
    prompt: str,
    *,
    retry_attempts: int = 1,
    model_id: str | None = None,
) -> tuple[IntentExtractionV1 | None, list[str], Dict[str, Any]]:
    errors: list[str] = []
    runtime_meta: Dict[str, Any] = {"prompt_version": PROMPT_VERSION, "attempts": retry_attempts + 1}
    resolved_model = (model_id or BEDROCK_MODEL_ID or "").strip()

    if not resolved_model:
        errors.append("model_not_configured")
        return None, errors, runtime_meta

    prompt_text = _build_prompt(prompt)
    runtime_meta["model_id"] = resolved_model
    runtime_meta["raw_text"] = ""

    for attempt in range(retry_attempts + 1):
        runtime_meta["attempt"] = attempt + 1
        try:
            raw_text = _invoke_bedrock_converse(prompt_text, model_id=resolved_model)
            runtime_meta["raw_text"] = raw_text
        except Exception as exc:  # pragma: no cover - runtime/network path
            errors.append(f"bedrock_invoke_error:{type(exc).__name__}")
            logger.warning("Intent extraction invoke failed on attempt %s: %s", attempt + 1, exc)
            continue

        payload = _try_parse_json(raw_text)
        if payload is None:
            errors.append("invalid_json")
            continue
        payload = _sanitize_extraction_payload(payload)

        schema_errors = validate_intent_extraction_payload(payload)
        if schema_errors:
            errors.append("invalid_schema")
            errors.extend([f"schema:{msg}" for msg in schema_errors[:3]])
            continue

        try:
            extraction = IntentExtractionV1.model_validate(payload)
            return extraction, errors, runtime_meta
        except ValidationError as exc:
            errors.append("invalid_contract")
            errors.append(str(exc))
            continue

    return None, errors, runtime_meta
