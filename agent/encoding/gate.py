from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from .contracts import EncodingDecisionV1

_COMMON_MOJIBAKE_PATTERNS = (
    "Ã",
    "Â",
    "á»",
    "â€",
    "Æ",
)
_CONTROL_ALLOWLIST = {"\n", "\r", "\t"}
_SUPPORTED_NORMALIZATION_FORMS = {"NFC", "NFD", "NFKC", "NFKD"}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _stable_fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]


def _safe_normalize(text: str, form: str) -> tuple[str, str]:
    normalized_form = str(form or "NFC").upper()
    if normalized_form not in _SUPPORTED_NORMALIZATION_FORMS:
        normalized_form = "NFC"
    return unicodedata.normalize(normalized_form, text), normalized_form


def _replacement_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    return text.count("\ufffd") / max(1, len(text))


def _mojibake_pattern_ratio(text: str) -> float:
    if not text:
        return 0.0
    total_hits = sum(text.count(pattern) for pattern in _COMMON_MOJIBAKE_PATTERNS)
    return total_hits / max(1, len(text))


def _control_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    hits = 0
    for char in text:
        if char in _CONTROL_ALLOWLIST:
            continue
        if unicodedata.category(char).startswith("C"):
            hits += 1
    return hits / max(1, len(text))


def _score_mojibake(text: str) -> tuple[float, list[str]]:
    replacement_ratio = _replacement_char_ratio(text)
    pattern_ratio = _mojibake_pattern_ratio(text)
    control_ratio = _control_char_ratio(text)

    reasons: list[str] = []
    if replacement_ratio > 0:
        reasons.append("replacement_char_detected")
    if pattern_ratio > 0:
        reasons.append("mojibake_pattern_detected")
    if control_ratio > 0:
        reasons.append("control_char_detected")
    if not reasons:
        reasons.append("clean_utf8")

    # Weighted score tuned for Vietnamese mojibake signatures.
    score = (replacement_ratio * 0.65) + (pattern_ratio * 2.5) + (control_ratio * 1.8)
    return _clamp01(score), reasons


def _attempt_repair(text: str, strategy: str) -> str | None:
    try:
        if strategy == "latin1_to_utf8":
            return text.encode("latin-1").decode("utf-8")
        if strategy == "cp1252_to_utf8":
            return text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return None
    return None


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def apply_prompt_encoding_gate(
    prompt: Any,
    *,
    gate_enabled: bool = True,
    repair_enabled: bool = True,
    repair_score_min: float = 0.12,
    failfast_score_min: float = 0.45,
    repair_min_delta: float = 0.10,
    normalization_form: str = "NFC",
) -> tuple[str, EncodingDecisionV1]:
    original_prompt = _safe_text(prompt)
    normalized_prompt, normalized_form = _safe_normalize(original_prompt, normalization_form)
    fingerprint = _stable_fingerprint(original_prompt)
    score, reason_codes = _score_mojibake(normalized_prompt)

    if not gate_enabled:
        return normalized_prompt, EncodingDecisionV1(
            decision="pass",
            mojibake_score=score,
            repair_applied=False,
            encoding_guess="",
            reason_codes=sorted(set([*reason_codes, "encoding_gate_disabled", f"normalized_{normalized_form.lower()}"])),
            input_fingerprint=fingerprint,
        )

    selected_text = normalized_prompt
    selected_score = score
    selected_guess = ""
    selected_repair_applied = False

    should_try_repair = bool(repair_enabled and score >= max(0.0, float(repair_score_min)))
    if should_try_repair:
        candidates: list[tuple[float, str, str]] = []
        for strategy in ("latin1_to_utf8", "cp1252_to_utf8"):
            repaired = _attempt_repair(normalized_prompt, strategy)
            if repaired is None:
                continue
            repaired_norm, _ = _safe_normalize(repaired, normalized_form)
            repaired_score, _ = _score_mojibake(repaired_norm)
            delta = score - repaired_score
            if delta >= float(repair_min_delta):
                candidates.append((repaired_score, strategy, repaired_norm))
        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]))
            selected_score, selected_guess, selected_text = candidates[0]
            selected_repair_applied = True
            reason_codes.append(f"repair_applied_{selected_guess}")
        else:
            reason_codes.append("repair_not_improved")

    final_score = selected_score
    decision = "repair" if selected_repair_applied else "pass"
    if final_score >= float(failfast_score_min):
        decision = "fail_fast"
        reason_codes.append("encoding_fail_fast_threshold_exceeded")

    decision_payload = EncodingDecisionV1(
        decision=decision,
        mojibake_score=_clamp01(final_score),
        repair_applied=selected_repair_applied,
        encoding_guess=selected_guess,
        reason_codes=sorted(set([*reason_codes, f"normalized_{normalized_form.lower()}"])),
        input_fingerprint=fingerprint,
    )
    return selected_text, decision_payload
