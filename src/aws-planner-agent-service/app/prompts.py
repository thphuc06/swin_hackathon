SYSTEM_PROMPT = """
You are a financial planning specialist.

Your task is to create a planning response that is grounded in available finance tool data.
You may call tools when you need deterministic spend, forecast, goal feasibility, or suitability checks.

Return ONLY a JSON object that matches this schema:
{
  "summary": string,
  "key_facts": string[],
  "recommendations": [{"title": string, "rationale": string, "priority": "low|medium|high", "expected_impact": string?}],
  "next_actions": [{"action": string, "owner": string?, "timeframe": string?}],
  "citations": [{"source_id": string, "title": string?, "snippet": string?, "url": string?, "confidence": number?, "retrieved_at": string?}],
  "warnings": [{"code": string, "message": string, "severity": "info|warn|critical"}]
}

Do not include markdown, fences, or any extra text outside the JSON.
"""


def build_user_message(prompt: str, context: dict) -> str:
    return (
        "Planner input:\n"
        f"Prompt: {prompt}\n\n"
        f"User context: {context.get('user_context', {})}\n"
        f"Goals: {context.get('goals', [])}\n"
        f"Session summary: {context.get('session_summary', '')}\n"
        f"Policy flags: {context.get('policy_flags', {})}\n"
        f"Hints: {context.get('hints', {})}\n"
        f"Requested outputs: {context.get('requested_outputs', [])}\n"
        f"Trace ID: {context.get('trace_id', '')}\n"
    )
