from __future__ import annotations

from typing import Any, Dict


def respond_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import reasoning

    return reasoning(state)  # type: ignore[return-value]

