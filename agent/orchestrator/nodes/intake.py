from __future__ import annotations

from typing import Any, Dict


def intake_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import encoding_gate

    return encoding_gate(state)  # type: ignore[return-value]

