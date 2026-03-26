from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone
from math import fsum
from typing import Any, Dict, Iterable, List, Mapping

UTC = timezone.utc
FINANCE_VERSION = "finance-mcp-v1.0.0"
FINANCE_SCHEMA_VERSION = "finance_tool_evidence_v2"
AUTH_CONTEXT: ContextVar[Dict[str, Any]] = ContextVar("finance_auth_context", default={})


def new_trace_id(trace_id: str | None = None) -> str:
    return trace_id or f"trc_{uuid.uuid4().hex[:10]}"


def canonical_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def set_auth_context(auth_context: Dict[str, Any]) -> Token:
    return AUTH_CONTEXT.set(dict(auth_context or {}))


def reset_auth_context(token: Token) -> None:
    AUTH_CONTEXT.reset(token)


def current_auth_context() -> Dict[str, Any]:
    return dict(AUTH_CONTEXT.get())


def iso_utc(value: datetime | None = None) -> str:
    dt = (value or now_utc()).astimezone(UTC).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def safe_float(value: Any, default: float = 0.0) -> float:
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


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(denominator) <= 1e-12:
        return default
    return numerator / denominator


def mean(values: Iterable[float], default: float = 0.0) -> float:
    seq = [float(value) for value in values]
    if not seq:
        return default
    return fsum(seq) / len(seq)


def population_stddev(values: Iterable[float], default: float = 0.0) -> float:
    seq = [float(value) for value in values]
    if len(seq) <= 1:
        return default
    avg = mean(seq)
    variance = mean([(value - avg) ** 2 for value in seq])
    return variance ** 0.5


def percentile(values: Iterable[float], q: float, default: float = 0.0) -> float:
    seq = sorted(float(value) for value in values)
    if not seq:
        return default
    q = clamp(q, 0.0, 1.0)
    if len(seq) == 1:
        return seq[0]
    position = q * (len(seq) - 1)
    lower = int(position)
    upper = min(len(seq) - 1, lower + 1)
    weight = position - lower
    return seq[lower] * (1 - weight) + seq[upper] * weight


def hhi(values: Iterable[float]) -> float:
    seq = [max(0.0, float(value)) for value in values]
    total = fsum(seq)
    if total <= 0:
        return 0.0
    return fsum((value / total) ** 2 for value in seq)


def confidence_level(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def weighted_score(components: Mapping[str, float], weights: Mapping[str, float]) -> float:
    weighted_total = 0.0
    weight_sum = 0.0
    for key, weight in weights.items():
        if weight <= 0:
            continue
        weight_sum += weight
        weighted_total += clamp(safe_float(components.get(key))) * weight
    if weight_sum <= 0:
        return 0.0
    return clamp(weighted_total / weight_sum)


def normalize_reason_codes(*groups: Iterable[Any]) -> List[str]:
    codes: List[str] = []
    for group in groups:
        for item in group:
            code = str(item or "").strip()
            if code and code not in codes:
                codes.append(code)
    return codes


def build_window(start: datetime, end: datetime) -> Dict[str, Any]:
    start_dt = start.astimezone(UTC)
    end_dt = end.astimezone(UTC)
    history_days = max(0, (end_dt.date() - start_dt.date()).days + 1)
    return {
        "start": start_dt.date().isoformat(),
        "end": end_dt.date().isoformat(),
        "history_days": history_days,
    }


def build_reliability(
    *,
    confidence_score: float,
    components: Mapping[str, float] | None = None,
    reason_codes: Iterable[Any] | None = None,
    abstain_threshold: float = 0.4,
) -> Dict[str, Any]:
    normalized_components = {
        str(key): round(clamp(safe_float(value)), 4)
        for key, value in (components or {}).items()
    }
    score = round(clamp(safe_float(confidence_score)), 4)
    return {
        "confidence_score": score,
        "confidence_level": confidence_level(score),
        "abstain_recommended": score < abstain_threshold,
        "reason_codes": normalize_reason_codes(reason_codes or []),
        "components": normalized_components,
    }


def build_provenance(
    *,
    library: str,
    model: str,
    model_version: str | None = None,
    base_model: str | None = None,
    feature_set_version: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "library": library,
        "model": model,
    }
    if model_version:
        payload["model_version"] = model_version
    if base_model:
        payload["base_model"] = base_model
    if feature_set_version:
        payload["feature_set_version"] = feature_set_version
    for key, value in (extra or {}).items():
        if value is not None:
            payload[str(key)] = value
    return payload


def build_validation(**kwargs: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is not None:
            payload[str(key)] = value
    return payload


def _prune_none(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned = {str(key): _prune_none(item) for key, item in value.items() if item is not None}
        return {key: item for key, item in cleaned.items() if item != {}}
    if isinstance(value, list):
        return [_prune_none(item) for item in value if item is not None]
    return value


def build_native_confidence(
    *,
    source: str,
    score: float | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": source,
    }
    if score is not None:
        payload["score"] = round(clamp(safe_float(score)), 4)
    payload.update(kwargs)
    return _prune_none(payload)


def build_native_uncertainty(
    *,
    source: str,
    p10: float | None = None,
    p50: float | None = None,
    p90: float | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": source,
    }
    if p10 is not None:
        payload["p10"] = round(safe_float(p10), 2)
    if p50 is not None:
        payload["p50"] = round(safe_float(p50), 2)
    if p90 is not None:
        payload["p90"] = round(safe_float(p90), 2)
    payload.update(kwargs)
    return _prune_none(payload)


def build_model_evidence(
    *,
    native_confidence: Mapping[str, Any] | None = None,
    native_uncertainty: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if native_confidence:
        payload["native_confidence"] = _prune_none(dict(native_confidence))
    if native_uncertainty:
        payload["native_uncertainty"] = _prune_none(dict(native_uncertainty))
    return payload


def parse_range_days(range_value: str) -> int:
    value = (range_value or "30d").strip().lower()
    if value.endswith("d"):
        try:
            return max(1, min(365, int(value[:-1])))
        except ValueError:
            return 30
    return 30


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def daterange_start(end: datetime, days: int) -> datetime:
    return end - timedelta(days=max(1, days) - 1)


def build_output(
    *,
    tool_name: str,
    tool_input: Dict[str, Any],
    payload: Dict[str, Any],
    trace_id: str,
    started_at: datetime,
    sql_snapshot_ts: str,
    schema_version: str = FINANCE_SCHEMA_VERSION,
    as_of: str | None = None,
    window: Dict[str, Any] | None = None,
    reliability: Dict[str, Any] | None = None,
    trust: Dict[str, Any] | None = None,
    agent_use: Dict[str, Any] | None = None,
    model_evidence: Dict[str, Any] | None = None,
    provenance: Dict[str, Any] | None = None,
    validation: Dict[str, Any] | None = None,
    policy_decision: str = "not_evaluated",
) -> Dict[str, Any]:
    duration_ms = max(0, int((now_utc() - started_at).total_seconds() * 1000))
    output = dict(payload)
    output.setdefault("schema_version", schema_version)
    output.setdefault("tool_name", tool_name)
    if as_of is not None:
        output["as_of"] = as_of
    if window is not None:
        output["window"] = dict(window)
    if reliability is not None:
        output["reliability"] = dict(reliability)
    if trust is not None:
        output["trust"] = dict(trust)
    if agent_use is not None:
        output["agent_use"] = dict(agent_use)
    if model_evidence:
        output["model_evidence"] = dict(model_evidence)
    if provenance is not None:
        output["provenance"] = dict(provenance)
    if validation is not None:
        output["validation"] = dict(validation)
    output.update(
        {
            "trace_id": trace_id,
            "version": FINANCE_VERSION,
            "params_hash": canonical_hash(tool_input),
            "sql_snapshot_ts": sql_snapshot_ts,
            "audit": {
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "policy_decision": policy_decision,
            },
        }
    )
    return output


def ensure_user_scope(auth_user_id: str, requested_user_id: str) -> None:
    caller_type = str(current_auth_context().get("caller_type") or "user").strip().lower()
    if caller_type == "service":
        return
    normalized_auth_user_id = str(auth_user_id or "").strip()
    normalized_requested_user_id = str(requested_user_id or "").strip()
    if not normalized_auth_user_id or not normalized_requested_user_id:
        raise PermissionError("Authenticated user scope is required for finance tool access")
    if normalized_auth_user_id != normalized_requested_user_id:
        raise PermissionError("user_id in request does not match authenticated subject")


def group_sum(rows: Iterable[Dict[str, Any]], key: str, amount_key: str) -> Dict[str, float]:
    sums: Dict[str, float] = {}
    for row in rows:
        group = str(row.get(key, "") or "unknown").strip() or "unknown"
        sums[group] = sums.get(group, 0.0) + safe_float(row.get(amount_key))
    return sums


