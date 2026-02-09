import os
from dotenv import load_dotenv

load_dotenv()


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
BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID", "")

AGENTCORE_GATEWAY_ENDPOINT = os.getenv("AGENTCORE_GATEWAY_ENDPOINT", "")
AGENTCORE_GATEWAY_TOOL_NAME = os.getenv("AGENTCORE_GATEWAY_TOOL_NAME", "")
AGENTCORE_MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "")

BACKEND_API_BASE = os.getenv("BACKEND_API_BASE", "http://localhost:8000")
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
RESPONSE_MAX_RETRIES = max(0, _env_int("RESPONSE_MAX_RETRIES", 1))

ENCODING_GATE_ENABLED = _env_bool("ENCODING_GATE_ENABLED", True)
ENCODING_REPAIR_ENABLED = _env_bool("ENCODING_REPAIR_ENABLED", True)
ENCODING_REPAIR_SCORE_MIN = _env_float("ENCODING_REPAIR_SCORE_MIN", 0.12)
ENCODING_FAILFAST_SCORE_MIN = _env_float("ENCODING_FAILFAST_SCORE_MIN", 0.45)
ENCODING_REPAIR_MIN_DELTA = _env_float("ENCODING_REPAIR_MIN_DELTA", 0.10)
ENCODING_NORMALIZATION_FORM = os.getenv("ENCODING_NORMALIZATION_FORM", "NFC").strip().upper() or "NFC"
if ENCODING_NORMALIZATION_FORM not in {"NFC", "NFD", "NFKC", "NFKD"}:
    ENCODING_NORMALIZATION_FORM = "NFC"
