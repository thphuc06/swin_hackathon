from __future__ import annotations

from typing import Any, Dict


def aggregate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import fetch_context, retrieve_kb

    next_state = fetch_context(state)  # type: ignore[assignment]
    return retrieve_kb(next_state)  # type: ignore[return-value]

