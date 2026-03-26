from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Mapping


ROLE_KEYWORDS: Dict[str, set[str]] = {
    "bills": {"bill", "utility", "rent", "mortgage", "insurance", "repair", "medical", "clinic", "health"},
    "emergency": {"emergency", "reserve", "buffer", "rainy", "safety"},
    "goals": {"goal", "saving", "save", "fund", "deposit", "down payment", "travel", "education", "home"},
    "living": {"living", "daily", "grocery", "groceries", "transport", "food", "kids", "family", "needs"},
    "discretionary": {"misc", "fun", "shopping", "entertainment", "online", "leisure", "play"},
}

CATEGORY_ROLE_HINTS: Dict[str, Dict[str, float]] = {
    "cashback reward": {"discretionary": 0.3},
    "deposit interest": {"emergency": 0.2, "goals": 0.2},
    "entertainment": {"discretionary": 1.0},
    "food & dining": {"living": 0.8, "discretionary": 0.2},
    "freelance income": {"goals": 0.1},
    "groceries": {"living": 1.0},
    "health & fitness": {"bills": 0.7, "living": 0.3},
    "home repair": {"bills": 0.9, "emergency": 0.1},
    "home utilities": {"bills": 1.0},
    "kids & pets": {"living": 1.0},
    "medical expense": {"bills": 0.8, "living": 0.2},
    "misc in store": {"discretionary": 1.0},
    "misc online": {"discretionary": 1.0},
    "salary": {"living": 0.1},
    "salary income": {"living": 0.1},
    "shopping in store": {"goals": 0.25, "discretionary": 0.75},
    "shopping online": {"goals": 0.25, "discretionary": 0.75},
    "transport": {"living": 1.0},
    "travel": {"goals": 0.7, "discretionary": 0.3},
}

ESSENTIAL_CATEGORY_HINTS = {"bills", "living", "emergency"}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def bucket_category(category_name: str) -> str:
    normalized = _normalize_text(category_name)
    hints = CATEGORY_ROLE_HINTS.get(normalized)
    if not hints:
        return "unknown"
    top_role = max(hints.items(), key=lambda item: item[1])[0]
    return "essential" if top_role in ESSENTIAL_CATEGORY_HINTS else "discretionary"


def score_text_role(name: str, description: str = "", keywords: Iterable[str] | None = None) -> Dict[str, float]:
    text = " ".join(filter(None, [_normalize_text(name), _normalize_text(description), " ".join(_normalize_text(item) for item in (keywords or []))]))
    scores: Dict[str, float] = {role: 0.0 for role in ROLE_KEYWORDS}
    if not text:
        return scores
    for role, role_keywords in ROLE_KEYWORDS.items():
        for token in role_keywords:
            if token in text:
                scores[role] += 1.0
    total = sum(scores.values())
    if total <= 0:
        return scores
    return {role: score / total for role, score in scores.items()}


def score_category_role(category_breakdown: Mapping[str, float]) -> Dict[str, float]:
    scores: Dict[str, float] = defaultdict(float)
    total = sum(max(0.0, float(amount)) for amount in category_breakdown.values())
    if total <= 0:
        return {role: 0.0 for role in ROLE_KEYWORDS}
    for category_name, amount in category_breakdown.items():
        hints = CATEGORY_ROLE_HINTS.get(_normalize_text(category_name), {})
        if not hints:
            continue
        share = max(0.0, float(amount)) / total
        for role, hint_score in hints.items():
            scores[role] += share * hint_score
    return {role: float(scores.get(role, 0.0)) for role in ROLE_KEYWORDS}


