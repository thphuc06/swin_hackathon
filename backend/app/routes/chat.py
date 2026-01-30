from __future__ import annotations

import os
import uuid
from typing import Generator, Optional

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.auth import current_user

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    prompt: str


def _stream_local(prompt: str) -> Generator[str, None, None]:
    yield f"data: Simulated advisory for: {prompt}\n\n"
    yield "data: Disclaimer: Educational guidance only.\n\n"
    yield f"data: Trace: trc_{uuid.uuid4().hex[:8]}\n\n"


def _invoke_agentcore(prompt: str, bearer_token: Optional[str]) -> Generator[str, None, None]:
    agent_arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    region = os.getenv("AWS_REGION", "us-east-1")
    if agent_arn:
        try:
            escaped_arn = requests.utils.quote(agent_arn, safe="")
            url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped_arn}/invocations"
            headers = {
                "Content-Type": "application/json",
                "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()),
            }
            if bearer_token:
                headers["Authorization"] = bearer_token

            response = requests.post(
                url,
                params={"qualifier": "DEFAULT"},
                headers=headers,
                json={"prompt": prompt},
                timeout=100,
                stream=True,
            )
            if response.status_code >= 400:
                snippet = response.text[:500]
                yield f"data: Error: AgentCore returned {response.status_code} {response.reason}\n\n"
                if snippet:
                    yield f"data: Details: {snippet}\n\n"
                return

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                payload = response.json()
                result = payload.get("result") or payload.get("response", "")
                trace_id = payload.get("trace_id", "")
                citations = payload.get("citations", [])
                disclaimer = payload.get("disclaimer", "")
                yield f"data: {result}\n\n"
                if trace_id:
                    yield f"data: Trace: {trace_id}\n\n"
                if citations:
                    cite_text = ", ".join([c.get("citation", "") for c in citations])
                    yield f"data: Citations: {cite_text}\n\n"
                if disclaimer:
                    yield f"data: Disclaimer: {disclaimer}\n\n"
                return

            for line in response.iter_lines(chunk_size=1):
                if line:
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data:"):
                        yield decoded + "\n"
            return
        except requests.RequestException as exc:
            yield f"data: Error: AgentCore request failed: {exc}\n\n"
            return

    # Fallback to local agentcore app for MVP streaming
    local_url = os.getenv("AGENTCORE_LOCAL_URL", "http://localhost:8080/invocations")
    try:
        response = requests.post(
            local_url,
            headers={"Content-Type": "application/json"},
            json={"prompt": prompt},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        yield f"data: {payload.get('result', '')}\n\n"
        yield f"data: Trace: {payload.get('trace_id', '')}\n\n"
        citations = payload.get("citations", [])
        if citations:
            cite_text = ", ".join([c.get("citation", "") for c in citations])
            yield f"data: Citations: {cite_text}\n\n"
        yield f"data: Disclaimer: {payload.get('disclaimer', '')}\n\n"
    except requests.RequestException as exc:
        yield f"data: Error: Local agentcore request failed: {exc}\n\n"


@router.post("/stream")
def stream_chat(
    payload: ChatRequest,
    user=Depends(current_user),
    authorization: Optional[str] = Header(None),
):
    agent_arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    if agent_arn and not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for AgentCore Runtime (JWT required).",
        )
    return StreamingResponse(
        _invoke_agentcore(payload.prompt, authorization),
        media_type="text/event-stream",
    )
