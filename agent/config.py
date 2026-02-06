import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
BEDROCK_GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID", "")
BEDROCK_GUARDRAIL_VERSION = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID", "")

AGENTCORE_GATEWAY_ENDPOINT = os.getenv("AGENTCORE_GATEWAY_ENDPOINT", "")
AGENTCORE_GATEWAY_TOOL_NAME = os.getenv("AGENTCORE_GATEWAY_TOOL_NAME", "")
AGENTCORE_MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "")

BACKEND_API_BASE = os.getenv("BACKEND_API_BASE", "http://localhost:8000")
USE_LOCAL_MOCKS = _env_bool("USE_LOCAL_MOCKS", True)
