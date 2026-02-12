import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)


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


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
BEDROCK_GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID", "")
BEDROCK_GUARDRAIL_VERSION = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")

# DEPRECATED: KB now loaded locally from kb/ folder to eliminate $700-1000/month OpenSearch cost
# BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID", "")
BEDROCK_KB_ID = ""  # Unused - local KB implementation

AGENTCORE_GATEWAY_ENDPOINT = os.getenv("AGENTCORE_GATEWAY_ENDPOINT", "")
AGENTCORE_GATEWAY_TOOL_NAME = os.getenv("AGENTCORE_GATEWAY_TOOL_NAME", "")
AGENTCORE_MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "")

BACKEND_API_BASE = os.getenv("BACKEND_API_BASE", "http://localhost:8010")
USE_LOCAL_MOCKS = _env_bool("USE_LOCAL_MOCKS", False)
ROUTER_MODE = os.getenv("ROUTER_MODE", "semantic_enforce").strip().lower()
if ROUTER_MODE not in {"rule", "semantic_shadow", "semantic_enforce"}:
    ROUTER_MODE = "semantic_enforce"
ROUTER_POLICY_VERSION = os.getenv("ROUTER_POLICY_VERSION", "v1")
ROUTER_INTENT_CONF_MIN = _env_float("ROUTER_INTENT_CONF_MIN", 0.70)
ROUTER_TOP2_GAP_MIN = _env_float("ROUTER_TOP2_GAP_MIN", 0.15)
ROUTER_SCENARIO_CONF_MIN = _env_float("ROUTER_SCENARIO_CONF_MIN", 0.75)
ROUTER_MAX_CLARIFY_QUESTIONS = max(1, _env_int("ROUTER_MAX_CLARIFY_QUESTIONS", 2))
RESPONSE_MODE = os.getenv("RESPONSE_MODE", "llm_shadow").strip().lower()
if RESPONSE_MODE not in {"template", "llm_shadow", "llm_enforce"}:
    RESPONSE_MODE = "llm_shadow"
RESPONSE_PROMPT_VERSION = os.getenv("RESPONSE_PROMPT_VERSION", "answer_synth_v2")
RESPONSE_SCHEMA_VERSION = os.getenv("RESPONSE_SCHEMA_VERSION", "answer_plan_v2")
RESPONSE_POLICY_VERSION = os.getenv("RESPONSE_POLICY_VERSION", "advice_policy_v1")
RESPONSE_MAX_RETRIES = max(0, _env_int("RESPONSE_MAX_RETRIES", 0))

# Dynamic service matcher
SERVICE_MATCHER_MODE = os.getenv("SERVICE_MATCHER_MODE", "dynamic_v2").strip().lower()
if SERVICE_MATCHER_MODE not in {"static", "dynamic", "dynamic_v2"}:
    SERVICE_MATCHER_MODE = "dynamic_v2"
SERVICE_CATALOG_TTL_SECONDS = max(30, _env_int("SERVICE_CATALOG_TTL_SECONDS", 300))
SERVICE_MATCH_TOP_K = max(1, _env_int("SERVICE_MATCH_TOP_K", 3))
SERVICE_MATCH_MIN_SCORE = _env_float("SERVICE_MATCH_MIN_SCORE", 0.58)
SERVICE_CATALOG_STRICT_VALIDATION = _env_bool("SERVICE_CATALOG_STRICT_VALIDATION", True)
SERVICE_CATALOG_FORCE_RELOAD = _env_bool("SERVICE_CATALOG_FORCE_RELOAD", False)
SERVICE_SIGNAL_REQUIRED_STRICT = _env_bool("SERVICE_SIGNAL_REQUIRED_STRICT", True)
SERVICE_CLARIFY_MARGIN_MIN = _env_float("SERVICE_CLARIFY_MARGIN_MIN", 0.08)

# Context signal thresholds
SERVICE_SIGNAL_OVESPEND_HIGH = _env_float("SERVICE_SIGNAL_OVESPEND_HIGH", 0.35)
SERVICE_SIGNAL_RUNWAY_LOW_MONTHS = _env_float("SERVICE_SIGNAL_RUNWAY_LOW_MONTHS", 3.0)
SERVICE_SIGNAL_VOLATILITY_HIGH = _env_float("SERVICE_SIGNAL_VOLATILITY_HIGH", 0.35)
SERVICE_SIGNAL_GOAL_GAP_HIGH_AMOUNT = _env_float("SERVICE_SIGNAL_GOAL_GAP_HIGH_AMOUNT", 0.0)
SERVICE_SIGNAL_ANOMALY_RECENT_MIN_FLAGS = max(1, _env_int("SERVICE_SIGNAL_ANOMALY_RECENT_MIN_FLAGS", 1))

# Hybrid semantic retrieval
SERVICE_EMBED_ENABLED = _env_bool("SERVICE_EMBED_ENABLED", True)
SERVICE_EMBED_MODEL_ID = os.getenv("SERVICE_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0").strip()
SERVICE_EMBED_TOP_N = max(1, _env_int("SERVICE_EMBED_TOP_N", 8))

ENCODING_GATE_ENABLED = _env_bool("ENCODING_GATE_ENABLED", True)
ENCODING_REPAIR_ENABLED = _env_bool("ENCODING_REPAIR_ENABLED", True)
ENCODING_REPAIR_SCORE_MIN = _env_float("ENCODING_REPAIR_SCORE_MIN", 0.12)
ENCODING_FAILFAST_SCORE_MIN = _env_float("ENCODING_FAILFAST_SCORE_MIN", 0.45)
ENCODING_REPAIR_MIN_DELTA = _env_float("ENCODING_REPAIR_MIN_DELTA", 0.10)
ENCODING_NORMALIZATION_FORM = os.getenv("ENCODING_NORMALIZATION_FORM", "NFC").strip().upper() or "NFC"
if ENCODING_NORMALIZATION_FORM not in {"NFC", "NFD", "NFKC", "NFKD"}:
    ENCODING_NORMALIZATION_FORM = "NFC"

# ============================================================================
# TIMEOUT CONFIGURATION (Centralized)
# ============================================================================
# Agent execution timeouts
AGENT_TIMEOUT_SECONDS = _env_int("AGENT_TIMEOUT_SECONDS", 120)
GATEWAY_TIMEOUT_SECONDS = _env_int("GATEWAY_TIMEOUT_SECONDS", 25)
BACKEND_TIMEOUT_SECONDS = _env_int("BACKEND_TIMEOUT_SECONDS", 20)

# Bedrock client timeouts
BEDROCK_CONNECT_TIMEOUT = _env_int("BEDROCK_CONNECT_TIMEOUT", 10)
BEDROCK_READ_TIMEOUT = _env_int("BEDROCK_READ_TIMEOUT", 120)  # Increased from 60s for large Vietnamese responses

# Tool execution timeouts
TOOL_EXECUTION_TIMEOUT = _env_int("TOOL_EXECUTION_TIMEOUT", 120)  # ThreadPoolExecutor global timeout

# Connection pooling configuration
HTTP_POOL_CONNECTIONS = _env_int("HTTP_POOL_CONNECTIONS", 10)  # Number of connection pools to cache
HTTP_POOL_MAXSIZE = _env_int("HTTP_POOL_MAXSIZE", 20)  # Max connections per pool
HTTP_POOL_BLOCK = _env_bool("HTTP_POOL_BLOCK", False)  # Block when pool is full
