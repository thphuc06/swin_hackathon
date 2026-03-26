from __future__ import annotations

from typing import Any, Dict

from orchestrator.nodes.plan import plan_node as legacy_plan


def routing_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return legacy_plan(state)
