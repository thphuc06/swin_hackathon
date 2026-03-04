from __future__ import annotations

from typing import Any, Dict


def select_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import select_agent

    return select_agent(state)  # type: ignore[return-value]

