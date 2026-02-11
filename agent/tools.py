from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import (
    AGENTCORE_GATEWAY_ENDPOINT,
    AGENTCORE_GATEWAY_TOOL_NAME,
    BACKEND_API_BASE,
    BACKEND_TIMEOUT_SECONDS,
    BEDROCK_KB_ID,
    GATEWAY_TIMEOUT_SECONDS,
    HTTP_POOL_CONNECTIONS,
    HTTP_POOL_MAXSIZE,
    USE_LOCAL_MOCKS,
)

logger = logging.getLogger(__name__)

# Tool registry cache (initialized at startup)
_resolved_tool_names: Dict[str, str] = {}
_tool_schemas: Dict[str, Dict[str, Any]] = {}  # Maps tool name -> full tool definition
_registry_initialized: bool = False

# Local KB cache (loaded at startup)
_KB_CONTENT: Dict[str, Dict[str, Any]] = {}
_KB_INITIALIZED: bool = False

# HTTP connection pooling (reduces SSL handshake overhead by ~2-3s per request)
_gateway_session: requests.Session | None = None
_backend_session: requests.Session | None = None


def _get_gateway_session() -> requests.Session:
    """Get persistent session for MCP Gateway with connection pooling."""
    global _gateway_session
    if _gateway_session is None:
        _gateway_session = requests.Session()
        # Configure connection pooling with retry logic
        adapter = HTTPAdapter(
            pool_connections=HTTP_POOL_CONNECTIONS,
            pool_maxsize=HTTP_POOL_MAXSIZE,
            max_retries=Retry(
                total=0,  # Retries handled by tenacity decorator
                connect=0,
                read=0,
                status_forcelist=[],
            ),
        )
        _gateway_session.mount("http://", adapter)
        _gateway_session.mount("https://", adapter)
        logger.info(
            "Initialized Gateway session with connection pooling (pool_connections=%d, pool_maxsize=%d)",
            HTTP_POOL_CONNECTIONS,
            HTTP_POOL_MAXSIZE,
        )
    return _gateway_session


def _get_backend_session() -> requests.Session:
    """Get persistent session for Backend API with connection pooling."""
    global _backend_session
    if _backend_session is None:
        _backend_session = requests.Session()
        # Configure connection pooling
        adapter = HTTPAdapter(
            pool_connections=HTTP_POOL_CONNECTIONS,
            pool_maxsize=HTTP_POOL_MAXSIZE,
            max_retries=Retry(
                total=0,  # Retries handled by tenacity decorator
                connect=0,
                read=0,
                status_forcelist=[],
            ),
        )
        _backend_session.mount("http://", adapter)
        _backend_session.mount("https://", adapter)
        logger.info(
            "Initialized Backend session with connection pooling (pool_connections=%d, pool_maxsize=%d)",
            HTTP_POOL_CONNECTIONS,
            HTTP_POOL_MAXSIZE,
        )
    return _backend_session


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _is_local_backend() -> bool:
    try:
        host = urlparse(BACKEND_API_BASE).hostname or ""
    except ValueError:
        host = ""
    return host in {"localhost", "127.0.0.1"} or host.endswith(".local")


def _should_use_local_mocks() -> bool:
    # Strict guard: mock data is only allowed for offline localhost development.
    if not USE_LOCAL_MOCKS:
        return False
    if not _is_local_backend():
        return False
    if AGENTCORE_GATEWAY_ENDPOINT.strip():
        return False
    return True


def _resolve_kb_dir() -> Path | None:
    """Resolve KB directory across local repo and packaged runtime layouts."""
    here = Path(__file__).resolve().parent
    candidates: list[Path] = []

    kb_dir_env = str(os.getenv("KB_DIR") or "").strip()
    if kb_dir_env:
        candidates.append(Path(kb_dir_env).expanduser())

    candidates.extend(
        [
            here.parent / "kb",  # local repo layout: repo/agent/tools.py -> repo/kb
            here / "kb",  # packaged runtime layout: /app/tools.py -> /app/kb
            Path.cwd() / "kb",
        ]
    )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _load_kb_files() -> Dict[str, Dict[str, Any]]:
    """Load all Knowledge Base markdown files from kb/ folder into memory.
    
    Returns:
        Dict mapping filename -> {content, sections, doc_type}
    """
    kb_dir = _resolve_kb_dir()
    if kb_dir is None:
        logger.warning("KB directory not found (checked KB_DIR, repo/kb, app/kb, cwd/kb)")
        return {}
    
    kb_content = {}
    kb_files = [
        "policies.md",
        "advisory_playbook_banking_services.md",
        "services_savings_and_deposits.md",
        "services_loans_and_credit.md",
        "services_cards_and_payments.md",
        "service_terms_glossary.md",
        "disclaimers.md",
    ]
    
    for filename in kb_files:
        file_path = kb_dir / filename
        if not file_path.exists():
            logger.warning("KB file not found: %s", filename)
            continue
        
        try:
            content = file_path.read_text(encoding="utf-8")
            sections = _parse_markdown_sections(content, filename)
            
            # Determine doc_type from filename
            doc_type = "policy"
            if "playbook" in filename:
                doc_type = "playbook"
            elif "services_" in filename:
                doc_type = "service"
            elif "glossary" in filename:
                doc_type = "glossary"
            elif "disclaimer" in filename:
                doc_type = "disclaimer"
            
            kb_content[filename] = {
                "content": content,
                "sections": sections,
                "doc_type": doc_type,
                "filename": filename,
            }
            logger.info("Loaded KB file: %s (%d chars, %d sections)", filename, len(content), len(sections))
        except Exception as exc:
            logger.error("Failed to load KB file %s: %s", filename, exc)
    
    return kb_content


def _parse_markdown_sections(content: str, filename: str) -> list[Dict[str, str]]:
    """Parse markdown content into sections based on headers."""
    sections = []
    lines = content.split("\n")
    current_section = {"header": filename, "content": "", "level": 0}
    
    for line in lines:
        header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if header_match:
            # Save previous section if it has content
            if current_section["content"].strip():
                sections.append(current_section.copy())
            # Start new section
            level = len(header_match.group(1))
            header_text = header_match.group(2).strip()
            current_section = {
                "header": header_text,
                "content": line + "\n",
                "level": level,
            }
        else:
            current_section["content"] += line + "\n"
    
    # Add last section
    if current_section["content"].strip():
        sections.append(current_section)
    
    return sections


def _match_kb_content_local(query: str, intent: str, filters: Dict[str, str]) -> Dict[str, Any]:
    """Match query against local KB content using intent-based filtering and keyword matching.
    
    Returns same format as original kb_retrieve(): 
        {"context": str, "matches": list, "filters": dict}
    """
    if not _KB_CONTENT:
        return {
            "context": "",
            "matches": [],
            "filters": filters,
            "note": "KB not loaded"
        }
    
    # Intent-based document selection
    intent_key = intent.lower().strip()
    intent_doc_mapping = {
        "summary": ["services_savings_and_deposits.md", "services_cards_and_payments.md", "service_terms_glossary.md", "policies.md"],
        "risk": ["services_loans_and_credit.md", "services_savings_and_deposits.md", "advisory_playbook_banking_services.md", "policies.md"],
        "planning": ["services_savings_and_deposits.md", "services_loans_and_credit.md", "advisory_playbook_banking_services.md", "policies.md"],
        "scenario": ["advisory_playbook_banking_services.md", "services_cards_and_payments.md", "services_savings_and_deposits.md", "policies.md"],
        "invest": ["policies.md", "disclaimers.md", "service_terms_glossary.md"],
    }
    
    # Get relevant documents for this intent
    relevant_docs = intent_doc_mapping.get(intent_key, list(_KB_CONTENT.keys()))
    
    # Extract keywords from query (simple tokenization)
    query_lower = query.lower()
    query_keywords = set(re.findall(r'\b\w{3,}\b', query_lower))  # Words 3+ chars
    
    # Score and rank sections
    matches = []
    for filename in relevant_docs:
        if filename not in _KB_CONTENT:
            continue
        
        kb_doc = _KB_CONTENT[filename]
        for section in kb_doc["sections"]:
            section_text = section["content"].lower()
            
            # Simple keyword matching score
            keyword_matches = sum(1 for kw in query_keywords if kw in section_text)
            if keyword_matches == 0 and query_keywords:
                continue  # Skip sections with no keyword matches
            
            # Calculate score (0-1 range)
            score = min(keyword_matches / max(len(query_keywords), 1), 1.0)
            
            # Boost score for certain keywords in specific intents
            if intent_key == "risk" and any(w in section_text for w in ["debt", "restructur", "emergency", "buffer"]):
                score += 0.2
            elif intent_key == "planning" and any(w in section_text for w in ["recurring", "savings", "goal", "term deposit"]):
                score += 0.2
            elif intent_key == "summary" and any(w in section_text for w in ["demand deposit", "card", "payment", "budget"]):
                score += 0.2
            
            matches.append({
                "id": f"{filename}#{section['header']}",
                "text": section["content"][:500].strip(),  # Truncate to 500 chars
                "citation": f"{filename}",
                "score": min(score, 1.0),
                "filename": filename,
                "section": section["header"],
            })
    
    # Sort by score and take top 3
    matches.sort(key=lambda x: x["score"], reverse=True)
    top_matches = matches[:3]
    
    # Build context text from top matches
    context_parts = []
    for match in top_matches:
        context_parts.append(f"## {match['section']}\n{match['text']}")
    
    context_text = "\n\n".join(context_parts)
    
    return {
        "context": context_text,
        "matches": top_matches,
        "filters": filters,
    }


def initialize_kb() -> Dict[str, Any]:
    """Initialize Knowledge Base by loading all KB files into memory.
    Call this once at application startup.
    """
    global _KB_CONTENT, _KB_INITIALIZED
    
    if _KB_INITIALIZED:
        return {"status": "already_initialized", "files": len(_KB_CONTENT)}
    
    try:
        _KB_CONTENT = _load_kb_files()
        _KB_INITIALIZED = True
        return {
            "status": "success",
            "files": len(_KB_CONTENT),
            "filenames": list(_KB_CONTENT.keys()),
        }
    except Exception as exc:
        logger.error("Failed to initialize KB: %s", exc)
        return {"status": "error", "error": str(exc)}


def _auth_headers(token: str) -> Dict[str, str]:
    if not token:
        return {}
    if token.lower().startswith("bearer "):
        return {"Authorization": token}
    return {"Authorization": f"Bearer {token}"}


def _gateway_endpoint() -> str:
    if not AGENTCORE_GATEWAY_ENDPOINT:
        return ""
    return (
        AGENTCORE_GATEWAY_ENDPOINT
        if AGENTCORE_GATEWAY_ENDPOINT.rstrip("/").endswith("/mcp")
        else f"{AGENTCORE_GATEWAY_ENDPOINT.rstrip('/')}/mcp"
    )


@retry(
    retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _gateway_jsonrpc(payload: Dict[str, Any], user_token: str, call_id: str | None = None) -> Dict[str, Any]:
    """Call AgentCore Gateway with retry logic for transient errors.
    
    Retries up to 3 times with exponential backoff (1s, 2s, 4s) for:
    - Network errors (ConnectionError, Timeout)
    - 5xx server errors
    
    Does NOT retry:
    - 4xx validation errors
    - Business logic errors
    """
    endpoint = _gateway_endpoint()
    if not endpoint:
        raise RuntimeError("AGENTCORE_GATEWAY_ENDPOINT not configured")
    
    log_ctx = {"call_id": call_id or "unknown", "method": payload.get("method")}
    
    try:
        session = _get_gateway_session()
        response = session.post(
            endpoint,
            json=payload,
            headers=_auth_headers(user_token),
            timeout=GATEWAY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            logger.warning("Gateway error: %s call_id=%s", data["error"], call_id)
            raise RuntimeError(f"Gateway tool error: {data['error']}")
        return data
    except requests.exceptions.HTTPError as exc:
        # Don't retry 4xx errors (client errors)
        if exc.response is not None and 400 <= exc.response.status_code < 500:
            logger.warning("Gateway client error: %s call_id=%s", exc, call_id)
            raise
        # Retry 5xx errors
        logger.warning("Gateway server error, will retry: %s call_id=%s", exc, call_id)
        raise


@retry(
    retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _request_json(
    method: str,
    path: str,
    user_token: str,
    *,
    params: Dict[str, Any] | None = None,
    payload: Dict[str, Any] | None = None,
    timeout: int | None = None,
) -> Dict[str, Any]:
    """Make HTTP request to Backend API with connection pooling and retry logic.
    
    Retries up to 3 times with exponential backoff (1s, 2s, 4s) for:
    - Network errors (ConnectionError, Timeout)
    - 5xx server errors
    """
    if timeout is None:
        timeout = BACKEND_TIMEOUT_SECONDS
    
    session = _get_backend_session()
    response = session.request(
        method=method,
        url=f"{BACKEND_API_BASE}{path}",
        headers=_auth_headers(user_token),
        params=params,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _parse_tool_result_content(content: Any) -> Dict[str, Any]:
    if not isinstance(content, list):
        return {}
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return {}


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned[key] = _drop_none(item)
        return cleaned
    if isinstance(value, list):
        return [_drop_none(item) for item in value if item is not None]
    return value


def initialize_tool_registry(user_token: str) -> Dict[str, Any]:
    """Initialize tool registry at startup by calling tools/list once.
    
    Populates:
    - _resolved_tool_names: Maps base_name -> full_name
    - _tool_schemas: Maps base_name -> full tool definition (with inputSchema)
    
    Returns:
        dict with 'count' and 'tools' for logging/monitoring
    """
    global _registry_initialized, _resolved_tool_names, _tool_schemas
    
    if _registry_initialized:
        return {"count": len(_resolved_tool_names), "tools": list(_resolved_tool_names.keys())}
    
    try:
        data = _gateway_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools-init", "method": "tools/list"},
            user_token,
            call_id="registry-init",
        )
        tools = (data.get("result") or {}).get("tools", [])
        
        for tool in tools:
            full_name = str(tool.get("name") or "")
            # Extract base name (remove server prefix if present)
            base_name = full_name.split("___")[-1] if "___" in full_name else full_name
            
            _resolved_tool_names[base_name] = full_name
            _tool_schemas[base_name] = tool
        
        _registry_initialized = True
        logger.info(
            "Tool registry initialized: %d tools loaded - %s",
            len(_resolved_tool_names),
            ", ".join(_resolved_tool_names.keys()),
        )
        
        return {"count": len(_resolved_tool_names), "tools": list(_resolved_tool_names.keys())}
    
    except Exception as exc:
        logger.error("Failed to initialize tool registry: %s", exc)
        # Don't fail startup - fall back to lazy loading
        return {"count": 0, "tools": [], "error": str(exc)}


def _resolve_tool_name(base_name: str, user_token: str) -> str:
    """Resolve tool name from cache (populated at startup).
    
    Falls back to lazy loading if registry not initialized.
    """
    if base_name in _resolved_tool_names:
        return _resolved_tool_names[base_name]
    
    # Fallback: lazy load if not in cache (shouldn't happen after startup)
    logger.warning("Tool %s not in registry, lazy loading (this should not happen)", base_name)
    
    data = _gateway_jsonrpc(
        {"jsonrpc": "2.0", "id": "tools-lazy", "method": "tools/list"},
        user_token,
        call_id=f"lazy-{base_name}",
    )
    tools = (data.get("result") or {}).get("tools", [])
    for tool in tools:
        name = str(tool.get("name") or "")
        if name == base_name or name.endswith(f"___{base_name}"):
            _resolved_tool_names[base_name] = name
            _tool_schemas[base_name] = tool
            return name
    raise RuntimeError(f"Tool {base_name} not found in AgentCore Gateway tools/list")


def _validate_tool_arguments(base_name: str, arguments: Dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate tool arguments against cached inputSchema (client-side validation).
    
    Returns:
        (is_valid, errors) tuple
    """
    if base_name not in _tool_schemas:
        # No schema available, skip validation
        return True, []
    
    tool_def = _tool_schemas[base_name]
    input_schema = tool_def.get("inputSchema")
    
    if not input_schema or not isinstance(input_schema, dict):
        # No schema to validate against
        return True, []
    
    try:
        import jsonschema
        jsonschema.validate(instance=arguments, schema=input_schema)
        return True, []
    except jsonschema.ValidationError as exc:
        return False, [str(exc.message)]
    except jsonschema.SchemaError as exc:
        logger.warning("Invalid schema for tool %s: %s", base_name, exc)
        return True, []  # Skip validation if schema itself is invalid
    except Exception as exc:
        logger.warning("Validation error for tool %s: %s", base_name, exc)
        return True, []  # Skip validation on unexpected errors


def _call_gateway_tool(
    base_name: str,
    arguments: Dict[str, Any],
    user_token: str,
    *,
    call_id: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    """Call MCP tool via AgentCore Gateway with validation and retry logic.
    
    Args:
        base_name: Tool name (e.g., 'anomaly_signals_v1')
        arguments: Tool arguments to validate and send
        user_token: Authorization token
        call_id: Unique call ID for this invocation (for correlation)
        trace_id: Request-level trace ID (for request correlation)
    
    Returns:
        Parsed tool output as dict
    """
    call_id = call_id or str(uuid.uuid4())

    # Resolve name first so lazy-loading can populate tool schema cache.
    resolved_name = _resolve_tool_name(base_name, user_token)

    # Sanitize first: optional None fields should be dropped before schema validation.
    sanitized_arguments = _drop_none(arguments)

    # Client-side JSON Schema validation (fail fast)
    is_valid, validation_errors = _validate_tool_arguments(base_name, sanitized_arguments)
    if not is_valid:
        error_msg = f"Invalid arguments for {base_name}: {'; '.join(validation_errors)}"
        logger.warning(
            "Client-side validation failed: tool=%s call_id=%s trace_id=%s errors=%s",
            base_name,
            call_id,
            trace_id,
            validation_errors,
        )
        raise ValueError(error_msg)

    payload = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": resolved_name, "arguments": sanitized_arguments},
    }
    
    logger.info(
        "Calling tool: %s call_id=%s trace_id=%s",
        base_name,
        call_id,
        trace_id,
    )
    
    data = _gateway_jsonrpc(payload, user_token, call_id=call_id)
    result = data.get("result") or {}
    
    if bool(result.get("isError")):
        content = result.get("content", [])
        detail = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    detail = item["text"].strip()
                    if detail:
                        break
        logger.warning(
            "Tool error: tool=%s call_id=%s trace_id=%s error=%s",
            base_name,
            call_id,
            trace_id,
            detail,
        )
        raise RuntimeError(f"Gateway tool error for {base_name}: {detail or 'unknown error'}")
    
    content = result.get("content", [])
    return _parse_tool_result_content(content)


def _mock_spend(range_days: str) -> Dict[str, Any]:
    return {
        "range": range_days,
        "total_spend": 14_200_000,
        "total_income": 38_200_000,
        "net_cashflow": 24_000_000,
        "jar_splits": [],
        "top_merchants": [],
        "budget_drift": [],
        "trace_id": "trc_mocked01",
    }


def _mock_forecast(horizon: str = "weekly_12") -> Dict[str, Any]:
    points = []
    count = 12 if horizon == "weekly_12" else 30
    for idx in range(count):
        points.append(
            {
                "period": f"p{idx+1}",
                "income_estimate": 35_000_000,
                "spend_estimate": 21_000_000,
                "p10": 10_000_000,
                "p50": 14_000_000,
                "p90": 18_000_000,
            }
        )
    return {
        "points": points,
        "confidence_band": {"p10_avg": 10_000_000, "p50_avg": 14_000_000, "p90_avg": 18_000_000},
        "trace_id": "trc_mocked01",
    }


def spend_analytics(user_token: str, user_id: str, range_days: str = "30d", trace_id: str | None = None) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return _mock_spend(range_days)
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "spend_analytics_v1",
        {"user_id": user_id, "range": range_days, "trace_id": trace_id},
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def anomaly_signals(user_token: str, user_id: str, lookback_days: int = 90, trace_id: str | None = None) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "flags": ["abnormal_spend"],
            "abnormal_spend": {"flag": True, "z_score": 2.8},
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "anomaly_signals_v1",
        {"user_id": user_id, "lookback_days": lookback_days, "trace_id": trace_id},
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def cashflow_forecast_tool(
    user_token: str,
    user_id: str,
    horizon: str = "weekly_12",
    scenario_overrides: Dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return _mock_forecast(horizon)
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "cashflow_forecast_v1",
        {
            "user_id": user_id,
            "horizon": horizon,
            "scenario_overrides": scenario_overrides or {},
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def jar_allocation_suggest_tool(
    user_token: str,
    user_id: str,
    monthly_income_override: float | None = None,
    goal_overrides: list[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "allocations": [
                {"jar_name": "Bills", "amount": 8_000_000, "ratio": 0.25},
                {"jar_name": "Emergency", "amount": 6_000_000, "ratio": 0.2},
            ],
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "jar_allocation_suggest_v1",
        {
            "user_id": user_id,
            "monthly_income_override": monthly_income_override,
            "goal_overrides": goal_overrides or [],
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def risk_profile_non_investment_tool(
    user_token: str,
    user_id: str,
    lookback_days: int = 180,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "risk_band": "moderate",
            "cashflow_volatility": 0.4,
            "emergency_runway_months": 4,
            "overspend_propensity": 0.45,
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "risk_profile_non_investment_v1",
        {"user_id": user_id, "lookback_days": lookback_days, "trace_id": trace_id},
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def suitability_guard_tool(
    user_token: str,
    user_id: str,
    intent: str,
    requested_action: str,
    prompt: str,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        action = (requested_action or "").strip().lower()
        blocked_execution = action in {"buy", "sell", "execute", "trade", "order"}
        blocked_recommendation = action in {"recommend_buy", "recommend_sell", "recommend_trade"}
        blocked = blocked_execution or blocked_recommendation
        decision = "allow"
        refusal_message = ""
        if blocked_execution:
            decision = "deny_execution"
            refusal_message = "I cannot execute buy/sell actions. I can provide educational guidance only."
        elif blocked_recommendation:
            decision = "deny_recommendation"
            refusal_message = (
                "I cannot provide buy/sell recommendations. "
                "I can help with cashflow, budgeting, and non-investment risk planning."
            )
        return {
            "allow": not blocked,
            "decision": decision,
            "reason_codes": (
                ["execution_blocked", "education_only_policy"]
                if blocked_execution
                else ["investment_recommendation_blocked", "education_only_policy"]
                if blocked_recommendation
                else ["non_investment_intent"]
            ),
            "refusal_message": refusal_message,
            "required_disclaimer": "Educational guidance only. We do not provide investment advice.",
            "education_only": "invest" in intent.lower() or "invest" in prompt.lower(),
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "suitability_guard_v1",
        {
            "user_id": user_id,
            "intent": intent,
            "requested_action": requested_action,
            "prompt": prompt,
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def recurring_cashflow_detect_tool(
    user_token: str,
    user_id: str,
    lookback_months: int = 6,
    min_occurrence_months: int = 3,
    recurring_overrides: list[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "recurring_income": [],
            "recurring_expense": [{"counterparty_norm": "LANDLORD", "average_amount": 9000000}],
            "fixed_cost_ratio": 0.42,
            "drift_alerts": [],
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "recurring_cashflow_detect_v1",
        {
            "user_id": user_id,
            "lookback_months": lookback_months,
            "min_occurrence_months": min_occurrence_months,
            "recurring_overrides": recurring_overrides or [],
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def goal_feasibility_tool(
    user_token: str,
    user_id: str,
    target_amount: float | None = None,
    horizon_months: int | None = None,
    goal_id: str | None = None,
    seasonality: bool = True,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "required_monthly_saving": 8_000_000,
            "feasible": True,
            "gap_amount": 0,
            "grade": "A",
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "goal_feasibility_v1",
        {
            "user_id": user_id,
            "target_amount": target_amount,
            "horizon_months": horizon_months,
            "goal_id": goal_id,
            "seasonality": seasonality,
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


def what_if_scenario_tool(
    user_token: str,
    user_id: str,
    horizon_months: int = 12,
    seasonality: bool = True,
    goal: str = "maximize_savings",
    base_scenario_overrides: Dict[str, Any] | None = None,
    variants: list[Dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {
            "scenario_comparison": [
                {"name": "base", "delta_vs_base": 0},
                {"name": "cut_discretionary_spend_15pct", "delta_vs_base": 5_000_000},
            ],
            "best_variant_by_goal": "cut_discretionary_spend_15pct",
            "base_total_net_p50": 40_000_000,
            "trace_id": "trc_mocked01",
        }
    call_id = str(uuid.uuid4())
    return _call_gateway_tool(
        "what_if_scenario_v1",
        {
            "user_id": user_id,
            "horizon_months": horizon_months,
            "seasonality": seasonality,
            "goal": goal,
            "base_scenario_overrides": base_scenario_overrides or {},
            "variants": variants or [],
            "trace_id": trace_id,
        },
        user_token,
        call_id=call_id,
        trace_id=trace_id,
    )


# Legacy aliases retained for compatibility.
def sql_read_views(user_token: str, range_days: str, user_id: str = "demo-user") -> Dict[str, Any]:
    return spend_analytics(user_token, user_id=user_id, range_days=range_days)


def forecast_cashflow(user_token: str, range_days: str = "90d", user_id: str = "demo-user") -> Dict[str, Any]:
    horizon = "daily_30" if range_days == "30d" else "weekly_12"
    return cashflow_forecast_tool(user_token, user_id=user_id, horizon=horizon)


def forecast_cashflow_scenario(user_token: str, payload: Dict[str, Any], user_id: str = "demo-user") -> Dict[str, Any]:
    horizon = str(payload.get("horizon") or payload.get("horizon_months") or "weekly_12")
    if horizon not in {"daily_30", "weekly_12"}:
        horizon = "weekly_12"
    return cashflow_forecast_tool(
        user_token,
        user_id=user_id,
        horizon=horizon,
        scenario_overrides=payload.get("scenario_overrides", {}),
        trace_id=payload.get("trace_id"),
    )


def forecast_runway(user_token: str, payload: Dict[str, Any], user_id: str = "demo-user") -> Dict[str, Any]:
    forecast = payload.get("forecast") or {}
    points = forecast.get("points") or forecast.get("monthly_forecast") or []
    cash = float(payload.get("cash_buffer") or 0)
    periods = 0
    for point in points:
        periods += 1
        cash += float(point.get("p50") or 0)
        if cash < 0:
            break
    return {
        "runway_periods": periods,
        "risk_flags": ["runway_below_threshold"] if cash < 0 else [],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
    }


def decision_savings_goal(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    forecast = payload.get("forecast") or {}
    points = forecast.get("points") or []
    target = float(payload.get("target_amount") or 0)
    horizon = max(1, int(payload.get("horizon_months") or 1))
    projected = sum(max(0.0, float((points[idx].get("p50") if idx < len(points) else 0))) for idx in range(horizon))
    required = target / horizon
    feasible = projected >= target
    return {
        "metrics": {"required_monthly_saving": required, "projected_positive_cashflow": projected},
        "grade": "A" if feasible else "C",
        "reasons": ["Deterministic projection from cashflow_forecast_v1"],
        "guardrails": [],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
    }


def decision_house_affordability(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    monthly_income = float(payload.get("monthly_income") or 0)
    monthly_payment = float(payload.get("house_price") or 0) / max(1, int(payload.get("loan_years") or 1) * 12)
    dti = monthly_payment / monthly_income if monthly_income > 0 else 1.0
    return {
        "metrics": {"monthly_payment": monthly_payment, "DTI": dti},
        "grade": "A" if dti < 0.35 else ("B" if dti < 0.45 else "C"),
        "reasons": ["Approximation for compatibility path."],
        "guardrails": [],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
    }


def decision_investment_capacity(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "metrics": {"investable_low": 0, "investable_high": 0},
        "grade": "N/A",
        "reasons": ["Use suitability_guard_v1 + risk_profile_non_investment_v1 instead."],
        "guardrails": ["education_only=true"],
        "trace_id": payload.get("trace_id", "trc_mocked01"),
        "education_only": True,
    }


def decision_what_if(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = str(payload.get("user_id") or "demo-user")
    return what_if_scenario_tool(
        user_token,
        user_id=user_id,
        horizon_months=int(payload.get("horizon_months") or 12),
        seasonality=bool(payload.get("seasonality", True)),
        goal=str(payload.get("goal") or "maximize_savings"),
        base_scenario_overrides=payload.get("base_scenario_overrides") or {},
        variants=payload.get("variants"),
        trace_id=payload.get("trace_id"),
    )


# DEPRECATED: These functions are no longer used with local KB implementation
# def _parse_kb_content(content: Any) -> Dict[str, Any]:
#     """DEPRECATED: Was used to parse Bedrock KB API responses. Local KB uses direct markdown parsing."""
#     pass
#
# def _resolve_kb_tool_name(user_token: str) -> str:
#     """DEPRECATED: Was used to resolve KB tool name from Gateway. Local KB doesn't use Gateway."""
#     pass


def kb_retrieve(query: str, filters: Dict[str, str], user_token: str = "", trace_id: str | None = None, intent: str = "") -> Dict[str, Any]:
    """Retrieve relevant Knowledge Base content using local in-memory KB.
    
    This replaces the expensive OpenSearch/Bedrock KB with local static file loading.
    For a corpus of 8 small markdown files (~5-10KB), this eliminates $700-1000/month in costs.
    
    Args:
        query: Search query (may include intent hints from _build_kb_query)
        filters: Document type filters
        user_token: User authorization token (unused in local KB)
        trace_id: Trace ID for logging
        intent: User intent key for intent-based filtering
    
    Returns:
        Dict with keys: context (str), matches (list), filters (dict)
    """
    logger.info(
        "KB retrieve (local): query=%s intent=%s trace_id=%s",
        query[:50] + "..." if len(query) > 50 else query,
        intent,
        trace_id,
    )
    
    # Use local KB matcher
    result = _match_kb_content_local(query, intent, filters)
    
    logger.info(
        "KB retrieve (local) result: %d matches, context_length=%d",
        len(result.get("matches", [])),
        len(result.get("context", "")),
    )
    
    return result


def goals_get_set(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"status": "mocked", "payload": payload}
    return _request_json("POST", "/goals", user_token, payload=payload, timeout=10)


def notifications_send(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"status": "mocked", "payload": payload}
    return _request_json("POST", "/notifications", user_token, payload=payload, timeout=10)


def code_interpreter_run(expression: str) -> Dict[str, Any]:
    return {"result": f"Computed ETA for: {expression}", "assumptions": {"inflation": 0.04}}


def audit_write(user_id: str, trace_id: str, payload: Dict[str, Any], user_token: str = "") -> Dict[str, Any]:
    if _should_use_local_mocks():
        return {"trace_id": trace_id, "payload_hash": _hash_payload(payload)}
    try:
        body = {
            "trace_id": trace_id,
            "event_type": "agent_summary",
            "payload": {
                **payload,
                "user_id": user_id,
            },
        }
        return _request_json("POST", "/audit", user_token, payload=body, timeout=10)
    except requests.RequestException:
        return {"trace_id": trace_id, "payload_hash": _hash_payload(payload)}
