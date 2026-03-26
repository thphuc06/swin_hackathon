from __future__ import annotations

from typing import Any, Dict

from orchestrator.nodes.memory_update import memory_update_node as legacy_memory


def memory_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return legacy_memory(state)
