from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict

from strands.agent.agent_result import AgentResult
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status, Usage, Metrics
from strands.telemetry.metrics import EventLoopMetrics
from strands.types.content import ContentBlock, Message
from observability.trace_context import log_trace_event, trace_context_from_state

logger = logging.getLogger(__name__)


class FunctionNode(MultiAgentBase):
    def __init__(self, node_id: str, func: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self.id = node_id
        self.node_id = node_id
        self.func = func

    async def invoke_async(self, task: str, invocation_state: Dict[str, Any], **kwargs: Any) -> MultiAgentResult:
        start = time.time()
        trace_ctx = trace_context_from_state(
            invocation_state,
            agent_name="orchestrator",
            tool_name=self.node_id,
            schema_version="v1",
        )
        log_trace_event(logger, "node_start", trace_ctx, payload={"node": self.node_id})

        if invocation_state.get("__short_circuit__") and self.node_id != "memory_update":
            elapsed_ms = int((time.time() - start) * 1000)
            usage = Usage(inputTokens=0, outputTokens=0, totalTokens=0)
            metrics = Metrics(latencyMs=elapsed_ms, promptTokens=0, completionTokens=0, totalTokens=0)
            agent_result = AgentResult(
                stop_reason="end_turn",
                message=Message(role="assistant", content=[ContentBlock(text="skipped")]),
                metrics=EventLoopMetrics(accumulated_usage=usage, accumulated_metrics=metrics),
                state=dict(invocation_state),
            )
            node_result = NodeResult(
                result=agent_result,
                execution_time=elapsed_ms,
                status=Status.COMPLETED,
                accumulated_usage=usage,
                accumulated_metrics=metrics,
                execution_count=1,
            )
            log_trace_event(
                logger,
                "node_end",
                trace_ctx,
                payload={"node": self.node_id, "latency_ms": elapsed_ms, "short_circuit": True},
            )
            return MultiAgentResult(
                status=Status.COMPLETED,
                results={self.node_id: node_result},
                accumulated_usage=usage,
                accumulated_metrics=metrics,
                execution_count=1,
                execution_time=elapsed_ms,
            )

        next_state = self.func(invocation_state)
        if isinstance(next_state, dict) and next_state is not invocation_state:
            invocation_state.clear()
            invocation_state.update(next_state)

        elapsed_ms = int((time.time() - start) * 1000)
        usage = Usage(inputTokens=0, outputTokens=0, totalTokens=0)
        metrics = Metrics(latencyMs=elapsed_ms, promptTokens=0, completionTokens=0, totalTokens=0)
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=self.node_id)]),
            metrics=EventLoopMetrics(accumulated_usage=usage, accumulated_metrics=metrics),
            state=dict(invocation_state),
        )
        node_result = NodeResult(
            result=agent_result,
            execution_time=elapsed_ms,
            status=Status.COMPLETED,
            accumulated_usage=usage,
            accumulated_metrics=metrics,
            execution_count=1,
        )
        log_trace_event(
            logger,
            "node_end",
            trace_ctx,
            payload={"node": self.node_id, "latency_ms": elapsed_ms, "short_circuit": False},
        )
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.node_id: node_result},
            accumulated_usage=usage,
            accumulated_metrics=metrics,
            execution_count=1,
            execution_time=elapsed_ms,
        )
