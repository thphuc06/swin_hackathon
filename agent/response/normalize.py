from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def fmt_money(value: Any) -> str:
    numeric = round(safe_float(value), 2)
    if abs(numeric - round(numeric)) < 0.01:
        return f"{int(round(numeric)):,}"
    return f"{numeric:,.2f}"


def fmt_signed_money(value: Any) -> str:
    numeric = safe_float(value)
    sign = "-" if numeric < 0 else "+"
    return f"{sign}{fmt_money(abs(numeric))}"


def fmt_pct(value: Any) -> str:
    numeric = safe_float(value)
    if abs(numeric) > 1.0:
        return f"{numeric:.2f}%"
    return f"{numeric * 100:.2f}%"

