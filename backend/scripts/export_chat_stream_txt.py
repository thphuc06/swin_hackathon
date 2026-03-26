from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, List

import requests
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repo_env() -> None:
    for env_path in (
        REPO_ROOT / "backend" / ".env",
        REPO_ROOT / "agent" / ".env",
        REPO_ROOT / "src" / "aws-specialist-agent-mcp-server" / ".env",
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _resolve_backend_url(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_url = str(os.getenv("BACKEND_CHAT_STREAM_URL") or "").strip()
    if env_url:
        return env_url
    backend_base = str(os.getenv("BACKEND_API_BASE") or "http://localhost:8010").strip().rstrip("/")
    return f"{backend_base}/chat/stream"


def _resolve_access_token(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_token = str(os.getenv("ACCESS_TOKEN") or os.getenv("COGNITO_ACCESS_TOKEN") or "").strip()
    if env_token:
        return env_token

    gen_token_script = REPO_ROOT / "agent" / "genToken.py"
    if gen_token_script.exists():
        proc = subprocess.run(
            [sys.executable, str(gen_token_script)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        combined = "\n".join([proc.stdout, proc.stderr])
        for line in combined.splitlines():
            if line.startswith("AccessToken:"):
                token = line.split("AccessToken:", 1)[1].strip()
                if token:
                    return token
    raise RuntimeError("Could not resolve an AccessToken. Pass --access-token or configure Cognito envs for agent/genToken.py.")


def _parse_sse(raw_text: str) -> Dict[str, str]:
    assistant_lines: List[str] = []
    metadata: Dict[str, str] = {}
    metadata_prefixes = {
        "RuntimeSource:": "runtime_source",
        "ResponseMode:": "response_mode",
        "ResponseFallback:": "response_fallback",
        "ResponseReasonCodes:": "response_reason_codes",
        "Trace:": "trace_id",
        "Citations:": "citations",
        "Tools:": "tools",
        "Disclaimer:": "disclaimer",
    }
    for raw_line in raw_text.splitlines():
        line = str(raw_line or "").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        matched = False
        for prefix, key in metadata_prefixes.items():
            if payload.startswith(prefix):
                metadata[key] = payload.split(prefix, 1)[1].strip()
                matched = True
                break
        if not matched and payload:
            assistant_lines.append(payload)
    metadata["assistant_output"] = "\n".join(assistant_lines).strip()
    return metadata


def _render_output_file(
    *,
    endpoint: str,
    prompt: str,
    session_id: str,
    http_status: int,
    parsed: Dict[str, str],
    raw_sse: str,
) -> str:
    return "\n".join(
        [
            "Planner User-Facing Output",
            "",
            f"Endpoint: {endpoint}",
            f"HTTP Status: {http_status}",
            f"Session ID: {session_id}",
            f"Trace ID: {parsed.get('trace_id', '')}",
            f"Runtime Source: {parsed.get('runtime_source', '')}",
            f"Response Mode: {parsed.get('response_mode', '')}",
            f"Response Reason Codes: {parsed.get('response_reason_codes', '')}",
            f"Tools: {parsed.get('tools', '')}",
            f"Citations: {parsed.get('citations', '')}",
            f"Disclaimer: {parsed.get('disclaimer', '')}",
            "",
            "Prompt",
            prompt,
            "",
            "Assistant Output",
            parsed.get("assistant_output", ""),
            "",
            "Raw SSE Response",
            raw_sse.strip(),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Invoke backend /chat/stream and export final user-facing TXT output.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--access-token", default="")
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()

    _load_repo_env()
    endpoint = _resolve_backend_url(args.endpoint)
    access_token = _resolve_access_token(args.access_token)
    session_id = str(args.session_id or f"chat_{uuid.uuid4().hex}")

    response = requests.post(
        endpoint,
        headers={
            "Authorization": access_token if access_token.lower().startswith("bearer ") else f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Session-Id": session_id,
        },
        json={"prompt": args.prompt},
        timeout=180,
    )
    response.raise_for_status()

    raw_sse = response.text
    parsed = _parse_sse(raw_sse)
    rendered = _render_output_file(
        endpoint=endpoint,
        prompt=args.prompt,
        session_id=session_id,
        http_status=response.status_code,
        parsed=parsed,
        raw_sse=raw_sse,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
