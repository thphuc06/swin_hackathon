from __future__ import annotations

from typing import Any, Dict, List

from .supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_output,
    build_provenance,
    build_reliability,
    build_validation,
    ensure_user_scope,
    iso_utc,
    new_trace_id,
    now_utc,
)
from .data import write_anomaly_feedback_rows, write_audit_event
from .trust import build_trust

TOOL_NAME = "record_anomaly_feedback_v1"
SOURCE_TOOL_NAME = "anomaly_signals_v1"
DEFAULT_OPTIONS: List[Dict[str, str]] = [
    {
        "label": "ÄÃºng lÃ  báº¥t thÆ°á»ng",
        "feedback_label": "confirmed",
        "description": "XÃ¡c nháº­n alert nÃ y lÃ  báº¥t thÆ°á»ng tháº­t.",
    },
    {
        "label": "BÃ¬nh thÆ°á»ng / bÃ¡o sai",
        "feedback_label": "false_positive",
        "description": "BÃ¡o Ä‘á»™ng giáº£, khÃ´ng nÃªn xem lÃ  anomaly.",
    },
    {
        "label": "Há»£p lá»‡ nhÆ°ng Ä‘Ã£ biáº¿t trÆ°á»›c",
        "feedback_label": "expected",
        "description": "Giao dá»‹ch láº¡ nhÆ°ng há»£p lá»‡ hoáº·c Ä‘Ã£ Ä‘Æ°á»£c biáº¿t trÆ°á»›c.",
    },
]
LABEL_DISPLAY = {
    "confirmed": "ÄÃºng lÃ  báº¥t thÆ°á»ng",
    "false_positive": "BÃ¬nh thÆ°á»ng / bÃ¡o sai",
    "expected": "Há»£p lá»‡ nhÆ°ng Ä‘Ã£ biáº¿t trÆ°á»›c",
}


def anomaly_feedback_options() -> List[Dict[str, str]]:
    return [dict(item) for item in DEFAULT_OPTIONS]


def _load_trace_audit(
    client: SupabaseRestClient,
    *,
    user_id: str,
    trace_id: str,
) -> Dict[str, Any] | None:
    if not client.table_exists("audit_event_log"):
        return None
    rows = client.fetch_rows(
        "audit_event_log",
        select="id,user_id,trace_id,event_type,payload,created_at",
        filters={
            "user_id": f"eq.{user_id}",
            "trace_id": f"eq.{trace_id}",
            "event_type": f"eq.{SOURCE_TOOL_NAME}",
        },
        order="created_at.desc",
    )
    return dict(rows[0]) if rows else None


def record_anomaly_feedback(
    *,
    auth_user_id: str,
    user_id: str,
    trace_id: str,
    feedback_label: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    anomaly_type: str | None = None,
    detector_name: str | None = None,
    feedback_source: str = "web",
    actor_type: str | None = None,
    note: str | None = None,
    resolved_at: str | None = None,
    created_at: str | None = None,
    source_confidence_score: float | None = None,
    source_flags: List[str] | None = None,
    source_as_of: str | None = None,
    trace_id_override: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    write_trace = new_trace_id(trace_id_override)
    ensure_user_scope(auth_user_id, user_id)

    normalized_trace_id = str(trace_id or "").strip()
    normalized_label = str(feedback_label or "").strip().lower()
    if not normalized_trace_id:
        raise ValueError("trace_id is required")
    if normalized_label not in LABEL_DISPLAY:
        raise ValueError("feedback_label must be one of confirmed, false_positive, expected")

    sql = client or get_supabase_client()
    linked_audit_event = _load_trace_audit(sql, user_id=user_id, trace_id=normalized_trace_id)
    payload = linked_audit_event.get("payload") if isinstance((linked_audit_event or {}).get("payload"), dict) else {}
    audit_result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    audit_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    fallback_source_score = None if source_confidence_score is None else round(float(source_confidence_score), 4)
    fallback_source_flags = [str(item) for item in (source_flags or []) if str(item or "").strip()]
    recalibration_eligible = bool(linked_audit_event) or fallback_source_score is not None

    row = {
        "user_id": user_id,
        "trace_id": normalized_trace_id,
        "tool_name": SOURCE_TOOL_NAME,
        "anomaly_type": str(anomaly_type or "trace_review"),
        "detector_name": str(detector_name or "human_review"),
        "entity_type": str(entity_type or "other"),
        "entity_id": str(entity_id or normalized_trace_id),
        "feedback_label": normalized_label,
        "feedback_source": str(feedback_source or "web"),
        "actor_type": actor_type,
        "note": str(note or "").strip() or None,
        "resolved_at": str(resolved_at or iso_utc()),
        "created_at": str(created_at or "").strip() or None,
        "payload": {
            "ingested_by": TOOL_NAME,
            "linked_audit_event_found": bool(linked_audit_event),
            "audit_event_created_at": linked_audit_event.get("created_at") if linked_audit_event else None,
            "audit_result_flags": audit_result.get("flags") if isinstance(audit_result.get("flags"), list) else None,
            "source_confidence_score": fallback_source_score,
            "source_flags": fallback_source_flags,
            "source_as_of": str(source_as_of or "").strip() or None,
            "source_signal_origin": "audit_event_log" if linked_audit_event else ("tool_payload" if fallback_source_score is not None else None),
        },
    }
    write_anomaly_feedback_rows(sql, [row])
    write_audit_event(
        sql,
        user_id=user_id,
        trace_id=write_trace,
        event_type=TOOL_NAME,
        payload={
            "params": {
                "user_id": user_id,
                "trace_id": normalized_trace_id,
                "feedback_label": normalized_label,
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
            },
            "result": {
                "recorded": True,
                "linked_audit_event_found": bool(linked_audit_event),
                "recalibration_eligible": recalibration_eligible,
            },
        },
    )

    reliability = build_reliability(
        confidence_score=0.99 if linked_audit_event else (0.9 if fallback_source_score is not None else 0.72),
        components={
            "audit_linkage": 1.0 if linked_audit_event else 0.0,
            "fallback_source_snapshot": 1.0 if fallback_source_score is not None else 0.0,
            "write_path": 1.0,
        },
        reason_codes=[] if linked_audit_event else (["audit_missing_used_tool_snapshot"] if fallback_source_score is not None else ["trace_not_found_in_audit_log"]),
    )
    trust_bundle = build_trust(
        confidence_score=float(reliability["confidence_score"]),
        reliability_components=reliability.get("components"),
        abstain_recommended=bool(reliability.get("abstain_recommended")),
        prior_alpha=99.0,
        prior_beta=1.0,
    )

    return build_output(
        tool_name=TOOL_NAME,
        tool_input={
            "user_id": user_id,
            "trace_id": normalized_trace_id,
            "feedback_label": normalized_label,
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
        },
        payload={
            "recorded": True,
            "feedback_label": normalized_label,
            "feedback_label_display": LABEL_DISPLAY[normalized_label],
            "feedback_options": anomaly_feedback_options(),
            "target": {
                "trace_id": normalized_trace_id,
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "anomaly_type": row["anomaly_type"],
                "detector_name": row["detector_name"],
            },
            "linkage": {
                "audit_event_found": bool(linked_audit_event),
                "recalibration_eligible": recalibration_eligible,
                "source_tool_name": SOURCE_TOOL_NAME,
                "source_tool_created_at": linked_audit_event.get("created_at") if linked_audit_event else None,
                "source_flags": audit_result.get("flags") if isinstance(audit_result.get("flags"), list) else fallback_source_flags,
                "source_confidence_score": audit_result.get("confidence_score") if audit_result.get("confidence_score") is not None else fallback_source_score,
                "source_params": audit_params,
                "fallback_source_snapshot_used": fallback_source_score is not None and not bool(linked_audit_event),
            },
        },
        trace_id=write_trace,
        started_at=started_at,
        sql_snapshot_ts=iso_utc(),
        as_of=iso_utc(),
        reliability=reliability,
        trust=trust_bundle["trust"],
        agent_use=trust_bundle["agent_use"],
        provenance=build_provenance(
            library="supabase_rest",
            model="human_feedback_ingest_v1",
            model_version="feedback_ingest_v1",
        ),
        validation=build_validation(
            linked_audit_event_found=bool(linked_audit_event),
            fallback_source_snapshot_used=fallback_source_score is not None and not bool(linked_audit_event),
            source_confidence_score=fallback_source_score,
            source_tool_name=SOURCE_TOOL_NAME,
        ),
    )


