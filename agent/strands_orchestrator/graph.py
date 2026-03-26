from __future__ import annotations

from typing import Any

from strands.multiagent import GraphBuilder

from strands_orchestrator.nodes import (
    aggregation_node,
    delegation_node,
    intake_node,
    memory_node,
    response_node,
    routing_node,
    safety_node,
    tool_invocation_node,
)
from strands_orchestrator.nodes.function_node import FunctionNode


def build_graph() -> Any:
    builder = GraphBuilder()

    builder.add_node(FunctionNode("intake", intake_node), "intake")
    builder.add_node(FunctionNode("safety", safety_node), "safety")
    builder.add_node(FunctionNode("routing", routing_node), "routing")
    builder.add_node(FunctionNode("delegation", delegation_node), "delegation")
    builder.add_node(FunctionNode("tool_invocation", tool_invocation_node), "tool_invocation")
    builder.add_node(FunctionNode("aggregation", aggregation_node), "aggregation")
    builder.add_node(FunctionNode("response", response_node), "response")
    builder.add_node(FunctionNode("memory_update", memory_node), "memory_update")

    builder.add_edge("intake", "safety")
    builder.add_edge("safety", "routing")
    builder.add_edge("routing", "delegation")
    builder.add_edge("delegation", "tool_invocation")
    builder.add_edge("tool_invocation", "aggregation")
    builder.add_edge("aggregation", "response")
    builder.add_edge("response", "memory_update")

    builder.set_entry_point("intake")
    return builder.build()
