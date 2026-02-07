from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable

UTC = timezone.utc
FINANCE_VERSION = "finance-mcp-v1.0.0"


def new_trace_id(trace_id: str | None = None) -> str:
    return trace_id or f"trc_{uuid.uuid4().hex[:10]}"


def canonical_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


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
    policy_decision: str = "not_evaluated",
) -> Dict[str, Any]:
    duration_ms = max(0, int((now_utc() - started_at).total_seconds() * 1000))
    output = dict(payload)
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
    dev_bypass = os.getenv("DEV_BYPASS_AUTH", "false").strip().lower() in {"1", "true", "yes", "on"}
    if dev_bypass and auth_user_id == "demo-user":
        return
    if auth_user_id != requested_user_id:
        raise PermissionError("user_id in request does not match authenticated subject")


def group_sum(rows: Iterable[Dict[str, Any]], key: str, amount_key: str) -> Dict[str, float]:
    sums: Dict[str, float] = {}
    for row in rows:
        group = str(row.get(key, "") or "unknown").strip() or "unknown"
        sums[group] = sums.get(group, 0.0) + safe_float(row.get(amount_key))
    return sums
