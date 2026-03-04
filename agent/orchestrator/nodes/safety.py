from __future__ import annotations

from typing import Any, Dict


def safety_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import suitability_guard

    return suitability_guard(state)  # type: ignore[return-value]

