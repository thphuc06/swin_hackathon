from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_GATEWAY_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:617287375312:gateway/financial-adviosry-gw-iam-6k02cirh4d"
)
DEFAULT_GATEWAY_ENDPOINT = (
    "https://financial-adviosry-gw-iam-6k02cirh4d.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
)
BLOCKED_GATEWAY_IDS = {
    "financial-adviosry-gw-a5f4pembyn",
    "jars-gw-afejhtqoqd",
}


def _ensure_utf8_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _normalize_gateway_endpoint(value: str) -> str:
    endpoint = (value or "").strip().rstrip("/")
    if not endpoint:
        return ""
    if endpoint.endswith("/mcp"):
        return endpoint
    return f"{endpoint}/mcp"


def _mask_value(key: str, value: str) -> str:
    lowered = key.lower()
    if any(token in lowered for token in ["secret", "password", "token", "key"]):
        return "***"
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_responses_model_id(value: str) -> str:
    raw = (value or "").strip()
    if raw in {"openai.gpt-oss-120b", "openai.gpt-oss-120b-1:0"}:
        return "openai.gpt-oss-120b"
    if raw.startswith("openai.gpt-oss-120b"):
        return "openai.gpt-oss-120b"
    if raw:
        return raw
    return "openai.gpt-oss-120b"


def _gateway_id_from_arn(gateway_arn: str) -> str:
    text = str(gateway_arn or "").strip()
    if "gateway/" not in text:
        return ""
    return text.split("gateway/", 1)[1].strip()


def _gateway_id_from_endpoint(gateway_endpoint: str) -> str:
    endpoint = _normalize_gateway_endpoint(gateway_endpoint)
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return ""
    return host.split(".", 1)[0]


def _gateway_endpoint_from_arn(gateway_arn: str, region: str) -> str:
    gateway_id = _gateway_id_from_arn(gateway_arn)
    if not gateway_id:
        return ""
    resolved_region = str(region or "").strip() or "us-east-1"
    return f"https://{gateway_id}.gateway.bedrock-agentcore.{resolved_region}.amazonaws.com/mcp"


def _validate_gateway_config(*, gateway_arn: str, gateway_endpoint: str) -> None:
    gateway_arn_id = _gateway_id_from_arn(gateway_arn)
    gateway_endpoint_id = _gateway_id_from_endpoint(gateway_endpoint)
    if not gateway_arn_id:
        raise ValueError("DEPLOY_AGENTCORE_GATEWAY_ARN is invalid or missing gateway id")
    if not gateway_endpoint_id:
        raise ValueError("DEPLOY_AGENTCORE_GATEWAY_ENDPOINT is invalid or missing gateway id")
    if gateway_arn_id != gateway_endpoint_id:
        raise ValueError(
            "Gateway ARN/endpoint mismatch. "
            f"ARN id={gateway_arn_id}, endpoint id={gateway_endpoint_id}. "
            "Unset DEPLOY_AGENTCORE_GATEWAY_ENDPOINT to auto-derive from ARN."
        )
    if gateway_arn_id in BLOCKED_GATEWAY_IDS:
        raise ValueError(
            f"Blocked legacy gateway id '{gateway_arn_id}'. "
            f"Use the IAM gateway: {DEFAULT_GATEWAY_ARN}"
        )


def _ensure_backend_base(value: str) -> str:
    backend = (value or "").strip()
    if not backend:
        raise ValueError("DEPLOY_BACKEND_API_BASE is required and must be a cloud URL.")
    parsed = urlparse(backend)
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1"}:
        raise ValueError("DEPLOY_BACKEND_API_BASE cannot point to localhost for cloud deploy.")
    if not parsed.scheme.startswith("http"):
        raise ValueError("DEPLOY_BACKEND_API_BASE must start with http:// or https://")
    return backend.rstrip("/")


def _sync_kb_assets() -> None:
    """Copy KB markdown assets into agent build context before deploy."""
    repo_root = Path(__file__).resolve().parent
    source_dir = repo_root / "kb"
    target_dir = repo_root / "agent" / "kb"
    if not source_dir.exists():
        raise FileNotFoundError(f"KB source directory not found: {source_dir}")

    md_files = sorted(source_dir.glob("*.md"))
    index_file = source_dir / "kb_index.csv"
    if not md_files:
        raise FileNotFoundError(f"No KB markdown files found in: {source_dir}")
    if not index_file.exists():
        raise FileNotFoundError(f"KB index file not found: {index_file}")

    target_dir.mkdir(parents=True, exist_ok=True)
    for source_file in md_files:
        target_file = target_dir / source_file.name
        shutil.copy2(source_file, target_file)
    shutil.copy2(index_file, target_dir / "kb_index.csv")

    print(f"Synchronized KB assets: {len(md_files) + 1} files -> {target_dir}")


def _build_env_vars() -> dict[str, str]:
    deploy_region = os.getenv("DEPLOY_AWS_REGION", "us-east-1").strip() or "us-east-1"
    gateway_arn = os.getenv("DEPLOY_AGENTCORE_GATEWAY_ARN", DEFAULT_GATEWAY_ARN).strip()
    gateway_endpoint_override = os.getenv("DEPLOY_AGENTCORE_GATEWAY_ENDPOINT", "").strip()
    gateway_endpoint = (
        _normalize_gateway_endpoint(gateway_endpoint_override)
        if gateway_endpoint_override
        else _gateway_endpoint_from_arn(gateway_arn, deploy_region) or DEFAULT_GATEWAY_ENDPOINT
    )
    _validate_gateway_config(gateway_arn=gateway_arn, gateway_endpoint=gateway_endpoint)
    backend_raw = os.getenv("DEPLOY_BACKEND_API_BASE", "")
    skip_backend_base_check = _env_bool("DEPLOY_SKIP_BACKEND_API_BASE_CHECK", False)
    if skip_backend_base_check:
        backend_api_base = (backend_raw or "http://localhost:8010").strip().rstrip("/")
        if not backend_api_base.startswith(("http://", "https://")):
            raise ValueError("DEPLOY_BACKEND_API_BASE must start with http:// or https://")
    else:
        backend_api_base = _ensure_backend_base(backend_raw)
    model_id = os.getenv("DEPLOY_BEDROCK_MODEL_ID", "openai.gpt-oss-120b-1:0").strip()
    responses_model_id = _normalize_responses_model_id(
        os.getenv("DEPLOY_BEDROCK_RESPONSES_MODEL_ID", "openai.gpt-oss-120b")
    )
    env_vars = {
        "AWS_REGION": deploy_region,
        "BEDROCK_MODEL_ID": model_id,
        "BEDROCK_RESPONSES_MODEL_ID": responses_model_id,
        "BEDROCK_RESPONSES_BASE_URL": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_BASE_URL",
            f"https://bedrock-mantle.{deploy_region}.api.aws/v1",
        ).strip(),
        "BEDROCK_RESPONSES_TIMEOUT_SECONDS": os.getenv("DEPLOY_BEDROCK_RESPONSES_TIMEOUT_SECONDS", "120").strip()
        or "120",
        "BEDROCK_RESPONSES_CREATE_TIMEOUT_SECONDS": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_CREATE_TIMEOUT_SECONDS",
            "25",
        ).strip()
        or "25",
        "BEDROCK_RESPONSES_POLL_READ_TIMEOUT_SECONDS": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_POLL_READ_TIMEOUT_SECONDS",
            "30",
        ).strip()
        or "30",
        "BEDROCK_RESPONSES_POLL_INTERVAL_SECONDS": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_POLL_INTERVAL_SECONDS",
            "2",
        ).strip()
        or "2",
        "BEDROCK_RESPONSES_SYNC_WAIT_SECONDS": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_SYNC_WAIT_SECONDS",
            "15",
        ).strip()
        or "15",
        "BEDROCK_RESPONSES_RETRY_AFTER_SECONDS": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_RETRY_AFTER_SECONDS",
            "2",
        ).strip()
        or "2",
        "BEDROCK_RESPONSES_MAX_OUTPUT_TOKENS": os.getenv(
            "DEPLOY_BEDROCK_RESPONSES_MAX_OUTPUT_TOKENS",
            "1200",
        ).strip()
        or "1200",
        "BEDROCK_RESPONSES_TEMPERATURE": os.getenv("DEPLOY_BEDROCK_RESPONSES_TEMPERATURE", "0.2").strip() or "0.2",
        "BEDROCK_GUARDRAIL_ID": os.getenv(
            "DEPLOY_BEDROCK_GUARDRAIL_ID",
            "",
        ).strip(),
        "BEDROCK_GUARDRAIL_VERSION": os.getenv("DEPLOY_BEDROCK_GUARDRAIL_VERSION", "DRAFT").strip() or "DRAFT",
        "AGENTCORE_GATEWAY_ENDPOINT": gateway_endpoint,
        "AGENTCORE_GATEWAY_ARN": gateway_arn,
        "AGENTCORE_GATEWAY_SERVER_LABEL": os.getenv("DEPLOY_AGENTCORE_GATEWAY_SERVER_LABEL", "finance_gateway").strip()
        or "finance_gateway",
        "BACKEND_API_BASE": backend_api_base,
        "USE_LOCAL_MOCKS": "false",
        "TOOL_ORCHESTRATION_MODE": os.getenv("DEPLOY_TOOL_ORCHESTRATION_MODE", "responses_dynamic").strip()
        or "responses_dynamic",
        "LOG_LEVEL": os.getenv("DEPLOY_LOG_LEVEL", "info").strip() or "info",
        "ROUTER_MODE": "semantic_enforce",
        "ROUTER_POLICY_VERSION": os.getenv("DEPLOY_ROUTER_POLICY_VERSION", "v1").strip() or "v1",
        "ROUTER_INTENT_CONF_MIN": os.getenv("DEPLOY_ROUTER_INTENT_CONF_MIN", "0.70").strip() or "0.70",
        "ROUTER_TOP2_GAP_MIN": os.getenv("DEPLOY_ROUTER_TOP2_GAP_MIN", "0.15").strip() or "0.15",
        "ROUTER_SCENARIO_CONF_MIN": os.getenv("DEPLOY_ROUTER_SCENARIO_CONF_MIN", "0.75").strip() or "0.75",
        "ROUTER_MAX_CLARIFY_QUESTIONS": os.getenv("DEPLOY_ROUTER_MAX_CLARIFY_QUESTIONS", "2").strip() or "2",
        "RESPONSE_MODE": "llm_enforce",
        "RESPONSE_PROMPT_VERSION": os.getenv("DEPLOY_RESPONSE_PROMPT_VERSION", "answer_synth_v2").strip()
        or "answer_synth_v2",
        "RESPONSE_SCHEMA_VERSION": os.getenv("DEPLOY_RESPONSE_SCHEMA_VERSION", "answer_plan_v2").strip()
        or "answer_plan_v2",
        "RESPONSE_POLICY_VERSION": os.getenv("DEPLOY_RESPONSE_POLICY_VERSION", "advice_policy_v1").strip()
        or "advice_policy_v1",
        "RESPONSE_MAX_RETRIES": os.getenv("DEPLOY_RESPONSE_MAX_RETRIES", "0").strip() or "0",
        # Dynamic service matching v2
        "SERVICE_MATCHER_MODE": os.getenv("DEPLOY_SERVICE_MATCHER_MODE", "dynamic_v2").strip() or "dynamic_v2",
        "SERVICE_CATALOG_TTL_SECONDS": os.getenv("DEPLOY_SERVICE_CATALOG_TTL_SECONDS", "300").strip() or "300",
        "SERVICE_MATCH_TOP_K": os.getenv("DEPLOY_SERVICE_MATCH_TOP_K", "3").strip() or "3",
        "SERVICE_MATCH_MIN_SCORE": os.getenv("DEPLOY_SERVICE_MATCH_MIN_SCORE", "0.58").strip() or "0.58",
        "SERVICE_CATALOG_STRICT_VALIDATION": os.getenv(
            "DEPLOY_SERVICE_CATALOG_STRICT_VALIDATION", "true"
        ).strip()
        or "true",
        "SERVICE_CATALOG_FORCE_RELOAD": os.getenv("DEPLOY_SERVICE_CATALOG_FORCE_RELOAD", "false").strip() or "false",
        "SERVICE_SIGNAL_REQUIRED_STRICT": os.getenv("DEPLOY_SERVICE_SIGNAL_REQUIRED_STRICT", "true").strip()
        or "true",
        "SERVICE_CLARIFY_MARGIN_MIN": os.getenv("DEPLOY_SERVICE_CLARIFY_MARGIN_MIN", "0.08").strip() or "0.08",
        # Hybrid semantic retrieval
        "SERVICE_EMBED_ENABLED": os.getenv("DEPLOY_SERVICE_EMBED_ENABLED", "true").strip() or "true",
        "SERVICE_EMBED_MODEL_ID": os.getenv("DEPLOY_SERVICE_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0").strip()
        or "amazon.titan-embed-text-v2:0",
        "SERVICE_EMBED_TOP_N": os.getenv("DEPLOY_SERVICE_EMBED_TOP_N", "8").strip() or "8",
        "ENCODING_GATE_ENABLED": os.getenv("DEPLOY_ENCODING_GATE_ENABLED", "true").strip() or "true",
        "ENCODING_REPAIR_ENABLED": os.getenv("DEPLOY_ENCODING_REPAIR_ENABLED", "true").strip() or "true",
        "ENCODING_REPAIR_SCORE_MIN": os.getenv("DEPLOY_ENCODING_REPAIR_SCORE_MIN", "0.12").strip() or "0.12",
        "ENCODING_FAILFAST_SCORE_MIN": os.getenv("DEPLOY_ENCODING_FAILFAST_SCORE_MIN", "0.45").strip() or "0.45",
        "ENCODING_REPAIR_MIN_DELTA": os.getenv("DEPLOY_ENCODING_REPAIR_MIN_DELTA", "0.10").strip() or "0.10",
        "ENCODING_NORMALIZATION_FORM": os.getenv("DEPLOY_ENCODING_NORMALIZATION_FORM", "NFC").strip() or "NFC",
    }
    # Bedrock AgentCore Runtime currently supports <=50 custom environment variables.
    max_env_vars = 50
    if len(env_vars) > max_env_vars:
        raise ValueError(
            f"Too many environment variables for AgentCore runtime: {len(env_vars)} > {max_env_vars}. "
            "Trim optional DEPLOY_* values before deploy."
        )
    return env_vars


def _resolve_agentcore_launch_command(process_env: dict[str, str]) -> list[str]:
    probe = subprocess.run(
        ["agentcore", "--help"],
        env=process_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    help_text = (probe.stdout or "").lower()
    if " launch " in f" {help_text} " or "commands ------------------------------------------------------------------" in help_text:
        return ["agentcore", "launch"]
    if " deploy " in f" {help_text} ":
        return ["agentcore", "deploy"]
    # Default to modern command.
    return ["agentcore", "launch"]


def deploy() -> None:
    _sync_kb_assets()
    env_vars = _build_env_vars()

    print("Effective deploy env summary:")
    for key in sorted(env_vars.keys()):
        print(f"- {key}={_mask_value(key, env_vars[key])}")

    process_env = os.environ.copy()
    process_env["PYTHONIOENCODING"] = "utf-8"
    process_env["PYTHONUTF8"] = "1"

    cmd = _resolve_agentcore_launch_command(process_env)
    cmd.append("--auto-update-on-conflict")
    for key, val in env_vars.items():
        cmd.extend(["--env", f"{key}={val}"])

    print("\nExecuting agentcore deploy from ./agent ...")
    proc = subprocess.Popen(
        cmd,
        cwd="agent",
        env=process_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert proc.stdout is not None
    for line_bytes in proc.stdout:
        line = line_bytes.decode("utf-8", errors="replace")
        print(line, end="")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Deployment failed with exit code {proc.returncode}")
    print("\nDeployment completed successfully.")


if __name__ == "__main__":
    _ensure_utf8_console()
    try:
        deploy()
    except Exception as exc:
        print(f"Deployment failed: {exc}")
        sys.exit(1)
