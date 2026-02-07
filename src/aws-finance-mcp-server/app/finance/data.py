from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.supabase_rest import SupabaseRestClient

from .common import parse_datetime


def fetch_transactions_in_window(
    client: SupabaseRestClient,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
) -> List[Dict[str, Any]]:
    rows = client.fetch_rows(
        "transactions",
        select="id,user_id,jar_id,category_id,amount,currency,counterparty,raw_narrative,occurred_at,direction",
        filters={
            "user_id": f"eq.{user_id}",
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
        select="id,user_id,name,description,target_amount",
        filters={"user_id": f"eq.{user_id}"},
        order="name.asc",
    )


def fetch_categories(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "categories",
        select="id,user_id,name,parent_id",
        filters={"user_id": f"eq.{user_id}"},
        order="name.asc",
    )


def fetch_budgets(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "budgets",
        select="id,user_id,scope_type,scope_id,period,limit_amount,currency,active",
        filters={"user_id": f"eq.{user_id}", "active": "eq.true"},
        order="created_at.asc",
    )


def fetch_goals(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "goals",
        select="id,user_id,name,target_amount,horizon_months",
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.asc",
    )


def fetch_income_sources(client: SupabaseRestClient, user_id: str) -> List[Dict[str, Any]]:
    return client.fetch_rows(
        "income_sources",
        select="id,user_id,source_name,monthly_amount,updated_at",
        filters={"user_id": f"eq.{user_id}"},
        order="updated_at.desc",
    )


def write_audit_event(
    client: SupabaseRestClient,
    *,
    user_id: str,
    trace_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    try:
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
    except Exception:
        return


def write_decision_event(
    client: SupabaseRestClient,
    *,
    user_id: str,
    trace_id: str,
    decision_type: str,
    decision: str,
    payload: Dict[str, Any],
) -> None:
    try:
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
    except Exception:
        return
