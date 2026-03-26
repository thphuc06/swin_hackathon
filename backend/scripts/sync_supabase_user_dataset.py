"""Synchronize one Supabase user-scoped dataset into another user id.

This is a provisioning utility, not a runtime dependency of the deployed flow.
It is intended for smoke-user setup, Cognito-sub alignment, and controlled data
migration when the live database user id must match the authenticated subject.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.supabase_rest import SupabaseRestClient  # noqa: E402

SYNC_NAMESPACE = uuid.UUID("c4ca7be2-10ef-45d5-8e17-3cb43d19f1f7")
TABLE_FETCH_ORDER = [
    "users",
    "profiles",
    "jars",
    "categories",
    "income_sources",
    "income_events",
    "goals",
    "budgets",
    "transactions",
    "balance_daily",
    "forecast_actuals_log",
    "anomaly_feedback_log",
    "allocation_decision_log",
]
TABLE_DELETE_ORDER = [
    "allocation_decision_log",
    "anomaly_feedback_log",
    "forecast_actuals_log",
    "balance_daily",
    "transactions",
    "income_events",
    "budgets",
    "goals",
    "categories",
    "income_sources",
    "jars",
    "profiles",
    "users",
]
TABLE_INSERT_ORDER = [
    "users",
    "profiles",
    "jars",
    "categories",
    "income_sources",
    "goals",
    "budgets",
    "transactions",
    "income_events",
    "balance_daily",
    "forecast_actuals_log",
    "anomaly_feedback_log",
    "allocation_decision_log",
]
USER_SCOPED_TABLES = [table for table in TABLE_FETCH_ORDER if table != "users"]


def load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _derive_target_email(target_user_id: str) -> str:
    token = hashlib.sha256(target_user_id.encode("utf-8")).hexdigest()[:12]
    return f"user_{token}@seed.local"


def _stable_uuid(kind: str, target_user_id: str, source_id: str) -> str:
    return str(uuid.uuid5(SYNC_NAMESPACE, f"{kind}:{target_user_id}:{source_id}"))


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _fetch_user_rows(client: SupabaseRestClient, table: str, user_id: str) -> List[Dict[str, Any]]:
    if table == "users":
        return client.fetch_rows(table, select="*", filters={"id": f"eq.{user_id}"}, page_size=1000)
    return client.fetch_rows(table, select="*", filters={"user_id": f"eq.{user_id}"}, page_size=1000)


def _insert_chunks(client: SupabaseRestClient, table: str, rows: List[Dict[str, Any]], chunk_size: int = 500) -> None:
    if not rows:
        return
    for idx in range(0, len(rows), chunk_size):
        client.insert_rows(table, rows[idx:idx + chunk_size])


def _delete_target_rows(client: SupabaseRestClient, target_user_id: str, existing_tables: set[str]) -> None:
    for table in TABLE_DELETE_ORDER:
        if table not in existing_tables:
            continue
        if table == "users":
            client.delete_rows("users", filters={"id": f"eq.{target_user_id}"})
        else:
            client.delete_rows(table, filters={"user_id": f"eq.{target_user_id}"})


def _deep_remap_ids(value: Any, id_map: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {str(key): _deep_remap_ids(item, id_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_remap_ids(item, id_map) for item in value]
    if isinstance(value, str):
        return id_map.get(value, value)
    return value


def _remap_known_id(value: Any, id_map: Mapping[str, str]) -> Any:
    text = str(value).strip()
    if not text:
        return value
    return id_map.get(text, value)


def _build_id_maps(source_rows: Mapping[str, List[Dict[str, Any]]], target_user_id: str) -> Dict[str, Dict[str, str]]:
    maps: Dict[str, Dict[str, str]] = {"users": {}}
    maps["users"] = {}
    for table in ("jars", "categories", "income_sources", "goals", "budgets", "transactions", "income_events", "balance_daily", "forecast_actuals_log", "anomaly_feedback_log", "allocation_decision_log"):
        table_map: Dict[str, str] = {}
        for row in source_rows.get(table, []):
            source_id = str(row.get("id") or "").strip()
            if source_id:
                table_map[source_id] = _stable_uuid(table, target_user_id, source_id)
        maps[table] = table_map
    return maps


def _combined_id_map(source_user_id: str, target_user_id: str, id_maps: Mapping[str, Mapping[str, str]]) -> Dict[str, str]:
    combined = {source_user_id: target_user_id}
    for table_map in id_maps.values():
        combined.update(table_map)
    return combined


def _transform_users(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    target_email: str,
) -> List[Dict[str, Any]]:
    if not source_rows:
        return [{"id": target_user_id, "email": target_email}]
    row = dict(_json_clone(source_rows[0]))
    row["id"] = target_user_id
    row["email"] = target_email
    return [row]


def _transform_profiles(source_rows: List[Dict[str, Any]], *, target_user_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in source_rows:
        cloned = dict(_json_clone(row))
        cloned["user_id"] = target_user_id
        out.append(cloned)
    return out


def _transform_simple_id_table(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in source_rows:
        cloned = dict(_deep_remap_ids(_json_clone(row), combined_id_map))
        source_id = str(row.get("id") or "").strip()
        if source_id and source_id in table_id_map:
            cloned["id"] = table_id_map[source_id]
        cloned["user_id"] = target_user_id
        out.append(cloned)
    return out


def _transform_categories(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        if row.get("parent_id") is not None:
            row["parent_id"] = _remap_known_id(row.get("parent_id"), combined_id_map)
    return out


def _transform_budgets(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        if row.get("scope_id") is not None:
            row["scope_id"] = _remap_known_id(row.get("scope_id"), combined_id_map)
    return out


def _transform_transactions(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        if row.get("jar_id") is not None:
            row["jar_id"] = _remap_known_id(row.get("jar_id"), combined_id_map)
        if row.get("category_id") is not None:
            row["category_id"] = _remap_known_id(row.get("category_id"), combined_id_map)
    return out


def _transform_income_events(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        if row.get("source_id") is not None:
            row["source_id"] = _remap_known_id(row.get("source_id"), combined_id_map)
    return out


def _transform_balance_daily(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        if row.get("scope_id") is not None:
            row["scope_id"] = _remap_known_id(row.get("scope_id"), combined_id_map)
        payload = row.get("payload")
        if payload is not None:
            row["payload"] = _deep_remap_ids(payload, combined_id_map)
    return out


def _transform_anomaly_feedback(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        if row.get("entity_id") is not None:
            row["entity_id"] = _remap_known_id(row.get("entity_id"), combined_id_map)
        payload = row.get("payload")
        if payload is not None:
            row["payload"] = _deep_remap_ids(payload, combined_id_map)
    return out


def _transform_allocation_decisions(
    source_rows: List[Dict[str, Any]],
    *,
    target_user_id: str,
    table_id_map: Mapping[str, str],
    combined_id_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    out = _transform_simple_id_table(
        source_rows,
        target_user_id=target_user_id,
        table_id_map=table_id_map,
        combined_id_map=combined_id_map,
    )
    for row in out:
        for key in ("recommendation_payload", "final_allocation_payload", "execution_payload"):
            if row.get(key) is not None:
                row[key] = _deep_remap_ids(row.get(key), combined_id_map)
    return out


def _transform_source_rows(
    source_rows: Mapping[str, List[Dict[str, Any]]],
    *,
    source_user_id: str,
    target_user_id: str,
    target_email: str,
) -> Dict[str, List[Dict[str, Any]]]:
    id_maps = _build_id_maps(source_rows, target_user_id)
    combined = _combined_id_map(source_user_id, target_user_id, id_maps)

    transformed: Dict[str, List[Dict[str, Any]]] = {}
    transformed["users"] = _transform_users(source_rows.get("users", []), target_user_id=target_user_id, target_email=target_email)
    transformed["profiles"] = _transform_profiles(source_rows.get("profiles", []), target_user_id=target_user_id)
    transformed["jars"] = _transform_simple_id_table(source_rows.get("jars", []), target_user_id=target_user_id, table_id_map=id_maps["jars"], combined_id_map=combined)
    transformed["categories"] = _transform_categories(source_rows.get("categories", []), target_user_id=target_user_id, table_id_map=id_maps["categories"], combined_id_map=combined)
    transformed["income_sources"] = _transform_simple_id_table(source_rows.get("income_sources", []), target_user_id=target_user_id, table_id_map=id_maps["income_sources"], combined_id_map=combined)
    transformed["income_events"] = _transform_income_events(source_rows.get("income_events", []), target_user_id=target_user_id, table_id_map=id_maps["income_events"], combined_id_map=combined)
    transformed["goals"] = _transform_simple_id_table(source_rows.get("goals", []), target_user_id=target_user_id, table_id_map=id_maps["goals"], combined_id_map=combined)
    transformed["budgets"] = _transform_budgets(source_rows.get("budgets", []), target_user_id=target_user_id, table_id_map=id_maps["budgets"], combined_id_map=combined)
    transformed["transactions"] = _transform_transactions(source_rows.get("transactions", []), target_user_id=target_user_id, table_id_map=id_maps["transactions"], combined_id_map=combined)
    transformed["balance_daily"] = _transform_balance_daily(source_rows.get("balance_daily", []), target_user_id=target_user_id, table_id_map=id_maps["balance_daily"], combined_id_map=combined)
    transformed["forecast_actuals_log"] = _transform_simple_id_table(source_rows.get("forecast_actuals_log", []), target_user_id=target_user_id, table_id_map=id_maps["forecast_actuals_log"], combined_id_map=combined)
    transformed["anomaly_feedback_log"] = _transform_anomaly_feedback(source_rows.get("anomaly_feedback_log", []), target_user_id=target_user_id, table_id_map=id_maps["anomaly_feedback_log"], combined_id_map=combined)
    transformed["allocation_decision_log"] = _transform_allocation_decisions(source_rows.get("allocation_decision_log", []), target_user_id=target_user_id, table_id_map=id_maps["allocation_decision_log"], combined_id_map=combined)
    return transformed


def _count_rows(client: SupabaseRestClient, table: str, user_id: str) -> int:
    return len(_fetch_user_rows(client, table, user_id))


def _transaction_range(client: SupabaseRestClient, user_id: str) -> Dict[str, Any]:
    rows = client.fetch_rows(
        "transactions",
        select="occurred_at",
        filters={"user_id": f"eq.{user_id}"},
        order="occurred_at.asc",
        page_size=1,
    )
    tail_rows = client.fetch_rows(
        "transactions",
        select="occurred_at",
        filters={"user_id": f"eq.{user_id}"},
        order="occurred_at.desc",
        page_size=1,
    )
    return {
        "min": rows[0]["occurred_at"] if rows else None,
        "max": tail_rows[0]["occurred_at"] if tail_rows else None,
    }


def build_sync_report(
    client: SupabaseRestClient,
    *,
    source_user_id: str,
    target_user_id: str,
    target_email: str,
    existing_tables: set[str],
    source_rows: Mapping[str, List[Dict[str, Any]]],
    transformed: Mapping[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    return {
        "source_user_id": source_user_id,
        "target_user_id": target_user_id,
        "target_email": target_email,
        "schema_tables": sorted(existing_tables),
        "source_counts": {table: len(source_rows.get(table, [])) for table in TABLE_FETCH_ORDER if table in existing_tables},
        "inserted_counts": {table: len(transformed.get(table, [])) for table in TABLE_FETCH_ORDER if table in existing_tables},
        "verified_counts": {
            "users": _count_rows(client, "users", target_user_id) if "users" in existing_tables else 0,
            **{table: _count_rows(client, table, target_user_id) for table in USER_SCOPED_TABLES if table in existing_tables},
        },
        "transaction_range": _transaction_range(client, target_user_id) if "transactions" in existing_tables else {"min": None, "max": None},
    }


def sync_user_dataset(
    *,
    source_user_id: str,
    target_user_id: str,
    target_email: str = "",
    supabase_url: str,
    service_role_key: str,
    timeout: int = 45,
    report_path: Path | None = None,
) -> Dict[str, Any]:
    client = SupabaseRestClient(supabase_url=supabase_url, service_key=service_role_key, timeout=int(timeout))
    existing_tables = {table for table in TABLE_FETCH_ORDER if client.table_exists(table)}

    source_rows = {table: _fetch_user_rows(client, table, source_user_id) for table in TABLE_FETCH_ORDER if table in existing_tables}
    if "users" not in source_rows or not source_rows["users"]:
        raise RuntimeError(f"Source user {source_user_id} does not exist in users table.")

    target_user_rows = _fetch_user_rows(client, "users", target_user_id) if "users" in existing_tables else []
    resolved_target_email = str(target_email or "").strip()
    if not resolved_target_email and target_user_rows:
        resolved_target_email = str(target_user_rows[0].get("email") or "").strip()
    if not resolved_target_email:
        resolved_target_email = _derive_target_email(target_user_id)

    transformed = _transform_source_rows(
        source_rows,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        target_email=resolved_target_email,
    )

    _delete_target_rows(client, target_user_id, existing_tables)
    for table in TABLE_INSERT_ORDER:
        if table not in existing_tables:
            continue
        _insert_chunks(client, table, transformed.get(table, []))

    report = build_sync_report(
        client,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        target_email=resolved_target_email,
        existing_tables=existing_tables,
        source_rows=source_rows,
        transformed=transformed,
    )

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clone one Supabase user-scoped dataset into another user id.")
    parser.add_argument("--source-user-id", required=True)
    parser.add_argument("--target-user-id", required=True)
    parser.add_argument("--target-email", default="")
    parser.add_argument("--env-file", default="")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--timeout", type=int, default=45)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_file:
        load_env_file(Path(args.env_file))

    supabase_url = str(os.getenv("SUPABASE_URL") or "").strip()
    service_role_key = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not supabase_url or not service_role_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set via env or --env-file.")

    report_path = Path(args.report_path) if args.report_path else REPO_ROOT / "backend" / "tmp" / f"supabase_sync_{args.target_user_id}.json"
    report = sync_user_dataset(
        source_user_id=args.source_user_id,
        target_user_id=args.target_user_id,
        target_email=args.target_email,
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        timeout=int(args.timeout),
        report_path=report_path,
    )
    print(str(report_path))
    print(json.dumps(report["verified_counts"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
