from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

import requests
from fastapi import APIRouter
from jsonschema import Draft202012Validator, RefResolver, ValidationError
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from app.trace import extract_trace_context, log_event
from planner_agent.agent import run_planner
from service_agent.agent import run_service
from stock.adapter import run_stock

router = APIRouter(tags=["mcp"])
logger = logging.getLogger(__name__)

SERVER_NAME = "specialist-agent-mcp-server"
SERVER_VERSION = "0.1.0"
SCHEMA_VERSION = "v1"

TOOL_NAMES = {
    "run_planner_agent_v1": "Planner specialist tool",
    "run_service_agent_v1": "Service roadmap specialist tool",
    "run_stock_agent_v1": "Stock specialist tool",
}

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_STRIP_KEYS = {"$id", "$schema", "title", "examples"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _resolve_tool_name(name: str) -> str:
    if name in TOOL_NAMES:
        return name
    for delimiter in ("___", "__"):
        if delimiter in name:
            suffix = name.split(delimiter)[-1]
            if suffix in TOOL_NAMES:
                return suffix
    return name


def _load_schema(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_tool_schemas() -> Dict[str, Dict[str, Any]]:
    return {
        "run_planner_agent_v1": _load_schema(SCHEMA_DIR / "run_planner_agent_v1.input.json"),
        "run_service_agent_v1": _load_schema(SCHEMA_DIR / "run_service_agent_v1.input.json"),
        "run_stock_agent_v1": _load_schema(SCHEMA_DIR / "run_stock_agent_v1.input.json"),
    }


def _load_output_schema(name: str) -> Dict[str, Any]:
    if name == "run_planner_agent_v1":
        return _load_schema(SCHEMA_DIR / "run_planner_agent_v1.output.json")
    if name == "run_service_agent_v1":
        return _load_schema(SCHEMA_DIR / "run_service_agent_v1.output.json")
    if name == "run_stock_agent_v1":
        return _load_schema(SCHEMA_DIR / "run_stock_agent_v1.output.json")
    return {}


def _schema_store() -> Dict[str, Dict[str, Any]]:
    store: Dict[str, Dict[str, Any]] = {}
    for path in SCHEMA_DIR.glob("*.json"):
        data = _load_schema(path)
        store[str(data.get("$id") or path.name)] = data
    return store


def _sanitize_schema(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if key in SCHEMA_STRIP_KEYS:
                continue
            cleaned[key] = _sanitize_schema(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_schema(item) for item in value]
    return value


OUTPUT_SCHEMA_STORE = _schema_store()
TOOL_SCHEMAS = _load_tool_schemas()
PUBLIC_TOOL_SCHEMAS = {name: _sanitize_schema(schema) for name, schema in TOOL_SCHEMAS.items()}
TOOL_VALIDATORS = {name: Draft202012Validator(schema) for name, schema in TOOL_SCHEMAS.items()}


def _build_tool_definitions() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_planner_agent_v1",
            description="Planner specialist wrapper with canonical actor/correlation envelope.",
            inputSchema=PUBLIC_TOOL_SCHEMAS["run_planner_agent_v1"],
        ),
        types.Tool(
            name="run_service_agent_v1",
            description="Service roadmap specialist wrapper with structured roadmap contract output.",
            inputSchema=PUBLIC_TOOL_SCHEMAS["run_service_agent_v1"],
        ),
        types.Tool(
            name="run_stock_agent_v1",
            description="Stock specialist wrapper with local adapter compatibility.",
            inputSchema=PUBLIC_TOOL_SCHEMAS["run_stock_agent_v1"],
        ),
    ]


MCP_TOOLS = _build_tool_definitions()


def _validate_arguments(tool_name: str, arguments: Dict[str, Any]) -> None:
    validator = TOOL_VALIDATORS.get(tool_name)
    if not validator:
        raise ValidationError(f"No schema for tool {tool_name}")
    validator.validate(arguments)


def _validate_output(tool_name: str, result: Dict[str, Any]) -> None:
    output_schema = _load_output_schema(tool_name)
    if not output_schema:
        return
    resolver = RefResolver.from_schema(output_schema, store=OUTPUT_SCHEMA_STORE)
    Draft202012Validator(output_schema, resolver=resolver).validate(result)


def _tool_result_text(payload: Dict[str, Any], *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        isError=is_error,
    )


def _tool_error(message: str, *, data: Any = None) -> types.CallToolResult:
    payload: Dict[str, Any] = {"error": message}
    if data is not None:
        payload["data"] = data
    return _tool_result_text(payload, is_error=True)


def _server_tool_result(payload: Dict[str, Any], *, is_error: bool = False) -> types.ServerResult:
    return types.ServerResult(
        root=types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            isError=is_error,
        )
    )


def _server_tool_error(message: str, *, data: Any = None) -> types.ServerResult:
    payload: Dict[str, Any] = {"error": message}
    if data is not None:
        payload["data"] = data
    return _server_tool_result(payload, is_error=True)


def _handle_planner(arguments: Dict[str, Any], *, trace_ctx: Dict[str, Any]) -> Dict[str, Any]:
    return run_planner(arguments)


def _handle_stock(arguments: Dict[str, Any], *, trace_ctx: Dict[str, Any]) -> Dict[str, Any]:
    log_event(logger, "stock_adapter_start", trace_ctx, payload={"mode": "external_app_runner"})
    result = run_stock(arguments)
    log_event(logger, "stock_adapter_end", trace_ctx, payload={"status": result.get("status", "ok")})
    return result


def _handle_service(arguments: Dict[str, Any], *, trace_ctx: Dict[str, Any]) -> Dict[str, Any]:
    log_event(logger, "service_agent_start", trace_ctx, payload={"mode": "hybrid_roadmap"})
    result = run_service(arguments)
    log_event(logger, "service_agent_end", trace_ctx, payload={"status": result.get("status", "ok")})
    return result


def _tool_headers() -> Dict[str, str]:
    return {
        "X-Agent-Name": SERVER_NAME,
        "X-Schema-Version": SCHEMA_VERSION,
    }


def _validation_error_payload(exc: ValidationError) -> Dict[str, Any]:
    path = [str(item) for item in list(getattr(exc, "absolute_path", []) or [])]
    schema_path = [str(item) for item in list(getattr(exc, "absolute_schema_path", []) or [])]
    return {
        "message": str(exc),
        "path": path,
        "schema_path": schema_path,
        "validator": str(getattr(exc, "validator", "") or ""),
    }


MCP_SERVER = Server(name=SERVER_NAME, version=SERVER_VERSION)


@MCP_SERVER.list_tools()
async def list_tools() -> list[types.Tool]:
    logger.warning("mcp_tools_list tool_count=%s", len(MCP_TOOLS))
    return MCP_TOOLS


async def _execute_call_tool(tool_name: str, arguments: Dict[str, Any]) -> types.ServerResult:
    requested_name = str(tool_name or "")
    resolved_tool_name = _resolve_tool_name(requested_name)
    trace_ctx = extract_trace_context(arguments, _tool_headers())

    log_event(logger, "mcp_tool_call_start", trace_ctx, payload={"tool_name": resolved_tool_name})
    start = time.time()

    try:
        if resolved_tool_name not in TOOL_NAMES:
            return _server_tool_error(f"Unknown tool: {requested_name}")

        _validate_arguments(resolved_tool_name, arguments)
        if resolved_tool_name == "run_planner_agent_v1":
            result = _handle_planner(arguments, trace_ctx=trace_ctx)
        elif resolved_tool_name == "run_service_agent_v1":
            result = _handle_service(arguments, trace_ctx=trace_ctx)
        else:
            result = _handle_stock(arguments, trace_ctx=trace_ctx)

        if isinstance(result, dict) and result.get("schema_version") == SCHEMA_VERSION:
            _validate_output(resolved_tool_name, result)
        return _server_tool_result(result)
    except ValidationError as exc:
        log_event(logger, "mcp_tool_call_error", trace_ctx, payload={"error": str(exc), "tool_name": resolved_tool_name})
        return _server_tool_error("Invalid tool arguments", data=_validation_error_payload(exc))
    except Exception as exc:
        logger.exception("Specialist tool execution failed: tool=%s error=%s", resolved_tool_name, exc)
        log_event(logger, "mcp_tool_call_error", trace_ctx, payload={"error": str(exc), "tool_name": resolved_tool_name})
        return _server_tool_error(
            "Tool execution failed",
            data={"tool": resolved_tool_name, "error_type": type(exc).__name__, "message": str(exc)},
        )
    finally:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info("Specialist tool call finished: tool=%s latency_ms=%s", resolved_tool_name, elapsed_ms)
        log_event(logger, "mcp_tool_call_end", trace_ctx, payload={"tool_name": resolved_tool_name, "latency_ms": elapsed_ms})


async def _call_tool_request_handler(req: types.CallToolRequest) -> types.ServerResult:
    return await _execute_call_tool(req.params.name, req.params.arguments or {})


MCP_SERVER.request_handlers[types.CallToolRequest] = _call_tool_request_handler


def create_mcp_session_manager() -> StreamableHTTPSessionManager:
    return StreamableHTTPSessionManager(
        app=MCP_SERVER,
        json_response=True,
        stateless=False,
    )


class StreamableHTTPASGIApp:
    def __init__(self, get_session_manager: Callable[[], StreamableHTTPSessionManager | None]) -> None:
        self.get_session_manager = get_session_manager

    async def __call__(self, scope, receive, send) -> None:
        session_manager = self.get_session_manager()
        if session_manager is None:
            raise RuntimeError("MCP session manager is not initialized.")
        await session_manager.handle_request(scope, receive, send)


@router.get("/mcp-health")
def mcp_health() -> str:
    return "MCP streamable HTTP endpoint ready at /mcp."
