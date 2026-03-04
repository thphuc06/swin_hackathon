from __future__ import annotations

from typing import Any, Dict


def memory_update_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from graph import memory_update

    return memory_update(state)  # type: ignore[return-value]

