from __future__ import annotations

from typing import Any, Dict

from orchestrator.nodes.intake import intake_node as legacy_intake


def intake_node(state: Dict[str, Any]) -> Dict[str, Any]:
    next_state = legacy_intake(state)
    if isinstance(next_state, dict) and next_state.get("response"):
        next_state["__short_circuit__"] = True
    return next_state
