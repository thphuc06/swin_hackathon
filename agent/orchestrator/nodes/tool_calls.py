from __future__ import annotations

from typing import Any, Dict


def tool_calls_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import decision_engine

    return decision_engine(state)  # type: ignore[return-value]

