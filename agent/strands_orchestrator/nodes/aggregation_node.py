from __future__ import annotations

from typing import Any, Dict

from orchestrator.nodes.aggregate import aggregate_node as legacy_aggregate


def aggregation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return legacy_aggregate(state)
