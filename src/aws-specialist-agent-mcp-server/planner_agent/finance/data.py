from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from .supabase_rest import SupabaseRestClient

from .common import iso_utc, parse_datetime


VALID_FEEDBACK_LABELS = {"confirmed", "false_positive", "expected"}
VALID_ACTOR_TYPES = {"user", "analyst", "system"}
OPTIONAL_SCHEMA_TABLES = {"audit_event_log", "audit_decision_log"}


def _normalize_feedback_label(value: Any) -> str | None:
    label = str(value or "").strip().lower()
    if label not in VALID_FEEDBACK_LABELS:
        return None
    return label


def _normalize_actor_type(value: Any, feedback_source: Any) -> str:
    actor_type = str(value or "").strip().lower()
    if actor_type in VALID_ACTOR_TYPES:
        return actor_type
    source = str(feedback_source or "").strip().lower()
    if source in {"user", "manual_user", "mobile", "web"}:
        return "user"
    if source in {"analyst", "ops", "reviewer"}:
        return "analyst"
    return "system"


def _normalize_feedback_row(row: Dict[str, Any], *, for_write: bool) -> Dict[str, Any] | None:
    trace_id = str(row.get("trace_id") or "").strip()
    label = _normalize_feedback_label(row.get("feedback_label"))
    if not trace_id or not label:
        return None
    normalized = dict(row)
    normalized["trace_id"] = trace_id
    normalized["feedback_label"] = label
    actor_type = _normalize_actor_type(row.get("actor_type"), row.get("feedback_source"))
    payload = normalized.get("payload") if isinstance(normalized.get("payload"), dict) else {}
    normalized["payload"] = {**payload, "actor_type": actor_type}
    normalized.pop("actor_type", None)
    normalized["feedback_source"] = actor_type
    if for_write:
        normalized["created_at"] = str(normalized.get("created_at") or iso_utc())
    else:
        normalized["actor_type"] = actor_type
    return normalized


def _select_columns(client: SupabaseRestClient, table: str, columns: str) -> str:
    available = client.table_columns(table)
    if not available:
        return columns
    requested = [item.strip() for item in str(columns or "").split(",") if item.strip()]
    selected = [item for item in requested if item in available]
    return ",".join(selected) if selected else "*"


def _table_supported(client: SupabaseRestClient, table: str) -> bool:
    if table not in OPTIONAL_SCHEMA_TABLES:
        return True
    return client.table_exists(table)


def fetch_transactions_in_window(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
) -> List[Dict[str, Any]]:
    rows = client.fetch_rows(
        "transactions",
        select=_select_columns(
            client,
            "transactions",
            "id,user_id,jar_id,category_id,amount,currency,counterparty,raw_narrative,user_note,channel,occurred_at,created_at,direction",
        ),
        filters={
            "user_id": f"eq.{user_id}",
            "occurred_at__gte": iso_utc(start_at),
            "occurred_at__lte": iso_utc(end_at),
        },
        order="occurred_at.asc",
    )
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        occurred = parse_datetime(row.get("occurred_at"))
        if not occurred:
            continue
        if start_at <= occurred <= end_at:
            filtered.append(row)
    return filtered


def fetch_jars(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "jars",
        select=_select_columns(client, "jars", "id,user_id,template_id,name,description,keywords,target_amount,created_at,updated_at"),
        filters={"user_id": f"eq.{user_id}"},
        order="name.asc",
    )


def fetch_categories(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "categories",
        select=_select_columns(client, "categories", "id,user_id,parent_id,name"),
        filters={"user_id": f"eq.{user_id}"},
        order="name.asc",
    )


def fetch_budgets(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "budgets",
        select=_select_columns(
            client,
            "budgets",
            "id,user_id,scope_type,scope_id,period,limit_amount,currency,active,created_at,updated_at",
        ),
        filters={"user_id": f"eq.{user_id}", "active": "eq.true"},
        order="created_at.asc",
    )


def fetch_goals(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "goals",
        select=_select_columns(client, "goals", "id,user_id,name,target_amount,horizon_months,created_at"),
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.asc",
    )


def fetch_income_sources(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "income_sources",
        select=_select_columns(client, "income_sources", "id,user_id,source_name,monthly_amount,updated_at"),
        filters={"user_id": f"eq.{user_id}"},
        order="updated_at.desc",
    )


def fetch_profiles(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "profiles",
        select=_select_columns(client, "profiles", "user_id,display_name,risk_profile_current,locale,updated_at"),
        filters={"user_id": f"eq.{user_id}"},
        order="updated_at.desc",
    )


def fetch_balance_daily(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
) -> List[Dict[str, Any]]:
    rows = client.fetch_rows(
        "balance_daily",
        select=_select_columns(
            client,
            "balance_daily",
            "id,user_id,balance_date,scope_type,scope_id,currency,opening_balance,inflow_total,outflow_total,closing_balance,source,quality_flag,payload,created_at,updated_at",
        ),
        filters={
            "user_id": f"eq.{user_id}",
            "balance_date__gte": start_at.date().isoformat(),
            "balance_date__lte": end_at.date().isoformat(),
        },
        order="balance_date.asc",
    )
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        balance_date = parse_datetime(str(row.get("balance_date") or ""))
        if not balance_date:
            continue
        if start_at.date() <= balance_date.date() <= end_at.date():
            filtered.append(row)
    return filtered


def fetch_forecast_actuals_history(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
    tool_name: str | None = None,
) -> List[Dict[str, Any]]:
    filters = {"user_id": f"eq.{user_id}", "actual_value": "not.is.null"}
    if tool_name:
        filters["tool_name"] = f"eq.{tool_name}"
    filters["forecast_as_of__gte"] = iso_utc(start_at)
    filters["forecast_as_of__lte"] = iso_utc(end_at)
    rows = client.fetch_rows(
        "forecast_actuals_log",
        select=_select_columns(
            client,
            "forecast_actuals_log",
            "id,user_id,trace_id,tool_name,model_name,horizon,granularity,forecast_as_of,target_start,target_end,predicted_p10,predicted_p50,predicted_p90,actual_value,actual_recorded_at,error_signed,error_abs,within_p80,within_p90,payload,created_at",
        ),
        filters=filters,
        order="forecast_as_of.desc",
    )
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        forecast_as_of = parse_datetime(row.get("forecast_as_of"))
        target_end = parse_datetime(str(row.get("target_end") or ""))
        if not forecast_as_of or not target_end:
            continue
        if start_at <= forecast_as_of <= end_at and target_end.date() <= end_at.date():
            filtered.append(row)
    return filtered


def fetch_audit_events(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
    event_type: str | None = None,
) -> List[Dict[str, Any]]:
    if not _table_supported(client, "audit_event_log"):
        return []
    filters = {"user_id": f"eq.{user_id}"}
    if event_type:
        filters["event_type"] = f"eq.{event_type}"
    filters["created_at__gte"] = iso_utc(start_at)
    filters["created_at__lte"] = iso_utc(end_at)
    rows = client.fetch_rows(
        "audit_event_log",
        select=_select_columns(client, "audit_event_log", "id,user_id,trace_id,event_type,payload,created_at"),
        filters=filters,
        order="created_at.desc",
    )
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        created_at = parse_datetime(row.get("created_at"))
        if not created_at:
            continue
        if start_at <= created_at <= end_at:
            filtered.append(row)
    return filtered


def fetch_anomaly_feedback(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
) -> List[Dict[str, Any]]:
    rows = client.fetch_rows(
        "anomaly_feedback_log",
        select=_select_columns(
            client,
            "anomaly_feedback_log",
            "id,user_id,trace_id,tool_name,anomaly_type,detector_name,entity_type,entity_id,feedback_label,feedback_source,note,payload,resolved_at,created_at",
        ),
        filters={
            "user_id": f"eq.{user_id}",
            "created_at__gte": iso_utc(start_at),
            "created_at__lte": iso_utc(end_at),
        },
        order="created_at.desc",
    )
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        created_at = parse_datetime(row.get("created_at"))
        if not created_at:
            continue
        if start_at <= created_at <= end_at:
            normalized = _normalize_feedback_row(row, for_write=False)
            if normalized:
                filtered.append(normalized)
    return filtered


def fetch_allocation_decision_history(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
) -> List[Dict[str, Any]]:
    rows = client.fetch_rows(
        "allocation_decision_log",
        select=_select_columns(
            client,
            "allocation_decision_log",
            "id,user_id,trace_id,tool_name,decision_status,monthly_income_reference,recommendation_payload,final_allocation_payload,execution_payload,note,decided_at,created_at",
        ),
        filters={
            "user_id": f"eq.{user_id}",
            "created_at__gte": iso_utc(start_at),
            "created_at__lte": iso_utc(end_at),
        },
        order="created_at.desc",
    )
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        created_at = parse_datetime(row.get("created_at"))
        if not created_at:
            continue
        if start_at <= created_at <= end_at:
            filtered.append(row)
    return filtered


def write_forecast_actuals_rows(client: SupabaseRestClient, rows: List[Dict[str, Any]]) -> None:
    client.upsert_rows(
        "forecast_actuals_log",
        rows,
        on_conflict="user_id,tool_name,horizon,granularity,forecast_as_of,target_start,target_end",
    )


def write_balance_daily_rows(client: SupabaseRestClient, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        client.upsert_rows(
            "balance_daily",
            rows,
            on_conflict="user_id,balance_date,scope_type,scope_id,currency,source",
        )
        return
    except Exception:
        # `balance_daily` uses a unique index with `coalesce(scope_id, ...)`, which
        # PostgREST cannot always target through `on_conflict`. Fall back to
        # replacing the affected derived rows within the requested date window.
        grouped: Dict[tuple[str, str, str | None, str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            key = (
                str(row.get("user_id") or ""),
                str(row.get("scope_type") or "overall"),
                str(row.get("scope_id")) if row.get("scope_id") is not None else None,
                str(row.get("currency") or "VND"),
                str(row.get("source") or "derived"),
            )
            grouped.setdefault(key, []).append(row)

        for (user_id, scope_type, scope_id, currency, source), group_rows in grouped.items():
            dates = [str(item.get("balance_date") or "") for item in group_rows if str(item.get("balance_date") or "")]
            if not user_id or not dates:
                continue
            filters = {
                "user_id": f"eq.{user_id}",
                "scope_type": f"eq.{scope_type}",
                "currency": f"eq.{currency}",
                "source": f"eq.{source}",
            }
            # Replace all matching derived rows for this scope/source. The current
            # backfill script writes a full synthetic history, so full-scope
            # replacement is acceptable and avoids fragile range filtering.
            if scope_id is None:
                filters["scope_id"] = "is.null"
            else:
                filters["scope_id"] = f"eq.{scope_id}"
            try:
                client.delete_rows("balance_daily", filters=filters)
            except Exception:
                pass

        batch_size = 500
        for idx in range(0, len(rows), batch_size):
            client.insert_rows("balance_daily", rows[idx:idx + batch_size])


def write_anomaly_feedback_rows(client: SupabaseRestClient, rows: List[Dict[str, Any]]) -> None:
    normalized_rows = []
    for row in rows:
        normalized = _normalize_feedback_row(row, for_write=True)
        if not normalized:
            continue
        normalized_rows.append(normalized)
    if not normalized_rows:
        return
    client.insert_rows("anomaly_feedback_log", normalized_rows)


def write_audit_event(
    client: SupabaseRestClient,
    *,
    user_id: str,
    trace_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    if not _table_supported(client, "audit_event_log"):
        return
    client.insert_rows(
        "audit_event_log",
        [
            {
                "user_id": user_id,
                "trace_id": trace_id,
                "event_type": event_type,
                "payload": payload,
            }
        ],
    )


def write_decision_event(
    client: SupabaseRestClient,
    *,
    user_id: str,
    trace_id: str,
    decision_type: str,
    decision: str,
    payload: Dict[str, Any],
) -> None:
    if not _table_supported(client, "audit_decision_log"):
        return
    client.insert_rows(
        "audit_decision_log",
        [
            {
                "user_id": user_id,
                "trace_id": trace_id,
                "decision_type": decision_type,
                "decision": decision,
                "payload": payload,
            }
        ],
    )


