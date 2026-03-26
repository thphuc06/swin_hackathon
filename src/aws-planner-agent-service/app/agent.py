from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from strands import Agent
from strands.models import BedrockModel

from app.clients import MCPClient, build_finance_client, build_kb_client
from app.contracts import (
    AgentResultEnvelope,
    ErrorItem,
    PlannerRequest,
    PlannerResult,
    TraceInfo,
    WarningItem,
)
from app.prompts import SYSTEM_PROMPT, build_user_message
from app.tools import PlannerContext, build_tools
from app.trace import build_trace_context, log_event
from app.utils import extract_json_object

SCHEMA_VERSION = "v1"
AGENT_ID = "planner"
TOOL_NAME = "run_planner_agent_v1"

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_model() -> Optional[BedrockModel]:
    model_id = str(os.getenv("PLANNER_MODEL_ID") or os.getenv("BEDROCK_MODEL_ID") or "").strip()
    if not model_id:
        return None
    region = str(os.getenv("AWS_REGION") or "us-west-2").strip()
    temperature = _env_float("PLANNER_TEMPERATURE", 0.2)
    return BedrockModel(model_id=model_id, region_name=region, temperature=temperature)


def _build_agent(context: PlannerContext, finance_client: MCPClient, kb_client: Optional[MCPClient]) -> Agent:
    model = _build_model()
    tools = build_tools(context, finance_client, kb_client)
    if model is None:
        return Agent(tools=tools, system_prompt=SYSTEM_PROMPT)
    return Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)


def _stub_planner(request: PlannerRequest) -> PlannerResult:
    return PlannerResult(
        summary="Planner stub response.",
        key_facts=["Planner agent is running in stub mode."],
        recommendations=[
            {
                "title": "Disable stub mode",
                "rationale": "Set PLANNER_STUB_MODE=false and configure Bedrock model access.",
                "priority": "high",
                "expected_impact": "Enables full planner reasoning and tool usage.",
            }
        ],
        next_actions=[{"action": "Configure Bedrock model", "owner": "team", "timeframe": "next"}],
        citations=[],
        tool_trace=[],
        warnings=[{"code": "planner_stub", "message": "Planner is in stub mode.", "severity": "info"}],
    )


def _normalize_result(raw: Dict[str, Any], context: PlannerContext, fallback_summary: str) -> PlannerResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    if not data.get("summary"):
        data["summary"] = fallback_summary
    data.setdefault("key_facts", [])
    data.setdefault("recommendations", [])
    data.setdefault("next_actions", [])
    data.setdefault("citations", [])
    data.setdefault("warnings", [])
    data["tool_trace"] = context.tool_trace
    return PlannerResult.model_validate(data)


def run_planner(request: PlannerRequest) -> AgentResultEnvelope:
    start = time.time()
    warnings: list[WarningItem] = []

    hints = request.hints if isinstance(request.hints, dict) else {}
    request_timestamp = str(getattr(request, "request_timestamp", "") or hints.get("request_timestamp") or "").strip()
    trace_ctx = build_trace_context(
        trace_id=request.trace_id,
        session_id=request.session_id,
        agent_name=AGENT_ID,
        tool_name=TOOL_NAME,
        schema_version=SCHEMA_VERSION,
        request_timestamp=request_timestamp or None,
    )
    context = PlannerContext(trace_id=request.trace_id, trace_context=trace_ctx)
    finance_client = build_finance_client()
    kb_client = build_kb_client()
    log_event(
        logger,
        "planner_request_start",
        trace_ctx,
        payload={"stub_mode": _env_bool("PLANNER_STUB_MODE", False), "kb_enabled": kb_client is not None},
    )

    try:
        if _env_bool("PLANNER_STUB_MODE", False):
            planner_result = _stub_planner(request)
            status = "partial"
        else:
            agent = _build_agent(context, finance_client, kb_client)
            user_message = build_user_message(
                request.prompt,
                {
                    "user_context": request.user_context,
                    "goals": request.goals,
                    "session_summary": request.session_summary,
                    "policy_flags": request.policy_flags,
                    "hints": request.hints,
                    "requested_outputs": request.requested_outputs,
                    "trace_id": request.trace_id,
                },
            )
            result = agent(user_message)
            text = str(result)
            parsed = extract_json_object(text)
            if parsed is None:
                warnings.append(WarningItem(code="planner_parse", message="Planner output was not JSON.", severity="warn"))
                planner_result = _normalize_result({}, context, text)
                status = "partial"
            else:
                planner_result = _normalize_result(parsed, context, parsed.get("summary", ""))
                status = "ok"

        trace = TraceInfo(
            trace_id=request.trace_id,
            request_id=request.request_id,
            session_id=request.session_id,
            agent_name=AGENT_ID,
            tool_name=TOOL_NAME,
            schema_version=SCHEMA_VERSION,
            latency_ms=int((time.time() - start) * 1000),
            reason_codes=["stub_mode"] if _env_bool("PLANNER_STUB_MODE", False) else [],
            fallback_used=_env_bool("PLANNER_STUB_MODE", False),
        )

        envelope = AgentResultEnvelope(
            schema_version=SCHEMA_VERSION,
            agent_id=AGENT_ID,
            agent_version=str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0"),
            tool_name=TOOL_NAME,
            status=status,
            result=planner_result,
            summary=planner_result.summary,
            trace=trace,
            warnings=warnings,
            errors=[],
        )
        log_event(logger, "planner_request_end", trace_ctx, payload={"status": status})
        return envelope
    except Exception as exc:
        trace = TraceInfo(
            trace_id=request.trace_id,
            request_id=request.request_id,
            session_id=request.session_id,
            agent_name=AGENT_ID,
            tool_name=TOOL_NAME,
            schema_version=SCHEMA_VERSION,
            latency_ms=int((time.time() - start) * 1000),
            reason_codes=["exception"],
            fallback_used=True,
        )
        error_item = ErrorItem(code="planner_exception", message=str(exc), retryable=False)
        fallback = PlannerResult(
            summary="Planner failed to run.",
            key_facts=[],
            recommendations=[],
            next_actions=[],
            citations=[],
            tool_trace=context.tool_trace,
            warnings=[{"code": "planner_exception", "message": str(exc), "severity": "critical"}],
        )
        return AgentResultEnvelope(
            schema_version=SCHEMA_VERSION,
            agent_id=AGENT_ID,
            agent_version=str(os.getenv("SPECIALIST_AGENT_VERSION") or "0.1.0"),
            tool_name=TOOL_NAME,
            status="error",
            result=fallback,
            summary=fallback.summary,
            trace=trace,
            warnings=[WarningItem(code="planner_exception", message=str(exc), severity="critical")],
            errors=[error_item],
        )
