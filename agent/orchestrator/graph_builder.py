from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes.aggregate import aggregate_node
from .nodes.intake import intake_node
from .nodes.memory_update import memory_update_node
from .nodes.plan import plan_node
from .nodes.respond import respond_node
from .nodes.safety import safety_node
from .nodes.select_agent import select_agent_node
from .nodes.tool_calls import tool_calls_node


def build_orchestrator_graph(state_schema: Any) -> Any:
    """Build the P0 orchestrator flow with explicit phase-oriented nodes."""
    graph = StateGraph(state_schema)
    graph.add_node("intake", intake_node)
    graph.add_node("plan", plan_node)
    graph.add_node("safety", safety_node)
    graph.add_node("select_agent", select_agent_node)
    graph.add_node("execute_tools", tool_calls_node)
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("respond", respond_node)
    graph.add_node("persist_memory", memory_update_node)

    graph.set_entry_point("intake")
    graph.add_conditional_edges(
        "intake",
        lambda state: "persist_memory" if state.get("response") else "plan",
        {
            "persist_memory": "persist_memory",
            "plan": "plan",
        },
    )
    graph.add_edge("plan", "safety")
    graph.add_edge("safety", "select_agent")
    graph.add_edge("select_agent", "execute_tools")
    graph.add_edge("execute_tools", "aggregate")
    graph.add_edge("aggregate", "respond")
    graph.add_edge("respond", "persist_memory")
    graph.add_edge("persist_memory", END)
    return graph.compile()
