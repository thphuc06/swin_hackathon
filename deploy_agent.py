from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


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
    gateway_endpoint = _normalize_gateway_endpoint(
        os.getenv(
            "DEPLOY_AGENTCORE_GATEWAY_ENDPOINT",
            "https://jars-gw-afejhtqoqd.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        )
    )
    backend_raw = os.getenv("DEPLOY_BACKEND_API_BASE", "")
    skip_backend_base_check = _env_bool("DEPLOY_SKIP_BACKEND_API_BASE_CHECK", False)
    if skip_backend_base_check:
        backend_api_base = (backend_raw or "http://localhost:8010").strip().rstrip("/")
        if not backend_api_base.startswith(("http://", "https://")):
            raise ValueError("DEPLOY_BACKEND_API_BASE must start with http:// or https://")
    else:
        backend_api_base = _ensure_backend_base(backend_raw)
    model_id = os.getenv("DEPLOY_BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0").strip()
    return {
        "AWS_REGION": os.getenv("DEPLOY_AWS_REGION", "us-east-1").strip() or "us-east-1",
        "BEDROCK_MODEL_ID": model_id,
        "BEDROCK_GUARDRAIL_ID": os.getenv(
            "DEPLOY_BEDROCK_GUARDRAIL_ID",
            "arn:aws:bedrock:us-east-1:021862553142:guardrail-profile/us.guardrail.v1:0",
        ).strip(),
        "BEDROCK_GUARDRAIL_VERSION": os.getenv("DEPLOY_BEDROCK_GUARDRAIL_VERSION", "DRAFT").strip() or "DRAFT",
        "BEDROCK_KB_ID": os.getenv("DEPLOY_BEDROCK_KB_ID", "G6GLWTUKEL").strip(),
        "BEDROCK_KB_DATASOURCE_ID": os.getenv("DEPLOY_BEDROCK_KB_DATASOURCE_ID", "WTYVWINQP9").strip(),
        "AGENTCORE_GATEWAY_ENDPOINT": gateway_endpoint,
        "BACKEND_API_BASE": backend_api_base,
        "USE_LOCAL_MOCKS": "false",
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


def deploy() -> None:
    _sync_kb_assets()
    env_vars = _build_env_vars()

    print("Effective deploy env summary:")
    for key in sorted(env_vars.keys()):
        print(f"- {key}={_mask_value(key, env_vars[key])}")

    cmd = ["agentcore", "deploy", "--auto-update-on-conflict"]
    for key, val in env_vars.items():
        cmd.extend(["--env", f"{key}={val}"])

    process_env = os.environ.copy()
    process_env["PYTHONIOENCODING"] = "utf-8"

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
    try:
        deploy()
    except Exception as exc:
        print(f"Deployment failed: {exc}")
        sys.exit(1)
