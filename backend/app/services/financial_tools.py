from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

MODEL_VERSION = "forecast-v1.0.0"

_DATE_KEYS = {"date", "transaction_date", "posted_date", "ngay", "ngay_giao_dich"}
_AMOUNT_KEYS = {"amount", "so_tien", "value"}
_DEBIT_KEYS = {"debit", "withdrawal", "chi", "outflow"}
_CREDIT_KEYS = {"credit", "deposit", "thu", "inflow"}
_COUNTERPARTY_KEYS = {"counterparty", "merchant", "description", "memo", "narrative", "noi_dung"}
_DIRECTION_KEYS = {"direction", "type", "dr_cr"}


def _new_trace_id(trace_id: str | None = None) -> str:
    return trace_id or f"trc_{uuid.uuid4().hex[:8]}"


def _hash_payload(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


def _normalize_counterparty(name: str) -> str:
    normalized = "".join(ch if ch.isalnum() else " " for ch in (name or "").upper())
    return " ".join(normalized.split())


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(",", "").replace(" ", "")
    if text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return default


def _try_parse_date(text: Any) -> date | None:
    if isinstance(text, date):
        return text
    value = str(text or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _add_months(base: date, months: int) -> date:
    year = base.year + (base.month - 1 + months) // 12
    month = (base.month - 1 + months) % 12 + 1
    day = min(base.day, 28)
    return date(year, month, day)


def _tool_response(tool_name: str, tool_input: Dict[str, Any], output: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
    output_hash = _hash_payload(output)
    result = dict(output)
    result["trace_id"] = trace_id
    result["audit"] = {
        "tool_name": tool_name,
        "trace_id": trace_id,
        "model_version": MODEL_VERSION,
        "input_hash": _hash_payload(tool_input),
        "output_hash": output_hash,
    }
    return result


def _choose_header(headers: Iterable[str], candidates: set[str]) -> str | None:
    normalized_headers = {_normalize_key(h): h for h in headers}
    for candidate in candidates:
        if candidate in normalized_headers:
            return normalized_headers[candidate]
    return None


def ingest_statement_vn(
    *,
    file_ref: str,
    bank_hint: str | None = None,
    currency: str = "VND",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    tool_input = {
        "file_ref": file_ref,
        "bank_hint": bank_hint,
        "currency": currency,
    }
    warnings: list[str] = []
    transactions: list[Dict[str, Any]] = []
    path = Path(file_ref)
    if not path.exists() or not path.is_file():
        warnings.append("file_not_found")
        return _tool_response(
            "ingest_statement_vn",
            tool_input,
            {
                "transactions": transactions,
                "quality_score": 0.0,
                "parse_warnings": warnings,
            },
            trace_id,
        )

    extension = path.suffix.lower()
    if extension in {".pdf", ".xls", ".xlsx"}:
        warnings.append("file_format_not_supported_in_mvp_parser")
        return _tool_response(
            "ingest_statement_vn",
            tool_input,
            {
                "transactions": transactions,
                "quality_score": 0.0,
                "parse_warnings": warnings,
            },
            trace_id,
        )

    if extension not in {".csv", ".txt", ".tsv"}:
        warnings.append("unknown_file_extension")
        return _tool_response(
            "ingest_statement_vn",
            tool_input,
            {
                "transactions": transactions,
                "quality_score": 0.0,
                "parse_warnings": warnings,
            },
            trace_id,
        )

    delimiter = "\t" if extension == ".tsv" else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        headers = reader.fieldnames or []
        date_col = _choose_header(headers, _DATE_KEYS)
        amount_col = _choose_header(headers, _AMOUNT_KEYS)
        debit_col = _choose_header(headers, _DEBIT_KEYS)
        credit_col = _choose_header(headers, _CREDIT_KEYS)
        counterparty_col = _choose_header(headers, _COUNTERPARTY_KEYS)
        direction_col = _choose_header(headers, _DIRECTION_KEYS)

        if not date_col:
            warnings.append("missing_date_column")
        if not amount_col and not (debit_col or credit_col):
            warnings.append("missing_amount_column")
        if not counterparty_col:
            warnings.append("missing_counterparty_column")

        parsed_rows = 0
        total_rows = 0
        for raw in reader:
            total_rows += 1
            tx_date = _try_parse_date(raw.get(date_col, "") if date_col else "")
            if not tx_date:
                warnings.append(f"row_{total_rows}_invalid_date")
                continue

            amount = _safe_float(raw.get(amount_col, "")) if amount_col else 0.0
            if not amount:
                debit_amount = _safe_float(raw.get(debit_col, "")) if debit_col else 0.0
                credit_amount = _safe_float(raw.get(credit_col, "")) if credit_col else 0.0
                if debit_amount:
                    amount = -abs(debit_amount)
                elif credit_amount:
                    amount = abs(credit_amount)

            if not amount:
                warnings.append(f"row_{total_rows}_invalid_amount")
                continue

            direction = ""
            if direction_col:
                direction_text = str(raw.get(direction_col, "")).strip().lower()
                if direction_text in {"debit", "dr", "out", "expense"}:
                    direction = "debit"
                elif direction_text in {"credit", "cr", "in", "income"}:
                    direction = "credit"
            if not direction:
                direction = "credit" if amount >= 0 else "debit"

            counterparty = str(raw.get(counterparty_col, "")).strip() if counterparty_col else ""
            if not counterparty:
                warnings.append(f"row_{total_rows}_missing_counterparty")
                counterparty = "UNKNOWN"

            transactions.append(
                {
                    "date": tx_date.isoformat(),
                    "amount": abs(amount),
                    "signed_amount": amount,
                    "currency": currency,
                    "direction": direction,
                    "counterparty": counterparty,
                    "raw": raw,
                    "bank_hint": bank_hint or "unknown",
                }
            )
            parsed_rows += 1

    dedup_warnings = sorted(set(warnings))
    quality = 0.0
    if transactions:
        quality = max(0.0, min(1.0, len(transactions) / (len(transactions) + len(dedup_warnings))))
    output = {
        "transactions": transactions,
        "quality_score": round(quality, 4),
        "parse_warnings": dedup_warnings,
    }
    return _tool_response("ingest_statement_vn", tool_input, output, trace_id)


def _heuristic_category(counterparty_norm: str, direction: str) -> Tuple[str, str, float]:
    if direction == "credit":
        return "jar_income", "cat_income", 0.9
    text = counterparty_norm
    if any(term in text for term in {"RENT", "LANDLORD", "MORTGAGE"}):
        return "jar_house", "cat_housing", 0.88
    if any(term in text for term in {"ELECTRIC", "WATER", "INTERNET", "UTILITY"}):
        return "jar_bills", "cat_utility", 0.86
    if any(term in text for term in {"GRAB", "GOJEK", "UBER", "TAXI", "TRANSPORT"}):
        return "jar_living", "cat_transport", 0.8
    if any(term in text for term in {"COFFEE", "HIGHLANDS", "STARBUCKS", "CAFE"}):
        return "jar_fun", "cat_food_out", 0.72
    return "jar_misc", "cat_other", 0.58


def normalize_and_categorize_txn(
    *,
    transactions: List[Dict[str, Any]],
    rules_counterparty_map: List[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    rules = rules_counterparty_map or []
    rule_map = {
        _normalize_counterparty(rule.get("counterparty_norm", "")): rule
        for rule in rules
        if rule.get("counterparty_norm")
    }
    normalized: list[Dict[str, Any]] = []
    needs_review: list[Dict[str, Any]] = []
    confidence_total = 0.0

    for tx in transactions:
        cp = str(tx.get("counterparty", "")).strip()
        cp_norm = _normalize_counterparty(cp)
        direction = str(tx.get("direction", "")).lower()
        signed_amount = _safe_float(tx.get("signed_amount"))
        amount = _safe_float(tx.get("amount"))
        if not direction:
            direction = "credit" if signed_amount >= 0 else "debit"
        if not amount:
            amount = abs(signed_amount)

        matched_rule = rule_map.get(cp_norm)
        if matched_rule:
            jar_id = str(matched_rule.get("jar_id", "jar_misc"))
            category_id = str(matched_rule.get("category_id", "cat_other"))
            confidence = 0.97
        else:
            jar_id, category_id, confidence = _heuristic_category(cp_norm, direction)

        record = {
            "date": tx.get("date"),
            "amount": amount,
            "currency": tx.get("currency", "VND"),
            "direction": direction,
            "counterparty": cp or "UNKNOWN",
            "counterparty_norm": cp_norm or "UNKNOWN",
            "jar_id": jar_id,
            "category_id": category_id,
            "confidence": round(confidence, 4),
        }
        normalized.append(record)
        confidence_total += confidence
        if record["counterparty_norm"] == "UNKNOWN" or confidence < 0.65:
            needs_review.append(record)

    avg_confidence = 0.0
    if normalized:
        avg_confidence = confidence_total / len(normalized)

    output = {
        "normalized_txn": normalized,
        "confidence": round(avg_confidence, 4),
        "needs_review": needs_review,
    }
    tool_input = {
        "transactions_count": len(transactions),
        "rules_count": len(rules),
    }
    return _tool_response("normalize_and_categorize_txn", tool_input, output, trace_id)


def detect_recurring_cashflow(
    *,
    normalized_txn: List[Dict[str, Any]],
    lookback_months: int = 6,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    grouped: dict[Tuple[str, str], list[Dict[str, Any]]] = defaultdict(list)
    for tx in normalized_txn:
        cp = _normalize_counterparty(str(tx.get("counterparty_norm") or tx.get("counterparty", "")))
        direction = str(tx.get("direction", "debit")).lower()
        grouped[(cp, direction)].append(tx)

    recurring_income: list[Dict[str, Any]] = []
    recurring_expense: list[Dict[str, Any]] = []
    total_expense = 0.0
    recurring_expense_total = 0.0

    for tx in normalized_txn:
        if str(tx.get("direction", "")).lower() == "debit":
            total_expense += _safe_float(tx.get("amount"))

    for (counterparty, direction), txs in grouped.items():
        if len(txs) < 3:
            continue
        month_buckets = {str(tx.get("date", ""))[:7] for tx in txs if tx.get("date")}
        if len(month_buckets) < min(3, lookback_months):
            continue
        avg_amount = statistics.fmean([_safe_float(tx.get("amount")) for tx in txs])
        score = min(0.99, len(month_buckets) / max(lookback_months, 1))
        item = {
            "counterparty_norm": counterparty,
            "average_amount": round(avg_amount, 2),
            "occurrence_months": len(month_buckets),
            "recurring_score": round(score, 4),
        }
        if direction == "credit":
            recurring_income.append(item)
        else:
            recurring_expense.append(item)
            recurring_expense_total += avg_amount

    fixed_cost_ratio = 0.0
    if total_expense > 0:
        fixed_cost_ratio = min(1.0, recurring_expense_total / total_expense)

    output = {
        "recurring_income": recurring_income,
        "recurring_expense": recurring_expense,
        "fixed_cost_ratio": round(fixed_cost_ratio, 4),
    }
    tool_input = {
        "normalized_txn_count": len(normalized_txn),
        "lookback_months": lookback_months,
    }
    return _tool_response("detect_recurring_cashflow", tool_input, output, trace_id)


def build_txn_agg_daily(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    daily: dict[str, Dict[str, float]] = defaultdict(lambda: {"total_spend": 0.0, "total_income": 0.0})
    for tx in transactions:
        tx_date = _try_parse_date(tx.get("date") or tx.get("day") or tx.get("occurred_at"))
        if not tx_date:
            continue
        day_key = tx_date.isoformat()
        amount = _safe_float(tx.get("amount"))
        direction = str(tx.get("direction", "debit")).lower()
        if direction == "credit":
            daily[day_key]["total_income"] += amount
        else:
            daily[day_key]["total_spend"] += amount

    rows = [{"day": day, **values} for day, values in daily.items()]
    rows.sort(key=lambda item: item["day"])
    return rows


def _monthly_from_daily(txn_agg_daily: List[Dict[str, Any]]) -> list[Dict[str, Any]]:
    monthly: dict[str, Dict[str, float]] = defaultdict(lambda: {"income": 0.0, "spend": 0.0})
    for point in txn_agg_daily:
        tx_date = _try_parse_date(point.get("day") or point.get("date"))
        if not tx_date:
            continue
        key = f"{tx_date.year:04d}-{tx_date.month:02d}"
        monthly[key]["income"] += _safe_float(point.get("total_income") or point.get("income_total"))
        monthly[key]["spend"] += _safe_float(point.get("total_spend") or point.get("spend_total"))
    rows = [{"month": month, **values} for month, values in monthly.items()]
    rows.sort(key=lambda item: item["month"])
    return rows


def forecast_cashflow_core(
    *,
    txn_agg_daily: List[Dict[str, Any]],
    seasonality: bool = True,
    scenario_overrides: Dict[str, Any] | None = None,
    horizon_months: int = 12,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    horizon = max(1, min(24, int(horizon_months or 1)))
    overrides = scenario_overrides or {}
    monthly_history = _monthly_from_daily(txn_agg_daily)
    low_history = len(txn_agg_daily) < 30 or len(monthly_history) < 2

    if monthly_history:
        recent = monthly_history[-3:]
        avg_income = statistics.fmean([m["income"] for m in recent])
        avg_spend = statistics.fmean([m["spend"] for m in recent])
        net_history = [m["income"] - m["spend"] for m in monthly_history]
        if len(net_history) >= 2:
            volatility = statistics.pstdev(net_history)
        else:
            volatility = abs(net_history[0]) * 0.2 if net_history else 1_000_000
    else:
        avg_income = 28_000_000.0
        avg_spend = 20_000_000.0
        volatility = 2_000_000.0

    income_delta_pct = _safe_float(overrides.get("income_delta_pct"), 0.0)
    spend_delta_pct = _safe_float(overrides.get("spend_delta_pct"), 0.0)
    income_delta_abs = _safe_float(overrides.get("income_delta_abs"), 0.0)
    spend_delta_abs = _safe_float(overrides.get("spend_delta_abs"), 0.0)

    seasonal_factors: dict[int, float] = defaultdict(lambda: 1.0)
    if seasonality and monthly_history:
        avg_monthly_income = statistics.fmean([m["income"] for m in monthly_history]) or 1.0
        monthly_by_num: dict[int, list[float]] = defaultdict(list)
        for month in monthly_history:
            month_num = int(month["month"].split("-")[1])
            monthly_by_num[month_num].append(month["income"])
        for month_num, values in monthly_by_num.items():
            seasonal_factors[month_num] = max(0.8, min(1.2, statistics.fmean(values) / avg_monthly_income))

    start_date = date.today().replace(day=1)
    points: list[Dict[str, Any]] = []
    p50_values: list[float] = []
    p10_values: list[float] = []
    p90_values: list[float] = []
    for idx in range(horizon):
        month_date = _add_months(start_date, idx)
        month_factor = seasonal_factors[month_date.month] if seasonality else 1.0
        income_est = max(0.0, avg_income * month_factor * (1 + income_delta_pct) + income_delta_abs)
        spend_est = max(0.0, avg_spend * month_factor * (1 + spend_delta_pct) + spend_delta_abs)
        p50 = income_est - spend_est
        width = max(500_000.0, abs(p50) * 0.12, volatility * 0.4)
        p10 = p50 - width
        p90 = p50 + width
        point = {
            "month": month_date.strftime("%Y-%m"),
            "income_estimate": round(income_est, 2),
            "spend_estimate": round(spend_est, 2),
            "p10": round(p10, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
        }
        points.append(point)
        p10_values.append(p10)
        p50_values.append(p50)
        p90_values.append(p90)

    assumptions = [
        "Baseline uses rolling monthly average and optional seasonality factors.",
        "Confidence band is heuristic volatility-based for MVP.",
    ]
    if low_history:
        assumptions.append("low_history: fallback heuristics due to limited history.")

    confidence_band = {
        "p10_avg": round(statistics.fmean(p10_values), 2) if p10_values else 0.0,
        "p50_avg": round(statistics.fmean(p50_values), 2) if p50_values else 0.0,
        "p90_avg": round(statistics.fmean(p90_values), 2) if p90_values else 0.0,
    }
    output = {
        "monthly_forecast": points,
        "forecast_points": points,
        "confidence_band": confidence_band,
        "assumptions": assumptions,
        "model_meta": {
            "model_version": MODEL_VERSION,
            "horizon_months": horizon,
            "history_days": len(txn_agg_daily),
            "low_history": low_history,
        },
    }
    tool_input = {
        "txn_agg_daily_count": len(txn_agg_daily),
        "seasonality": seasonality,
        "scenario_overrides": overrides,
        "horizon_months": horizon,
    }
    return _tool_response("forecast_cashflow_core", tool_input, output, trace_id)


def compute_runway_and_stress(
    *,
    forecast: Dict[str, Any],
    cash_buffer: float,
    stress_config: Dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    config = {
        "income_drop_pct": 0.2,
        "spend_spike_pct": 0.15,
        "duration_months": 3,
        "runway_threshold_months": 6,
    }
    config.update(stress_config or {})
    points = forecast.get("monthly_forecast") or forecast.get("forecast_points") or []
    cash = _safe_float(cash_buffer)
    runway_months = 0
    for point in points:
        cash += _safe_float(point.get("p50"))
        runway_months += 1
        if cash < 0:
            break

    stress_cash = _safe_float(cash_buffer)
    stress_rows: list[Dict[str, Any]] = []
    for idx, point in enumerate(points):
        income = _safe_float(point.get("income_estimate"))
        spend = _safe_float(point.get("spend_estimate"))
        if idx < int(config["duration_months"]):
            income = income * (1 - _safe_float(config["income_drop_pct"]))
            spend = spend * (1 + _safe_float(config["spend_spike_pct"]))
        net = income - spend
        stress_cash += net
        stress_rows.append(
            {
                "month": point.get("month"),
                "stressed_net": round(net, 2),
                "stressed_cash_balance": round(stress_cash, 2),
            }
        )

    risk_flags: list[str] = []
    if runway_months < int(config["runway_threshold_months"]):
        risk_flags.append("runway_below_threshold")
    if any(row["stressed_cash_balance"] < 0 for row in stress_rows):
        risk_flags.append("stress_scenario_negative_cash")

    output = {
        "runway_months": runway_months,
        "stress_result": stress_rows,
        "risk_flags": risk_flags,
    }
    tool_input = {
        "forecast_points": len(points),
        "cash_buffer": cash_buffer,
        "stress_config": config,
    }
    return _tool_response("compute_runway_and_stress", tool_input, output, trace_id)


def evaluate_savings_goal(
    *,
    target_amount: float,
    horizon_months: int,
    forecast: Dict[str, Any],
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    horizon = max(1, int(horizon_months))
    points = (forecast.get("monthly_forecast") or forecast.get("forecast_points") or [])[:horizon]
    if not points:
        points = [{"p50": 0.0} for _ in range(horizon)]

    required = _safe_float(target_amount) / horizon
    projected = sum(max(0.0, _safe_float(point.get("p50"))) for point in points)
    avg_capacity = sum(_safe_float(point.get("p50")) for point in points) / horizon
    feasible = avg_capacity >= required and projected >= _safe_float(target_amount)
    gap = max(0.0, _safe_float(target_amount) - projected)
    grade = "A" if feasible else ("B" if gap <= _safe_float(target_amount) * 0.2 else "C")

    reasons = [
        f"Required monthly saving: {required:.0f} VND.",
        f"Projected cumulative positive cashflow: {projected:.0f} VND.",
    ]
    if not feasible:
        reasons.append("Current cashflow trajectory is below target; adjust spend or horizon.")

    output = {
        "required_monthly_saving": round(required, 2),
        "feasible": feasible,
        "gap_amount": round(gap, 2),
        "metrics": {
            "required_monthly_saving": round(required, 2),
            "projected_positive_cashflow": round(projected, 2),
            "average_monthly_capacity": round(avg_capacity, 2),
            "gap_amount": round(gap, 2),
        },
        "grade": grade,
        "reasons": reasons,
        "guardrails": [],
    }
    tool_input = {
        "target_amount": target_amount,
        "horizon_months": horizon,
        "forecast_points": len(points),
    }
    return _tool_response("evaluate_savings_goal", tool_input, output, trace_id)


def evaluate_house_affordability(
    *,
    house_price: float,
    down_payment: float,
    interest_rate: float,
    loan_years: int,
    fees: float | Dict[str, Any] = 0.0,
    monthly_income: float = 0.0,
    existing_debt_payment: float = 0.0,
    cash_buffer: float = 0.0,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    fees_total = _safe_float(fees) if not isinstance(fees, dict) else sum(_safe_float(v) for v in fees.values())
    annual_rate = _safe_float(interest_rate)
    if annual_rate > 1:
        annual_rate = annual_rate / 100
    months = max(1, int(loan_years) * 12)
    loan_amount = max(0.0, _safe_float(house_price) - _safe_float(down_payment))
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        monthly_payment = loan_amount / months
    else:
        factor = math.pow(1 + monthly_rate, months)
        monthly_payment = loan_amount * monthly_rate * factor / (factor - 1)

    income = max(0.0, _safe_float(monthly_income))
    dti = 1.0 if income <= 0 else (_safe_float(existing_debt_payment) + monthly_payment) / income
    target_dti = 0.4
    max_payment = max(0.0, income * target_dti - _safe_float(existing_debt_payment))
    if monthly_rate == 0:
        max_loan = max_payment * months
    else:
        factor = math.pow(1 + monthly_rate, months)
        max_loan = max_payment * (factor - 1) / (monthly_rate * factor)
    safe_price = max_loan + _safe_float(down_payment) - fees_total
    safe_range = [round(max(0.0, safe_price * 0.9), 2), round(max(0.0, safe_price * 1.05), 2)]

    if dti <= 0.35 and cash_buffer >= 6 * income:
        grade = "A"
    elif dti <= 0.45:
        grade = "B"
    else:
        grade = "C"

    output = {
        "monthly_payment": round(monthly_payment, 2),
        "DTI": round(dti, 4),
        "safe_price_range": safe_range,
        "decision_grade": grade,
        "metrics": {
            "monthly_payment": round(monthly_payment, 2),
            "DTI": round(dti, 4),
            "loan_amount": round(loan_amount, 2),
            "upfront_fees": round(fees_total, 2),
            "safe_price_range": safe_range,
        },
        "grade": grade,
        "reasons": [
            f"Estimated monthly mortgage payment: {monthly_payment:.0f} VND.",
            f"Debt-to-income ratio: {dti:.2%}.",
        ],
        "guardrails": [
            "Assumptions depend on user-entered house price, interest rate, and fees.",
            "Maintain emergency reserve before final commitment.",
        ],
    }
    tool_input = {
        "house_price": house_price,
        "down_payment": down_payment,
        "interest_rate": interest_rate,
        "loan_years": loan_years,
        "fees": fees,
        "monthly_income": monthly_income,
        "existing_debt_payment": existing_debt_payment,
    }
    return _tool_response("evaluate_house_affordability", tool_input, output, trace_id)


def evaluate_investment_capacity(
    *,
    risk_profile: str,
    emergency_target: float,
    forecast: Dict[str, Any],
    cash_buffer: float = 0.0,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    profile = (risk_profile or "balanced").strip().lower()
    points = forecast.get("monthly_forecast") or forecast.get("forecast_points") or []
    avg_net = statistics.fmean([_safe_float(point.get("p50")) for point in points]) if points else 0.0
    risk_budget = {"conservative": 0.2, "balanced": 0.35, "aggressive": 0.5}.get(profile, 0.35)
    max_loss_budget = {"conservative": 0.08, "balanced": 0.15, "aggressive": 0.25}.get(profile, 0.15)

    emergency_gap = max(0.0, _safe_float(emergency_target) - _safe_float(cash_buffer))
    raw_capacity = max(0.0, avg_net) * risk_budget
    if emergency_gap > 0:
        low = 0.0
        high = raw_capacity * 0.5
    else:
        low = raw_capacity * 0.8
        high = raw_capacity * 1.2 + max(0.0, (_safe_float(cash_buffer) - _safe_float(emergency_target)) * 0.02)

    max_loss = max(0.0, high * max_loss_budget)
    grade = "A" if emergency_gap <= 0 and avg_net > 0 else ("B" if avg_net > 0 else "C")
    guardrails = [
        "education_only=true",
        "No buy/sell timing or ticker recommendation is provided.",
        "Review suitability with regulated advisor before execution.",
    ]
    output = {
        "investable_amount_range": {"low": round(low, 2), "high": round(high, 2)},
        "max_loss_tolerance": round(max_loss, 2),
        "guardrail_notes": guardrails,
        "education_only": True,
        "metrics": {
            "avg_monthly_net_cashflow": round(avg_net, 2),
            "emergency_gap": round(emergency_gap, 2),
            "investable_low": round(low, 2),
            "investable_high": round(high, 2),
            "max_loss_tolerance": round(max_loss, 2),
        },
        "grade": grade,
        "reasons": [
            f"Risk profile used: {profile}.",
            f"Average monthly net cashflow: {avg_net:.0f} VND.",
        ],
        "guardrails": guardrails,
    }
    tool_input = {
        "risk_profile": profile,
        "emergency_target": emergency_target,
        "cash_buffer": cash_buffer,
        "forecast_points": len(points),
    }
    return _tool_response("evaluate_investment_capacity", tool_input, output, trace_id)


def simulate_what_if(
    *,
    base_scenario: Dict[str, Any],
    variants: List[Dict[str, Any]],
    goal: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    trace_id = _new_trace_id(trace_id)
    base_overrides = base_scenario.get("scenario_overrides", {})
    txn_agg_daily = base_scenario.get("txn_agg_daily", [])
    seasonality = bool(base_scenario.get("seasonality", True))
    horizon = int(base_scenario.get("horizon_months", 12))
    base_forecast = forecast_cashflow_core(
        txn_agg_daily=txn_agg_daily,
        seasonality=seasonality,
        scenario_overrides=base_overrides,
        horizon_months=horizon,
        trace_id=trace_id,
    )
    base_total = sum(_safe_float(point.get("p50")) for point in base_forecast.get("monthly_forecast", []))
    comparison: list[Dict[str, Any]] = []
    best_name = "base"
    best_score = base_total
    for variant in variants:
        name = str(variant.get("name", f"variant_{len(comparison)+1}"))
        merged_overrides = dict(base_overrides)
        merged_overrides.update(variant.get("scenario_overrides", {}))
        variant_forecast = forecast_cashflow_core(
            txn_agg_daily=txn_agg_daily,
            seasonality=seasonality,
            scenario_overrides=merged_overrides,
            horizon_months=horizon,
            trace_id=trace_id,
        )
        total_net = sum(_safe_float(point.get("p50")) for point in variant_forecast.get("monthly_forecast", []))
        row = {
            "name": name,
            "total_net_p50": round(total_net, 2),
            "delta_vs_base": round(total_net - base_total, 2),
        }
        comparison.append(row)
        score = total_net
        if "house" in (goal or "").lower():
            score = total_net
        if score > best_score:
            best_score = score
            best_name = name

    output = {
        "scenario_comparison": comparison,
        "best_variant_by_goal": best_name,
    }
    tool_input = {
        "base_scenario": base_scenario,
        "variants_count": len(variants),
        "goal": goal,
    }
    return _tool_response("simulate_what_if", tool_input, output, trace_id)
