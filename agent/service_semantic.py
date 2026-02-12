from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

from config import (
    AWS_REGION,
    BEDROCK_CONNECT_TIMEOUT,
    BEDROCK_READ_TIMEOUT,
    SERVICE_EMBED_ENABLED,
    SERVICE_EMBED_MODEL_ID,
    SERVICE_EMBED_TOP_N,
)

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_BEDROCK_CLIENT: Any | None = None
_DOC_VECTOR_CACHE: dict[tuple[str, str], dict[str, list[float]]] = {}
_QUERY_VECTOR_CACHE: dict[tuple[str, str], list[float]] = {}


@dataclass
class ServiceSemanticCandidate:
    service_id: str
    similarity: float
    normalized_similarity: float
    rank: int


def _get_bedrock_client() -> Any:
    global _BEDROCK_CLIENT
    with _LOCK:
        if _BEDROCK_CLIENT is None:
            cfg = Config(
                connect_timeout=BEDROCK_CONNECT_TIMEOUT,
                read_timeout=BEDROCK_READ_TIMEOUT,
                retries={"max_attempts": 2, "mode": "adaptive"},
            )
            _BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION, config=cfg)
        return _BEDROCK_CLIENT


def _text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def _normalize_vector(raw: Any) -> list[float] | None:
    if not isinstance(raw, list):
        return None
    out: list[float] = []
    for item in raw:
        if isinstance(item, (int, float)):
            out.append(float(item))
            continue
        try:
            out.append(float(str(item).strip()))
        except ValueError:
            return None
    return out if out else None


def _extract_embedding(payload: dict[str, Any]) -> list[float] | None:
    vector = _normalize_vector(payload.get("embedding"))
    if vector:
        return vector

    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and embeddings:
        first = embeddings[0]
        if isinstance(first, list):
            vector = _normalize_vector(first)
            if vector:
                return vector
        if isinstance(first, dict):
            vector = _normalize_vector(first.get("embedding"))
            if vector:
                return vector

    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            vector = _normalize_vector(first.get("embedding"))
            if vector:
                return vector
    return None


def _embed_with_payload(model_id: str, payload: dict[str, Any]) -> list[float] | None:
    client = _get_bedrock_client()
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = response.get("body")
    raw = body.read() if hasattr(body, "read") else body
    if isinstance(raw, bytes):
        parsed = json.loads(raw.decode("utf-8"))
    elif isinstance(raw, str):
        parsed = json.loads(raw)
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {}
    if not isinstance(parsed, dict):
        return None
    return _extract_embedding(parsed)


def _embed_text(model_id: str, text: str, *, input_type: str) -> list[float] | None:
    cache_key = (model_id, _text_hash(text))
    with _LOCK:
        cached = _QUERY_VECTOR_CACHE.get(cache_key)
    if cached:
        return cached

    payloads: list[dict[str, Any]] = []
    model_lower = model_id.lower()
    if "cohere" in model_lower:
        payloads.append({"texts": [text], "input_type": input_type})
    else:
        payloads.append({"inputText": text})
        payloads.append({"texts": [text], "input_type": input_type})

    last_error: Exception | None = None
    for payload in payloads:
        try:
            vector = _embed_with_payload(model_id, payload)
            if vector:
                with _LOCK:
                    _QUERY_VECTOR_CACHE[cache_key] = vector
                return vector
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if last_error is not None:
        logger.warning("embedding_call_failed model=%s error=%s", model_id, last_error)
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dim = min(len(a), len(b))
    if dim <= 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for idx in range(dim):
        x = float(a[idx])
        y = float(b[idx])
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _normalize_similarity(value: float) -> float:
    return max(0.0, min(1.0, (float(value) + 1.0) / 2.0))


def _ensure_doc_vectors(
    *,
    catalog_version: str,
    model_id: str,
    service_texts: dict[str, str],
) -> tuple[dict[str, list[float]], list[str]]:
    cache_key = (catalog_version, model_id)
    reason_codes: list[str] = []
    with _LOCK:
        vectors = dict(_DOC_VECTOR_CACHE.get(cache_key, {}))

    missing_ids = [service_id for service_id in service_texts if service_id not in vectors]
    if not missing_ids:
        return vectors, reason_codes

    for service_id in missing_ids:
        text = str(service_texts.get(service_id) or "").strip()
        if not text:
            continue
        vector = _embed_text(model_id, text, input_type="search_document")
        if vector is None:
            reason_codes.append(f"embedding_doc_failed:{service_id}")
            continue
        vectors[service_id] = vector

    with _LOCK:
        _DOC_VECTOR_CACHE[cache_key] = vectors
    return vectors, reason_codes


def rank_semantic_candidates(
    *,
    query_text: str,
    service_texts: dict[str, str],
    catalog_version: str,
    top_n: int | None = None,
) -> tuple[list[ServiceSemanticCandidate], list[str]]:
    effective_top_n = max(1, int(top_n or SERVICE_EMBED_TOP_N))
    reason_codes: list[str] = []

    if not bool(SERVICE_EMBED_ENABLED):
        return [], ["embedding_disabled"]
    model_id = str(SERVICE_EMBED_MODEL_ID or "").strip()
    if not model_id:
        return [], ["embedding_model_missing"]
    if not service_texts:
        return [], ["embedding_no_service_texts"]

    try:
        doc_vectors, doc_reasons = _ensure_doc_vectors(
            catalog_version=catalog_version,
            model_id=model_id,
            service_texts=service_texts,
        )
        reason_codes.extend(doc_reasons)
        query_vector = _embed_text(model_id, query_text, input_type="search_query")
        if query_vector is None:
            reason_codes.append("embedding_query_failed")
            return [], sorted(set(reason_codes))

        rows: list[ServiceSemanticCandidate] = []
        for service_id, vector in doc_vectors.items():
            similarity = _cosine_similarity(query_vector, vector)
            rows.append(
                ServiceSemanticCandidate(
                    service_id=service_id,
                    similarity=round(similarity, 6),
                    normalized_similarity=round(_normalize_similarity(similarity), 6),
                    rank=0,
                )
            )

        rows.sort(key=lambda item: (-item.normalized_similarity, item.service_id))
        selected = rows[:effective_top_n]
        for index, item in enumerate(selected, start=1):
            item.rank = index
        if not selected:
            reason_codes.append("embedding_empty_candidates")
        return selected, sorted(set(reason_codes))
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding_unavailable_fallback error=%s", exc)
        return [], ["embedding_unavailable_fallback"]
