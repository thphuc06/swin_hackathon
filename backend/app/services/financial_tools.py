from __future__ import annotations

# Compatibility shim: legacy imports should use app.services.finance moving forward.
from app.services.finance import (
    build_txn_agg_daily,
    compute_runway_and_stress,
    detect_recurring_cashflow,
    evaluate_house_affordability,
    evaluate_investment_capacity,
    evaluate_savings_goal,
    forecast_cashflow_core,
    ingest_statement_vn,
    normalize_and_categorize_txn,
    simulate_what_if,
)

__all__ = [
    "ingest_statement_vn",
    "normalize_and_categorize_txn",
    "detect_recurring_cashflow",
    "build_txn_agg_daily",
    "forecast_cashflow_core",
    "compute_runway_and_stress",
    "evaluate_savings_goal",
    "evaluate_house_affordability",
    "evaluate_investment_capacity",
    "simulate_what_if",
]
