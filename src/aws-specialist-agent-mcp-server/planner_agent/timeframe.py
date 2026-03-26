from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable

_RETROSPECTIVE_CUES = (
    "gan day",
    "qua",
    "vua qua",
    "last",
    "past",
    "recent",
)
_FUTURE_CUES = (
    "thang toi",
    "ngay toi",
    "tuan toi",
    "nam toi",
    "next",
    "upcoming",
)

_UNIT_PATTERNS = (
    ("days", 1, re.compile(r"(?P<value>\d+)\s*(?P<unit>ngay|day|days)\b", re.IGNORECASE)),
    ("weeks", 7, re.compile(r"(?P<value>\d+)\s*(?P<unit>tuan|week|weeks)\b", re.IGNORECASE)),
    ("months", 30, re.compile(r"(?P<value>\d+)\s*(?P<unit>thang|month|months)\b", re.IGNORECASE)),
    ("years", 365, re.compile(r"(?P<value>\d+)\s*(?P<unit>nam|year|years)\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class TimeframeHint:
    analysis_days: int | None = None
    analysis_months: int | None = None
    source: str = ""
    matched_text: str = ""

    @property
    def spend_range(self) -> str | None:
        if self.analysis_days is None:
            return None
        return f"{self.analysis_days}d"

    @property
    def lookback_days(self) -> int | None:
        return self.analysis_days

    @property
    def lookback_months(self) -> int | None:
        if self.analysis_months is not None:
            return self.analysis_months
        if self.analysis_days is None:
            return None
        return max(1, math.ceil(self.analysis_days / 30))

    @property
    def history_days(self) -> int | None:
        return self.analysis_days

    def as_prompt_hints(self) -> Dict[str, Any]:
        return {
            "analysis_days": self.analysis_days,
            "analysis_months": self.analysis_months,
            "source": self.source,
            "matched_text": self.matched_text,
        }


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_only)


def _candidate_from_slots(slots: Dict[str, Any]) -> TimeframeHint:
    if not isinstance(slots, dict):
        return TimeframeHint()

    raw_days = slots.get("analysis_period_days") or slots.get("time_period_days") or slots.get("lookback_days")
    if isinstance(raw_days, (int, float)) and int(raw_days) > 0:
        days = max(1, min(720, int(raw_days)))
        return TimeframeHint(
            analysis_days=days,
            analysis_months=max(1, math.ceil(days / 30)),
            source="slots.days",
            matched_text=str(raw_days),
        )

    raw_months = slots.get("analysis_period_months") or slots.get("time_period_months") or slots.get("lookback_months")
    if isinstance(raw_months, (int, float)) and int(raw_months) > 0:
        months = max(1, min(24, int(raw_months)))
        return TimeframeHint(
            analysis_days=max(1, min(720, months * 30)),
            analysis_months=months,
            source="slots.months",
            matched_text=str(raw_months),
        )

    return TimeframeHint()


def _iter_slot_sources(user_context: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if not isinstance(user_context, dict):
        return []
    sources = [user_context]
    extraction_slots = user_context.get("extraction_slots")
    if isinstance(extraction_slots, dict):
        sources.append(extraction_slots)
    return sources


def _score_context(text: str) -> int:
    score = 0
    if any(cue in text for cue in _RETROSPECTIVE_CUES):
        score += 2
    if any(cue in text for cue in _FUTURE_CUES):
        score -= 2
    return score


def _candidate_from_prompt(prompt: str) -> TimeframeHint:
    normalized_prompt = _normalize_text(prompt)
    if not normalized_prompt:
        return TimeframeHint()

    best: tuple[int, int, TimeframeHint] | None = None
    for unit_name, multiplier, pattern in _UNIT_PATTERNS:
        for match in pattern.finditer(normalized_prompt):
            raw_value = int(match.group("value"))
            if raw_value <= 0:
                continue
            days = max(1, min(720, raw_value * multiplier))
            months = max(1, math.ceil(days / 30))
            context_start = max(0, match.start() - 24)
            context_end = min(len(normalized_prompt), match.end() + 24)
            context = normalized_prompt[context_start:context_end]
            score = _score_context(context)
            if unit_name in {"months", "years"} and score >= 0:
                score += 1
            candidate = TimeframeHint(
                analysis_days=days,
                analysis_months=months,
                source="prompt",
                matched_text=match.group(0),
            )
            ranking = (score, -match.start())
            if best is None or ranking > best[:2]:
                best = (ranking[0], ranking[1], candidate)

    if best is None:
        return TimeframeHint()
    return best[2]


def derive_timeframe_hint(prompt: str, user_context: Dict[str, Any] | None = None) -> TimeframeHint:
    for slot_source in _iter_slot_sources(user_context or {}):
        candidate = _candidate_from_slots(slot_source)
        if candidate.analysis_days is not None:
            return candidate
    return _candidate_from_prompt(prompt)
