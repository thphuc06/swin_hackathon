from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
SPECIALIST_ROOT = REPO_ROOT / "src" / "aws-specialist-agent-mcp-server"
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(SPECIALIST_ROOT))

from planner_agent.agent import run_planner
from planner_agent.contracts import PlannerResult, SpecialistRequestEnvelope
from planner_agent.finance.data import fetch_profiles
from planner_agent.finance.supabase_rest import get_supabase_client
from planner_agent.policy import build_tool_plan, normalize_planner_intent
from planner_agent.reporting import (
    build_standardized_runtime_metadata,
    build_standardized_txt_report,
    build_standardized_txt_report_from_contract,
)
from planner_agent.timeframe import derive_timeframe_hint
from planner_agent.tool_router import PlannerContext, invoke_finance_tool


def _load_repo_env() -> None:
    for env_path in (
        SPECIALIST_ROOT / ".env",
        REPO_ROOT / "backend" / ".env",
        REPO_ROOT / "agent" / ".env",
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)
    os.environ.setdefault("PLANNER_EXECUTION_MODE", "deterministic")


def _request_envelope(*, prompt: str, user_id: str, intent: str, session_id: str, trace_id: str) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "actor": {
            "actor_id": user_id,
            "user_id": user_id,
            "tenant_id": "",
            "scopes": ["chat:invoke", "finance:read"],
        },
        "correlation": {
            "session_id": session_id,
            "request_id": f"req_{uuid.uuid4().hex[:10]}",
            "trace_id": trace_id,
            "parent_request_id": "",
            "request_timestamp": "",
        },
        "request": {
            "prompt": prompt,
            "intent": normalize_planner_intent(intent),
            "policy_flags": {},
            "user_context": {},
            "goals": [],
            "session_summary": "",
        },
        "routing": {
            "specialist_id": "planner",
            "tool_name": "run_planner_agent_v1",
        },
    }


def _collect_tool_results(request: SpecialistRequestEnvelope) -> Dict[str, Dict[str, Any]]:
    context = PlannerContext(
        actor=request.actor,
        correlation=request.correlation,
        trace_context={
            "trace_id": request.correlation.trace_id,
            "session_id": request.correlation.session_id,
            "agent_name": "planner",
            "tool_name": "run_planner_agent_v1",
            "schema_version": request.schema_version,
            "request_timestamp": request.correlation.request_timestamp,
        },
        supabase_client=get_supabase_client(),
        timeframe_hint=derive_timeframe_hint(request.request.prompt, request.request.user_context),
    )
    tool_results: Dict[str, Dict[str, Any]] = {}
    for tool_name, kwargs in build_tool_plan(request, context):
        tool_results[tool_name] = invoke_finance_tool(context, tool_name, **kwargs)
    return tool_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a standardized financial TXT report.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--intent", default="planning")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--trace-id", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    _load_repo_env()

    session_id = str(args.session_id or f"sess_{uuid.uuid4().hex}")
    trace_id = str(args.trace_id or f"trc_{uuid.uuid4().hex[:10]}")
    request = SpecialistRequestEnvelope.model_validate(
        _request_envelope(
            prompt=args.prompt,
            user_id=args.user_id,
            intent=args.intent,
            session_id=session_id,
            trace_id=trace_id,
        )
    )

    planner_envelope = run_planner(request.model_dump())
    standardized_contract = planner_envelope.get("standardized_contract")
    if isinstance(standardized_contract, dict) and standardized_contract:
        report_text = build_standardized_txt_report_from_contract(standardized_contract)
    else:
        tool_results = _collect_tool_results(request)
        planner_result = PlannerResult.model_validate(planner_envelope["result"])
        profiles = fetch_profiles(get_supabase_client(), args.user_id)

        report_text = build_standardized_txt_report(
            request=request,
            planner_result=planner_result,
            planner_status=str(planner_envelope.get("status") or "ok"),
            tool_results=tool_results,
            profile=profiles[0] if profiles else {},
            runtime_metadata=build_standardized_runtime_metadata(
                request_id=request.correlation.request_id,
                runtime_source="planner_core_direct",
                response_mode="standardized_txt_generator",
                response_reason_codes=["planner_policy", "finance_tool_grounded"],
            ),
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
