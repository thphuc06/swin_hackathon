from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from core.settings import CLOUDWATCH_ENABLED, OBSERVABILITY_EXPORTER
from .exporters.cloudwatch_exporter import CloudWatchExporter
from .exporters.noop_exporter import NoopExporter

logger = logging.getLogger(__name__)


_EXPORTER = None
_TOOL_METRICS_LOCK = threading.Lock()
_TOOL_METRICS: Dict[str, Dict[str, Any]] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_exporter():
    global _EXPORTER
    if _EXPORTER is not None:
        return _EXPORTER
    mode = str(OBSERVABILITY_EXPORTER or "structured").strip().lower()
    if mode == "cloudwatch" or (mode == "structured" and CLOUDWATCH_ENABLED):
        _EXPORTER = CloudWatchExporter()
    else:
        _EXPORTER = NoopExporter()
    return _EXPORTER


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _latency_percentile(latencies: list[int], percentile: float) -> int:
    if not latencies:
        return 0
    ordered = sorted(int(item) for item in latencies if int(item) >= 0)
    if not ordered:
        return 0
    index = int(round((len(ordered) - 1) * max(0.0, min(1.0, percentile))))
    return ordered[index]


def _update_tool_metrics(envelope: Dict[str, Any]) -> None:
    if str(envelope.get("stage") or "").strip().lower() != "tool_call":
        return
    payload = envelope.get("payload", {})
    if not isinstance(payload, dict):
        return
    tool_name = str(payload.get("tool_name") or "").strip()
    if not tool_name:
        return
    outcome = str(envelope.get("outcome") or payload.get("status") or "").strip().lower()
    status = str(payload.get("status") or outcome).strip().lower()
    latency_ms = max(0, _safe_int(payload.get("latency_ms"), 0))
    error_code = str(payload.get("error_code") or "").strip().lower()

    with _TOOL_METRICS_LOCK:
        metric = _TOOL_METRICS.setdefault(
            tool_name,
            {
                "started": 0,
                "completed": 0,
                "status_counts": {},
                "latencies_ms": [],
                "error_codes": {},
            },
        )

        if outcome == "start":
            metric["started"] = int(metric.get("started", 0)) + 1
            return

        metric["completed"] = int(metric.get("completed", 0)) + 1
        status_counts = metric.get("status_counts")
        if isinstance(status_counts, dict):
            status_counts[status] = int(status_counts.get(status, 0)) + 1
        else:
            metric["status_counts"] = {status: 1}

        if latency_ms > 0:
            latencies = metric.get("latencies_ms")
            if isinstance(latencies, list):
                latencies.append(latency_ms)
                if len(latencies) > 5000:
                    del latencies[: len(latencies) - 5000]
            else:
                metric["latencies_ms"] = [latency_ms]

        if error_code:
            error_counts = metric.get("error_codes")
            if isinstance(error_counts, dict):
                error_counts[error_code] = int(error_counts.get(error_code, 0)) + 1
            else:
                metric["error_codes"] = {error_code: 1}


def reset_tool_metrics() -> None:
    with _TOOL_METRICS_LOCK:
        _TOOL_METRICS.clear()


def get_tool_metrics_snapshot(*, reset_after_read: bool = False) -> Dict[str, Any]:
    with _TOOL_METRICS_LOCK:
        raw = json.loads(json.dumps(_TOOL_METRICS))
        if reset_after_read:
            _TOOL_METRICS.clear()
    tools: Dict[str, Any] = {}
    for tool_name, metric in raw.items():
        status_counts = metric.get("status_counts", {}) if isinstance(metric.get("status_counts"), dict) else {}
        latencies = metric.get("latencies_ms", []) if isinstance(metric.get("latencies_ms"), list) else []
        completed = max(0, _safe_int(metric.get("completed"), 0))
        ok_count = max(0, _safe_int(status_counts.get("ok"), 0))
        timeout_count = max(0, _safe_int(status_counts.get("timeout"), 0))
        error_count = max(0, _safe_int(status_counts.get("error"), 0))
        tools[tool_name] = {
            "started": max(0, _safe_int(metric.get("started"), 0)),
            "completed": completed,
            "status_counts": status_counts,
            "latency_ms": {
                "count": len(latencies),
                "p50": _latency_percentile(latencies, 0.50),
                "p95": _latency_percentile(latencies, 0.95),
            },
            "error_codes": metric.get("error_codes", {}) if isinstance(metric.get("error_codes"), dict) else {},
            "ok_rate": (ok_count / completed) if completed > 0 else 0.0,
            "failure_rate": ((timeout_count + error_count) / completed) if completed > 0 else 0.0,
        }
    return {
        "generated_at": _utc_now_iso(),
        "tool_count": len(tools),
        "tools": tools,
    }


def emit_trace_event(
    *,
    trace_id: str,
    stage: str,
    outcome: str,
    reason_codes: Iterable[str] | None = None,
    payload: Dict[str, Any] | None = None,
) -> None:
    envelope = {
        "timestamp": _utc_now_iso(),
        "trace_id": str(trace_id or ""),
        "stage": str(stage or ""),
        "outcome": str(outcome or ""),
        "reason_codes": [str(code).strip() for code in (reason_codes or []) if str(code).strip()],
        "payload": payload or {},
    }
    _update_tool_metrics(envelope)
    logger.info("trace_event %s", json.dumps(envelope, ensure_ascii=True, default=str))
    try:
        _get_exporter().export_trace(envelope)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trace_export_failed trace=%s stage=%s error=%s", trace_id, stage, exc)
