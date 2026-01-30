from __future__ import annotations

import os
from typing import Any, Dict

from bedrock_agentcore import BedrockAgentCoreApp
from dotenv import load_dotenv

from graph import run_agent

load_dotenv()
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    prompt = payload.get("prompt", "")
    user_token = payload.get("authorization", os.getenv("DEFAULT_USER_TOKEN", ""))
    user_id = payload.get("user_id", "demo-user")
    result = run_agent(prompt=prompt, user_token=user_token, user_id=user_id)
    return {
        "result": result["response"],
        "trace_id": result["trace_id"],
        "citations": result["citations"].get("matches", []),
        "disclaimer": "Educational guidance only. We do not provide investment advice.",
    }


if __name__ == "__main__":
    app.run()
