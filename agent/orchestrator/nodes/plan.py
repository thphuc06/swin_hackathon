from __future__ import annotations

from typing import Any, Dict


def plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import intent_router

    return intent_router(state)  # type: ignore[return-value]

