from __future__ import annotations

import os

SCHEMA_VERSION = "v1"
AGENT_ID = "service"
TOOL_NAME = "run_service_agent_v1"
AGENT_VERSION = str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0")

CLASS_READY = "ready"
CLASS_PARTIAL = "partial_but_usable"
CLASS_INSUFFICIENT_GOAL = "insufficient_goal_data"
CLASS_INSUFFICIENT_STATE = "insufficient_financial_state"
CLASS_REJECTED_FALLBACK = "candidate_rejected_fallback"

PHASE_STABILIZE = "stabilize"
PHASE_PROTECT = "protect_liquidity"
PHASE_ACCUMULATE = "accumulate"
PHASE_REVIEW = "readiness_review"
PHASE_MATURITY = "maturity_transition"

PHASE_TYPES = [
    PHASE_STABILIZE,
    PHASE_PROTECT,
    PHASE_ACCUMULATE,
    PHASE_REVIEW,
    PHASE_MATURITY,
]

JOURNEY_PATTERNS = {
    "stabilize_then_accumulate": [PHASE_STABILIZE, PHASE_ACCUMULATE, PHASE_REVIEW],
    "protect_then_accumulate": [PHASE_PROTECT, PHASE_ACCUMULATE, PHASE_REVIEW],
    "stabilize_then_protect_then_accumulate": [PHASE_STABILIZE, PHASE_PROTECT, PHASE_ACCUMULATE, PHASE_REVIEW],
    "stabilize_then_accumulate_then_review": [PHASE_STABILIZE, PHASE_ACCUMULATE, PHASE_REVIEW],
    "protect_then_stabilize_then_accumulate_then_review": [PHASE_PROTECT, PHASE_STABILIZE, PHASE_ACCUMULATE, PHASE_REVIEW],
}

SERVICE_IDS = [
    "anomaly_review",
    "budget_controls",
    "recurring_expense_cleanup",
    "liquidity_guardrails",
    "emergency_buffer_setup",
    "auto_save_activation",
    "goal_bucket_setup",
    "contribution_review",
    "readiness_check",
    "maturity_options_review",
]

RATIONALE_TAGS = [
    "runway_short",
    "liquidity_pressure_high",
    "cashflow_negative",
    "goal_urgent",
    "goal_feasible",
    "goal_stretch",
    "anomaly_active",
    "readiness_low",
]

SERVICE_PHASE_ALLOWLIST = {
    "anomaly_review": [PHASE_PROTECT],
    "budget_controls": [PHASE_STABILIZE],
    "recurring_expense_cleanup": [PHASE_STABILIZE],
    "liquidity_guardrails": [PHASE_PROTECT, PHASE_STABILIZE],
    "emergency_buffer_setup": [PHASE_PROTECT, PHASE_STABILIZE],
    "auto_save_activation": [PHASE_ACCUMULATE],
    "goal_bucket_setup": [PHASE_ACCUMULATE],
    "contribution_review": [PHASE_ACCUMULATE, PHASE_REVIEW],
    "readiness_check": [PHASE_REVIEW],
    "maturity_options_review": [PHASE_MATURITY],
}

PHASE_TITLES = {
    PHASE_STABILIZE: "Stabilize monthly cashflow",
    PHASE_PROTECT: "Protect liquidity first",
    PHASE_ACCUMULATE: "Build steady goal contributions",
    PHASE_REVIEW: "Review readiness before the final push",
    PHASE_MATURITY: "Handle goal maturity and next options",
}

GOAL_TYPE_KEYWORDS = {
    "vehicle_purchase": ["car", "vehicle", "motorbike", "motorcycle", "bike", "xe", "oto", "auto"],
    "emergency_fund": ["emergency", "buffer", "rainy day", "quy khan cap"],
    "home_purchase": ["house", "home", "apartment", "deposit", "down payment", "nha"],
    "travel": ["travel", "trip", "vacation", "du lich"],
    "education": ["education", "course", "tuition", "study", "hoc"],
    "wedding": ["wedding", "marry", "dam cuoi"],
    "general_savings": ["save", "saving", "goal", "fund"],
}

MODEL_ID_FALLBACK = "us.anthropic.claude-sonnet-4-6"
MODEL_REGION_FALLBACK = "us-east-1"

SCORE_WEIGHTS = {
    "feasibility": 0.24,
    "liquidity_safety": 0.22,
    "goal_alignment": 0.16,
    "planner_alignment": 0.17,
    "service_coherence": 0.12,
    "stock_context_alignment": 0.08,
    "journey_richness": 0.09,
    "complexity_penalty": 0.05,
    "partial_penalty": 0.10,
    "model_bonus_max": 0.05,
}

SCORE_TIE_TOLERANCE = 0.01
