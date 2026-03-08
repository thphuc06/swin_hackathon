from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import boto3
from botocore.config import Config
from pydantic import ValidationError

from config import (
    AWS_REGION,
    BEDROCK_CONNECT_TIMEOUT,
    BEDROCK_GUARDRAIL_ID,
    BEDROCK_GUARDRAIL_VERSION,
    BEDROCK_MODEL_ID,
    BEDROCK_READ_TIMEOUT,
)

from .contracts import IntentExtractionV1
from .schemas import validate_intent_extraction_payload

logger = logging.getLogger(__name__)
PROMPT_VERSION = "intent_extractor_v1"

# Boto3 client cache with timeout config
_bedrock_client = None
_guardrail_warning_emitted = False


def _truncate_for_log(text: str, limit: int = 320) -> str:
    payload = str(text or "").strip().replace("\n", "\\n")
    if len(payload) <= limit:
        return payload
    return f"{payload[:limit]}..."

def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        config = Config(
            connect_timeout=BEDROCK_CONNECT_TIMEOUT,
            read_timeout=BEDROCK_READ_TIMEOUT,
            retries={'max_attempts': 2, 'mode': 'adaptive'}
        )
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=config
        )
        logger.info(
            "Initialized Bedrock client with timeout config (connect=%ds, read=%ds)",
            BEDROCK_CONNECT_TIMEOUT,
            BEDROCK_READ_TIMEOUT,
        )
    return _bedrock_client


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


def _extract_text_from_converse_payload(payload: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    output = payload.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    texts: list[str] = []
    reasoning_texts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str):
                texts.append(item["text"])
            reasoning_content = item.get("reasoningContent")
            if isinstance(reasoning_content, dict):
                reasoning_text = (reasoning_content.get("reasoningText") or {}).get("text")
                if isinstance(reasoning_text, str):
                    reasoning_texts.append(reasoning_text)
    meta = {
        "content_items": len(content) if isinstance(content, list) else 0,
        "text_items": len(texts),
        "reasoning_items": len(reasoning_texts),
    }
    if texts:
        return "\n".join(texts).strip(), meta
    if reasoning_texts:
        logger.warning("Intent extraction received reasoningContent-only response; using reasoningText fallback.")
        return "\n".join(reasoning_texts).strip(), meta
    return "", meta


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


def _invoke_bedrock_converse(prompt: str, *, model_id: str) -> tuple[str, Dict[str, Any]]:
    client = _get_bedrock_client()
    logger.debug("Invoking Bedrock converse for intent extraction (model=%s)", model_id)
    request: Dict[str, Any] = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"temperature": 0.0, "maxTokens": 900},
    }
    guardrail_id = str(BEDROCK_GUARDRAIL_ID or "").strip()
    guardrail_version = str(BEDROCK_GUARDRAIL_VERSION or "DRAFT").strip() or "DRAFT"
    if guardrail_id:
        request["guardrailConfig"] = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": guardrail_version,
        }
    else:
        global _guardrail_warning_emitted
        if not _guardrail_warning_emitted and str(BEDROCK_GUARDRAIL_VERSION or "").strip():
            logger.warning(
                "BEDROCK_GUARDRAIL_VERSION is set but BEDROCK_GUARDRAIL_ID is empty. Guardrail is disabled."
            )
            _guardrail_warning_emitted = True
    response = client.converse(
        **request,
    )
    text, payload_meta = _extract_text_from_converse_payload(response)
    usage = response.get("usage") if isinstance(response, dict) else {}
    invoke_meta = {
        "stop_reason": str(response.get("stopReason") or ""),
        "input_tokens": int((usage or {}).get("inputTokens") or 0),
        "output_tokens": int((usage or {}).get("outputTokens") or 0),
        "total_tokens": int((usage or {}).get("totalTokens") or 0),
        **payload_meta,
    }
    return text, invoke_meta


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
    runtime_meta: Dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "attempts": retry_attempts + 1,
        "guardrail_enabled": bool(str(BEDROCK_GUARDRAIL_ID or "").strip()),
        "guardrail_id": str(BEDROCK_GUARDRAIL_ID or "").strip(),
        "guardrail_version": str(BEDROCK_GUARDRAIL_VERSION or "DRAFT").strip() or "DRAFT",
        "attempt_meta": [],
    }
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
            raw_text, invoke_meta = _invoke_bedrock_converse(prompt_text, model_id=resolved_model)
            runtime_meta["raw_text"] = raw_text
            runtime_meta["attempt_meta"].append({"attempt": attempt + 1, **invoke_meta})
        except Exception as exc:  # pragma: no cover - runtime/network path
            errors.append(f"bedrock_invoke_error:{type(exc).__name__}")
            logger.warning("Intent extraction invoke failed on attempt %s: %s", attempt + 1, exc)
            continue

        payload = _try_parse_json(raw_text)
        if payload is None:
            logger.warning(
                "intent_json_parse_failed attempt=%s stop_reason=%s output_tokens=%s preview=%s",
                attempt + 1,
                str(invoke_meta.get("stop_reason") or ""),
                int(invoke_meta.get("output_tokens") or 0),
                _truncate_for_log(raw_text),
            )
            if str(invoke_meta.get("stop_reason") or "").strip().lower() == "max_tokens":
                errors.append("intent_output_truncated_max_tokens")
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
