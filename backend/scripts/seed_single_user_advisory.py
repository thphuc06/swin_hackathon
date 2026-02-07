from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import os
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable

import requests
from dotenv import load_dotenv

UTC = timezone.utc
SEED_NAMESPACE = uuid.UUID("11d85697-44c4-4f56-9ea1-f8e2d8f9371d")
DEFAULT_TIMEOUT = 45

DEFAULT_JARS = ["Bills", "Living", "Goals", "Emergency", "Misc"]
SALARY_CATEGORY_NAME = "Salary Income"
FALLBACK_CATEGORY_NAME = "Other"
SALARY_COUNTERPARTY = "Payroll Employer"


@dataclass(frozen=True)
class SparkovRow:
    trans_num: str
    occurred_at: datetime
    amount_usd: Decimal
    merchant: str
    category: str
    city: str
    state: str


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _normalize_key(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower())


def _clean_text(value: str, fallback: str = "UNKNOWN") -> str:
    text = " ".join(str(value or "").strip().split())
    return text if text else fallback


def _stable_uuid(*parts: str) -> str:
    key = "|".join(parts)
    return str(uuid.uuid5(SEED_NAMESPACE, key))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_value(row: Dict[str, str], *keys: str) -> str:
    normalized = {_normalize_key(k): v for k, v in row.items()}
    for key in keys:
        value = normalized.get(_normalize_key(key))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value!r}")


def _parse_decimal(value: str) -> Decimal:
    cleaned = value.replace(",", "").strip()
    if not cleaned:
        raise ValueError("empty decimal")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc


def _is_nonfraud(value: str) -> bool:
    try:
        return int(float(value.strip())) == 0
    except ValueError:
        return False


def _rank(seed: int, trans_num: str, source_name: str) -> int:
    text = f"{seed}:{source_name}:{trans_num}"
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _add_months(dt: datetime, months: int) -> datetime:
    month_index = (dt.month - 1) + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def _month_window(months: int, now_utc: datetime) -> tuple[datetime, datetime, list[datetime]]:
    if months < 1:
        raise ValueError("months must be >= 1")
    current_month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month_start = _add_months(current_month_start, -1)
    start_month_start = _add_months(end_month_start, -(months - 1))
    next_month_start = _add_months(end_month_start, 1)
    window_end = next_month_start - timedelta(seconds=1)
    month_starts = [_add_months(start_month_start, idx) for idx in range(months)]
    return start_month_start, window_end, month_starts


def _vnd_round(amount: Decimal) -> int:
    rounded = (amount / Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("1000")
    return int(rounded)


def _load_category_mapping(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    category_map = data.get("category_to_bucket")
    fallback = data.get("fallback")
    if not isinstance(category_map, dict) or not isinstance(fallback, dict):
        raise ValueError("Invalid mapping file. Expected keys: category_to_bucket, fallback")
    normalized_map: dict[str, dict[str, str]] = {}
    for key, entry in category_map.items():
        if not isinstance(entry, dict):
            continue
        jar = _clean_text(str(entry.get("jar", "Misc")), "Misc")
        category = _clean_text(str(entry.get("category", FALLBACK_CATEGORY_NAME)), FALLBACK_CATEGORY_NAME)
        channel = _clean_text(str(entry.get("channel", "other")), "other").lower()
        normalized_map[key.strip().lower()] = {"jar": jar, "category": category, "channel": channel}
    fallback_out = {
        "jar": _clean_text(str(fallback.get("jar", "Misc")), "Misc"),
        "category": _clean_text(str(fallback.get("category", FALLBACK_CATEGORY_NAME)), FALLBACK_CATEGORY_NAME),
        "channel": _clean_text(str(fallback.get("channel", "other")), "other").lower(),
    }
    return {"category_to_bucket": normalized_map, "fallback": fallback_out}


def _select_sparkov_rows(paths: Iterable[Path], target_rows: int, seed: int) -> tuple[list[SparkovRow], dict[str, int]]:
    if target_rows < 1:
        raise ValueError("target_rows must be >= 1")
    heap: list[tuple[int, SparkovRow]] = []
    stats = {"total_rows": 0, "nonfraud_rows": 0, "parse_errors": 0}

    for source_path in paths:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                stats["total_rows"] += 1
                if not _is_nonfraud(_row_value(row, "is_fraud")):
                    continue
                stats["nonfraud_rows"] += 1
                try:
                    trans_num = _row_value(row, "trans_num")
                    if not trans_num:
                        raise ValueError("missing trans_num")
                    ts_text = _row_value(row, "trans_date_trans_time")
                    if not ts_text:
                        trans_date = _row_value(row, "trans_date")
                        trans_time = _row_value(row, "trans_time") or "00:00:00"
                        ts_text = f"{trans_date} {trans_time}".strip()
                    occurred_at = _parse_ts(ts_text)
                    amount_usd = _parse_decimal(_row_value(row, "amt"))
                    merchant = _clean_text(_row_value(row, "merchant"), "UNKNOWN MERCHANT")
                    category = _clean_text(_row_value(row, "category"), "other").lower()
                    city = _clean_text(_row_value(row, "city"), "UNKNOWN CITY")
                    state = _clean_text(_row_value(row, "state"), "NA")
                except ValueError:
                    stats["parse_errors"] += 1
                    continue

                sparkov_row = SparkovRow(
                    trans_num=trans_num,
                    occurred_at=occurred_at,
                    amount_usd=amount_usd,
                    merchant=merchant,
                    category=category,
                    city=city,
                    state=state,
                )
                row_rank = _rank(seed=seed, trans_num=trans_num, source_name=source_path.name)
                heap_item = (-row_rank, sparkov_row)
                if len(heap) < target_rows:
                    heapq.heappush(heap, heap_item)
                elif heap_item[0] > heap[0][0]:
                    heapq.heapreplace(heap, heap_item)

    if len(heap) < target_rows:
        raise RuntimeError(
            f"Not enough non-fraud rows. Requested {target_rows}, selected {len(heap)}. "
            "Check input Sparkov files."
        )

    selected = [(-neg_rank, row) for neg_rank, row in heap]
    selected.sort(key=lambda item: (item[0], item[1].trans_num))
    return [item[1] for item in selected], stats


def _reshape_timestamps(rows: list[SparkovRow], start: datetime, end: datetime) -> list[tuple[SparkovRow, datetime]]:
    sorted_rows = sorted(rows, key=lambda row: (row.occurred_at, row.trans_num))
    if not sorted_rows:
        return []
    source_min = sorted_rows[0].occurred_at
    source_max = sorted_rows[-1].occurred_at
    source_span = (source_max - source_min).total_seconds()
    window_span = (end - start).total_seconds()
    out: list[tuple[SparkovRow, datetime]] = []
    denominator = max(1, len(sorted_rows) - 1)
    for idx, row in enumerate(sorted_rows):
        if source_span <= 0:
            ratio = idx / denominator
        else:
            ratio = (row.occurred_at - source_min).total_seconds() / source_span
        mapped = start + timedelta(seconds=window_span * ratio)
        out.append((row, mapped))
    return out


def _build_email(seed_user_id: str) -> str:
    token = hashlib.sha256(seed_user_id.encode("utf-8")).hexdigest()[:10]
    return f"user_{token}@seed.local"


def _build_entities(
    *,
    seed_user_id: str,
    now_utc: datetime,
    category_mapping: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], dict[str, str]]:
    now_iso = _iso(now_utc)
    jars: list[dict[str, Any]] = []
    jar_name_to_id: dict[str, str] = {}
    for jar_name in DEFAULT_JARS:
        jar_id = _stable_uuid("jar", seed_user_id, jar_name.lower())
        jar_name_to_id[jar_name] = jar_id
        jars.append(
            {
                "id": jar_id,
                "user_id": seed_user_id,
                "template_id": None,
                "name": jar_name,
                "description": f"Seeded jar: {jar_name}",
                "keywords": [],
                "target_amount": 0,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
        )

    category_names = {SALARY_CATEGORY_NAME, FALLBACK_CATEGORY_NAME}
    for entry in category_mapping["category_to_bucket"].values():
        category_names.add(entry["category"])
    category_rows: list[dict[str, Any]] = []
    category_name_to_id: dict[str, str] = {}
    for category_name in sorted(category_names):
        category_id = _stable_uuid("category", seed_user_id, category_name.lower())
        category_name_to_id[category_name] = category_id
        category_rows.append(
            {
                "id": category_id,
                "user_id": seed_user_id,
                "parent_id": None,
                "name": category_name,
            }
        )

    return jars, category_rows, jar_name_to_id, category_name_to_id


def _pick_bucket(category_mapping: dict[str, Any], sparkov_category: str) -> dict[str, str]:
    key = sparkov_category.strip().lower()
    return category_mapping["category_to_bucket"].get(key, category_mapping["fallback"])


def _build_raw_narrative(row: SparkovRow) -> str:
    ref = row.trans_num[-8:] if len(row.trans_num) >= 8 else row.trans_num
    return f"POS {row.merchant} {row.category.upper()} {row.city} {row.state} REF:{ref}"


def _build_debit_transactions(
    *,
    remapped_rows: list[tuple[SparkovRow, datetime]],
    seed_user_id: str,
    currency: str,
    fx_rate: Decimal,
    category_mapping: dict[str, Any],
    jar_name_to_id: dict[str, str],
    category_name_to_id: dict[str, str],
    now_utc: datetime,
) -> list[dict[str, Any]]:
    now_iso = _iso(now_utc)
    out: list[dict[str, Any]] = []
    for idx, (row, mapped_ts) in enumerate(remapped_rows):
        bucket = _pick_bucket(category_mapping, row.category)
        jar_id = jar_name_to_id.get(bucket["jar"], jar_name_to_id["Misc"])
        category_id = category_name_to_id.get(bucket["category"], category_name_to_id[FALLBACK_CATEGORY_NAME])
        amount_vnd = _vnd_round(row.amount_usd * fx_rate)
        tx_id = _stable_uuid("txn", seed_user_id, row.trans_num, str(idx))
        out.append(
            {
                "id": tx_id,
                "user_id": seed_user_id,
                "jar_id": jar_id,
                "category_id": category_id,
                "amount": amount_vnd,
                "currency": currency,
                "counterparty": row.merchant,
                "raw_narrative": _build_raw_narrative(row),
                "user_note": None,
                "channel": bucket["channel"],
                "occurred_at": _iso(mapped_ts),
                "created_at": now_iso,
                "direction": "debit",
            }
        )
    return out


def _month_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def _salary_from_debit(debit_rows: list[dict[str, Any]], month_starts: list[datetime]) -> tuple[int, float]:
    monthly_totals: dict[str, float] = {_month_key(month): 0.0 for month in month_starts}
    for row in debit_rows:
        ts = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
        monthly_totals[_month_key(ts)] += float(row["amount"])

    values = list(monthly_totals.values())
    avg_monthly_debit = statistics.fmean(values) if values else 0.0
    min_monthly_debit = min(values) if values else 0.0
    max_monthly_debit = max(values) if values else 0.0

    if avg_monthly_debit <= 0:
        return 20_000_000, 1.0

    if max_monthly_debit > min_monthly_debit:
        midpoint = (min_monthly_debit + max_monthly_debit) / 2
        multiplier = max(0.75, min(1.25, midpoint / avg_monthly_debit))
    else:
        multiplier = 1.0

    salary_amount = _vnd_round(Decimal(avg_monthly_debit * multiplier))
    salary_amount = max(8_000_000, salary_amount)
    return salary_amount, multiplier


def _build_income_and_salary_transactions(
    *,
    seed_user_id: str,
    currency: str,
    month_starts: list[datetime],
    salary_amount: int,
    jar_name_to_id: dict[str, str],
    category_name_to_id: dict[str, str],
    now_utc: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    now_iso = _iso(now_utc)
    source_id = _stable_uuid("income_source", seed_user_id, "monthly_salary")
    source_rows = [
        {
            "id": source_id,
            "user_id": seed_user_id,
            "source_name": "Monthly Salary",
            "monthly_amount": salary_amount,
            "updated_at": now_iso,
        }
    ]

    income_event_rows: list[dict[str, Any]] = []
    salary_tx_rows: list[dict[str, Any]] = []
    jar_id = jar_name_to_id["Bills"]
    category_id = category_name_to_id[SALARY_CATEGORY_NAME]
    for month_start in month_starts:
        event_ts = month_start.replace(day=5, hour=9, minute=0, second=0, microsecond=0)
        month_token = event_ts.strftime("%Y-%m")
        income_event_id = _stable_uuid("income_event", seed_user_id, month_token)
        tx_id = _stable_uuid("salary_tx", seed_user_id, month_token)
        income_event_rows.append(
            {
                "id": income_event_id,
                "user_id": seed_user_id,
                "source_id": source_id,
                "amount": salary_amount,
                "occurred_at": _iso(event_ts),
            }
        )
        salary_tx_rows.append(
            {
                "id": tx_id,
                "user_id": seed_user_id,
                "jar_id": jar_id,
                "category_id": category_id,
                "amount": salary_amount,
                "currency": currency,
                "counterparty": SALARY_COUNTERPARTY,
                "raw_narrative": f"SALARY CREDIT MONTH {month_token}",
                "user_note": None,
                "channel": "transfer",
                "occurred_at": _iso(event_ts),
                "created_at": now_iso,
                "direction": "credit",
            }
        )

    return source_rows, income_event_rows, salary_tx_rows


def _optional_goal_and_budget(
    *,
    seed_user_id: str,
    currency: str,
    now_utc: datetime,
    salary_amount: int,
    average_monthly_debit: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now_iso = _iso(now_utc)
    goal_rows = [
        {
            "id": _stable_uuid("goal", seed_user_id, "home_goal"),
            "user_id": seed_user_id,
            "name": "Home Down Payment",
            "target_amount": salary_amount * 18,
            "horizon_months": 60,
            "created_at": now_iso,
        }
    ]
    budget_limit = _vnd_round(Decimal(max(5_000_000.0, average_monthly_debit * 0.9)))
    budget_rows = [
        {
            "id": _stable_uuid("budget", seed_user_id, "overall_monthly"),
            "user_id": seed_user_id,
            "scope_type": "overall",
            "scope_id": None,
            "period": "monthly",
            "limit_amount": budget_limit,
            "currency": currency,
            "active": True,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    ]
    return goal_rows, budget_rows


class SupabaseRestClient:
    def __init__(self, *, supabase_url: str, service_key: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        base = supabase_url.rstrip("/")
        self.base_url = f"{base}/rest/v1"
        self.timeout = timeout
        self.common_headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        payload: Any = None,
        headers: Dict[str, str] | None = None,
    ) -> Any:
        merged_headers = dict(self.common_headers)
        if headers:
            merged_headers.update(headers)
        response = requests.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=payload,
            headers=merged_headers,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            snippet = response.text[:1200]
            raise RuntimeError(f"Supabase {method} {path} failed ({response.status_code}): {snippet}")
        if response.text and "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return None

    def upsert_rows(self, table: str, rows: list[dict[str, Any]], on_conflict: str, chunk_size: int = 500) -> None:
        if not rows:
            return
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            self._request(
                "POST",
                f"/{table}",
                params={"on_conflict": on_conflict},
                payload=chunk,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )

    def fetch_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Dict[str, str] | None = None,
        order: str | None = None,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: Dict[str, Any] = {"select": select, "limit": page_size, "offset": offset}
            if order:
                params["order"] = order
            for key, value in filters.items():
                params[key] = f"eq.{value}"
            page = self._request("GET", f"/{table}", params=params)
            if not isinstance(page, list):
                raise RuntimeError(f"Unexpected response type while fetching {table}")
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return rows

    def count_rows(self, table: str, filters: Dict[str, str] | None = None) -> int:
        filters = filters or {}
        params: Dict[str, Any] = {"select": "*"}
        for key, value in filters.items():
            params[key] = f"eq.{value}"
        merged_headers = dict(self.common_headers)
        merged_headers["Prefer"] = "count=exact"
        response = requests.request(
            method="HEAD",
            url=f"{self.base_url}/{table}",
            params=params,
            headers=merged_headers,
            timeout=self.timeout,
        )
        if response.status_code < 400:
            content_range = response.headers.get("Content-Range", "")
            if "/" in content_range:
                try:
                    return int(content_range.split("/")[-1])
                except ValueError:
                    pass
        rows = self.fetch_rows(table, select="*", filters=filters, page_size=1000)
        return len(rows)


def _evaluate_checks(
    *,
    transactions: list[dict[str, Any]],
    jar_ids: set[str],
    category_ids: set[str],
    seed_user_id: str,
    months: int,
    expected_debit_rows: int,
    expected_credit_rows: int,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    total_rows = len(transactions)
    debit_rows = [row for row in transactions if row.get("direction") == "debit"]
    credit_rows = [row for row in transactions if row.get("direction") == "credit"]

    def add_check(name: str, passed: bool, detail: Dict[str, Any]) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    add_check(
        "integrity_all_transactions_belong_to_user",
        all(str(row.get("user_id")) == seed_user_id for row in transactions),
        {"transaction_count": total_rows},
    )

    add_check(
        "integrity_jar_and_category_fk_coverage",
        all(str(row.get("jar_id")) in jar_ids and str(row.get("category_id")) in category_ids for row in transactions),
        {"known_jar_count": len(jar_ids), "known_category_count": len(category_ids)},
    )

    add_check(
        "volume_debit_rows_match_target",
        len(debit_rows) == expected_debit_rows,
        {"expected": expected_debit_rows, "actual": len(debit_rows)},
    )
    add_check(
        "volume_credit_rows_match_salary_events",
        len(credit_rows) == expected_credit_rows,
        {"expected": expected_credit_rows, "actual": len(credit_rows)},
    )

    occurred = [
        datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00")).astimezone(UTC)
        for row in transactions
    ]
    min_ts = min(occurred) if occurred else None
    max_ts = max(occurred) if occurred else None
    now_utc = datetime.now(UTC)

    month_keys = {ts.strftime("%Y-%m") for ts in occurred}
    add_check(
        "time_spans_full_month_window",
        len(month_keys) >= months,
        {"months_present": len(month_keys), "required": months},
    )
    add_check(
        "time_no_future_dates",
        max_ts is None or max_ts <= now_utc,
        {"max_occurred_at": _iso(max_ts) if max_ts else None, "now_utc": _iso(now_utc)},
    )

    monthly_net: dict[str, float] = defaultdict(float)
    for row in transactions:
        ts = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00")).astimezone(UTC)
        key = ts.strftime("%Y-%m")
        amount = float(row.get("amount") or 0)
        if row.get("direction") == "credit":
            monthly_net[key] += amount
        else:
            monthly_net[key] -= amount
    add_check(
        "advisory_monthly_cashflow_has_positive_and_tight_months",
        any(val > 0 for val in monthly_net.values()) and any(val <= 0 for val in monthly_net.values()),
        {
            "positive_months": sum(1 for val in monthly_net.values() if val > 0),
            "tight_months": sum(1 for val in monthly_net.values() if val <= 0),
        },
    )

    spend_window_counts: dict[str, int] = {}
    if max_ts:
        for window in (30, 60, 90):
            start = max_ts - timedelta(days=window)
            count = sum(
                1
                for row in debit_rows
                if datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00")).astimezone(UTC) >= start
            )
            spend_window_counts[str(window)] = count
    add_check(
        "advisory_spend_windows_non_empty",
        all(count > 0 for count in spend_window_counts.values()) if spend_window_counts else False,
        {"window_counts": spend_window_counts},
    )

    def non_empty_ratio(field: str) -> float:
        if total_rows == 0:
            return 0.0
        non_empty = sum(1 for row in transactions if str(row.get(field) or "").strip())
        return non_empty / total_rows

    narrative_ratio = non_empty_ratio("raw_narrative")
    counterparty_ratio = non_empty_ratio("counterparty")
    add_check(
        "narrative_non_empty_ratio",
        narrative_ratio >= 0.99,
        {"ratio": round(narrative_ratio, 6), "threshold": 0.99},
    )
    add_check(
        "counterparty_non_empty_ratio",
        counterparty_ratio >= 0.99,
        {"ratio": round(counterparty_ratio, 6), "threshold": 0.99},
    )

    all_pass = all(check["passed"] for check in checks)
    return {
        "summary": {
            "all_pass": all_pass,
            "check_count": len(checks),
            "pass_count": sum(1 for check in checks if check["passed"]),
        },
        "metrics": {
            "total_transactions": total_rows,
            "debit_rows": len(debit_rows),
            "credit_rows": len(credit_rows),
            "min_occurred_at": _iso(min_ts) if min_ts else None,
            "max_occurred_at": _iso(max_ts) if max_ts else None,
            "monthly_net_cashflow": dict(sorted(monthly_net.items())),
        },
        "checks": checks,
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    repo_backend = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Seed one advisory user into Supabase from Sparkov subset.")
    parser.add_argument("--sparkov-train", required=True, help="Path to Sparkov fraudTrain.csv")
    parser.add_argument("--sparkov-test", required=True, help="Path to Sparkov fraudTest.csv")
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL", ""), help="Supabase project URL")
    parser.add_argument(
        "--supabase-service-key",
        default=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        help="Supabase service role key",
    )
    parser.add_argument("--seed-user-id", required=True, help="Single user identifier to seed")
    parser.add_argument("--months", type=int, default=12, help="Completed months to seed (default: 12)")
    parser.add_argument("--target-debit-rows", type=int, default=5000, help="Debit row count target (default: 5000)")
    parser.add_argument("--fx-rate", type=int, default=25000, help="USD->VND conversion rate (default: 25000)")
    parser.add_argument("--currency", default="VND", help="Currency code (default: VND)")
    parser.add_argument("--seed", type=int, default=20260207, help="Deterministic random seed (default: 20260207)")
    parser.add_argument(
        "--category-mapping",
        default=str(repo_backend / "seed" / "sparkov_category_mapping.json"),
        help="Path to Sparkov category mapping JSON",
    )
    parser.add_argument(
        "--output-dir",
        default=str(repo_backend / "tmp"),
        help="Output directory for manifest/validation files",
    )
    parser.add_argument(
        "--include-goal-budget",
        action="store_true",
        help="Seed one goal and one monthly budget for demos",
    )
    return parser.parse_args()


def main() -> int:
    repo_backend = Path(__file__).resolve().parents[1]
    load_dotenv(repo_backend / ".env")
    args = _parse_args()

    sparkov_train = Path(args.sparkov_train).resolve()
    sparkov_test = Path(args.sparkov_test).resolve()
    mapping_path = Path(args.category_mapping).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not sparkov_train.exists() or not sparkov_train.is_file():
        raise FileNotFoundError(f"--sparkov-train not found: {sparkov_train}")
    if not sparkov_test.exists() or not sparkov_test.is_file():
        raise FileNotFoundError(f"--sparkov-test not found: {sparkov_test}")
    if not mapping_path.exists() or not mapping_path.is_file():
        raise FileNotFoundError(f"--category-mapping not found: {mapping_path}")
    if not args.supabase_url:
        raise ValueError("--supabase-url is required (or set SUPABASE_URL)")
    if not args.supabase_service_key:
        raise ValueError("--supabase-service-key is required (or set SUPABASE_SERVICE_ROLE_KEY)")
    if args.months < 1:
        raise ValueError("--months must be >= 1")
    if args.target_debit_rows < 1:
        raise ValueError("--target-debit-rows must be >= 1")
    if args.fx_rate <= 0:
        raise ValueError("--fx-rate must be > 0")

    now_utc = datetime.now(UTC)
    window_start, window_end, month_starts = _month_window(args.months, now_utc)
    fx_rate_decimal = Decimal(args.fx_rate)
    category_mapping = _load_category_mapping(mapping_path)

    selected_rows, extract_stats = _select_sparkov_rows(
        paths=[sparkov_train, sparkov_test],
        target_rows=args.target_debit_rows,
        seed=args.seed,
    )
    remapped_rows = _reshape_timestamps(selected_rows, window_start, window_end)

    jars, categories, jar_name_to_id, category_name_to_id = _build_entities(
        seed_user_id=args.seed_user_id,
        now_utc=now_utc,
        category_mapping=category_mapping,
    )
    debit_transactions = _build_debit_transactions(
        remapped_rows=remapped_rows,
        seed_user_id=args.seed_user_id,
        currency=args.currency,
        fx_rate=fx_rate_decimal,
        category_mapping=category_mapping,
        jar_name_to_id=jar_name_to_id,
        category_name_to_id=category_name_to_id,
        now_utc=now_utc,
    )

    salary_amount, salary_multiplier = _salary_from_debit(debit_transactions, month_starts)
    source_rows, income_event_rows, salary_transactions = _build_income_and_salary_transactions(
        seed_user_id=args.seed_user_id,
        currency=args.currency,
        month_starts=month_starts,
        salary_amount=salary_amount,
        jar_name_to_id=jar_name_to_id,
        category_name_to_id=category_name_to_id,
        now_utc=now_utc,
    )

    all_transactions = debit_transactions + salary_transactions
    monthly_debit_values = defaultdict(float)
    for tx in debit_transactions:
        ts = datetime.fromisoformat(tx["occurred_at"].replace("Z", "+00:00"))
        monthly_debit_values[_month_key(ts)] += float(tx["amount"])
    average_monthly_debit = statistics.fmean(monthly_debit_values.values()) if monthly_debit_values else 0.0

    user_row = {
        "id": args.seed_user_id,
        "email": _build_email(args.seed_user_id),
        "created_at": _iso(now_utc),
    }
    profile_row = {
        "user_id": args.seed_user_id,
        "display_name": "Seeded Advisory User",
        "risk_profile_current": "balanced",
        "locale": "vi-VN",
        "updated_at": _iso(now_utc),
    }

    goal_rows: list[dict[str, Any]] = []
    budget_rows: list[dict[str, Any]] = []
    if args.include_goal_budget:
        goal_rows, budget_rows = _optional_goal_and_budget(
            seed_user_id=args.seed_user_id,
            currency=args.currency,
            now_utc=now_utc,
            salary_amount=salary_amount,
            average_monthly_debit=average_monthly_debit,
        )

    client = SupabaseRestClient(
        supabase_url=args.supabase_url,
        service_key=args.supabase_service_key,
    )

    client.upsert_rows("users", [user_row], on_conflict="id")
    client.upsert_rows("profiles", [profile_row], on_conflict="user_id")
    client.upsert_rows("jars", jars, on_conflict="id")
    client.upsert_rows("categories", categories, on_conflict="id")
    client.upsert_rows("transactions", debit_transactions, on_conflict="id")
    client.upsert_rows("income_sources", source_rows, on_conflict="id")
    client.upsert_rows("income_events", income_event_rows, on_conflict="id")
    client.upsert_rows("transactions", salary_transactions, on_conflict="id")
    if goal_rows:
        client.upsert_rows("goals", goal_rows, on_conflict="id")
    if budget_rows:
        client.upsert_rows("budgets", budget_rows, on_conflict="id")

    db_transactions = client.fetch_rows(
        "transactions",
        select="id,user_id,jar_id,category_id,amount,counterparty,raw_narrative,direction,occurred_at",
        filters={"user_id": args.seed_user_id},
        order="occurred_at.asc",
        page_size=1000,
    )
    db_jars = client.fetch_rows("jars", select="id", filters={"user_id": args.seed_user_id}, page_size=500)
    db_categories = client.fetch_rows("categories", select="id", filters={"user_id": args.seed_user_id}, page_size=500)

    validation = _evaluate_checks(
        transactions=db_transactions,
        jar_ids={str(row["id"]) for row in db_jars},
        category_ids={str(row["id"]) for row in db_categories},
        seed_user_id=args.seed_user_id,
        months=args.months,
        expected_debit_rows=len(debit_transactions),
        expected_credit_rows=len(salary_transactions),
    )
    validation["db_counts"] = {
        "users": client.count_rows("users", filters={"id": args.seed_user_id}),
        "profiles": client.count_rows("profiles", filters={"user_id": args.seed_user_id}),
        "jars": client.count_rows("jars", filters={"user_id": args.seed_user_id}),
        "categories": client.count_rows("categories", filters={"user_id": args.seed_user_id}),
        "transactions": client.count_rows("transactions", filters={"user_id": args.seed_user_id}),
        "income_sources": client.count_rows("income_sources", filters={"user_id": args.seed_user_id}),
        "income_events": client.count_rows("income_events", filters={"user_id": args.seed_user_id}),
    }

    manifest_payload = {
        "seed_version": "seed_single_user_v1",
        "generated_at": _iso(now_utc),
        "seed_namespace": str(SEED_NAMESPACE),
        "seed_user_id": args.seed_user_id,
        "window": {"start": _iso(window_start), "end": _iso(window_end), "months": args.months},
        "parameters": {
            "target_debit_rows": args.target_debit_rows,
            "fx_rate": args.fx_rate,
            "currency": args.currency,
            "seed": args.seed,
            "include_goal_budget": args.include_goal_budget,
        },
        "params_hash": _hash_text(
            _canonical_json(
                {
                    "seed_user_id": args.seed_user_id,
                    "months": args.months,
                    "target_debit_rows": args.target_debit_rows,
                    "fx_rate": args.fx_rate,
                    "currency": args.currency,
                    "seed": args.seed,
                    "include_goal_budget": args.include_goal_budget,
                }
            )
        ),
        "input_hashes": {
            "sparkov_train_sha256": _hash_file(sparkov_train),
            "sparkov_test_sha256": _hash_file(sparkov_test),
            "category_mapping_sha256": _hash_file(mapping_path),
        },
        "selection_stats": extract_stats,
        "salary": {
            "salary_amount": salary_amount,
            "salary_multiplier": round(salary_multiplier, 6),
            "salary_event_count": len(income_event_rows),
        },
        "generated_row_counts": {
            "users": 1,
            "profiles": 1,
            "jars": len(jars),
            "categories": len(categories),
            "debit_transactions": len(debit_transactions),
            "salary_transactions": len(salary_transactions),
            "all_transactions": len(all_transactions),
            "income_sources": len(source_rows),
            "income_events": len(income_event_rows),
            "goals": len(goal_rows),
            "budgets": len(budget_rows),
        },
        "validation_summary": validation["summary"],
    }

    manifest_path = output_dir / "seed_manifest_single_user.json"
    validation_path = output_dir / "seed_validation_single_user.json"
    _write_json(manifest_path, manifest_payload)
    _write_json(validation_path, validation)

    print(f"Seed complete for user: {args.seed_user_id}")
    print(f"Transactions inserted (expected): {len(all_transactions)}")
    print(f"Validation all_pass: {validation['summary']['all_pass']}")
    print(f"Manifest: {manifest_path}")
    print(f"Validation: {validation_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
