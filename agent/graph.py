from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, TypedDict

from langgraph.graph import END, StateGraph
import boto3
from dotenv import load_dotenv

from tools import (
    audit_write,
    code_interpreter_run,
    kb_retrieve,
    sql_read_views,
)


class AgentState(TypedDict):
    user_token: str
    user_id: str
    prompt: str
    intent: str
    context: Dict[str, Any]
    kb: Dict[str, Any]
    response: str
    trace_id: str


load_dotenv()

FINANCIAL_INTENTS = ["summary", "house", "largest_txn", "what_if", "risk"]


def llm_generate(prompt: str) -> str:
    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    region = os.getenv("AWS_REGION", "us-east-1")
    if not model_id:
        return ""

    client = boto3.client("bedrock-runtime", region_name=region)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 400, "temperature": 0.2},
    )
    data = response
    if not hasattr(data, "get"):
        if hasattr(data, "read"):
            data = json.loads(data.read())
        elif hasattr(data, "json"):
            data = data.json()
    return data.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")


def intent_router(state: AgentState) -> AgentState:
    prompt = state["prompt"].lower()
    if "house" in prompt or "buy" in prompt:
        state["intent"] = "house"
    elif "largest" in prompt:
        state["intent"] = "largest_txn"
    elif "60" in prompt:
        state["intent"] = "summary_60d"
    else:
        state["intent"] = "summary_30d"
    return state


def fetch_context(state: AgentState) -> AgentState:
    range_days = "60d" if "60" in state["intent"] else "30d"
    state["context"] = sql_read_views(state["user_token"], range_days)
    return state


def retrieve_kb(state: AgentState) -> AgentState:
    state["kb"] = kb_retrieve(state["prompt"], {"doc_type": "policy"})
    return state


def suitability_guard(state: AgentState) -> AgentState:
    prompt = state["prompt"].lower()
    if any(term in prompt for term in ["invest", "buy", "sell", "stock"]):
        state["intent"] = "education_only"
    return state


def what_if(state: AgentState) -> AgentState:
    if state["intent"] != "house":
        return state
    state["context"]["what_if"] = code_interpreter_run(state["prompt"])
    return state


def reasoning(state: AgentState) -> AgentState:
    citations = ", ".join([m["citation"] for m in state["kb"].get("matches", [])])
    if state["intent"] == "education_only":
        state["response"] = (
            "I can share educational guidance but cannot provide investment advice. "
            "Consider reviewing your risk profile and financial goals. "
            f"Citations: {citations}."
        )
        return state

    summary = state.get("context", {})
    prompt = (
        "You are a fintech assistant. Use the numeric context only. "
        "Do not provide investment advice. Provide concise guidance and cite KB ids.\n\n"
        f"Context: {json.dumps(summary)}\n"
        f"KB citations: {citations}\n"
        f"User question: {state['prompt']}\n"
        "Answer with a short paragraph, include citations and trace id."
    )
    generated = llm_generate(prompt)
    if generated:
        state["response"] = f"{generated}\nCitations: {citations}. Trace: {state['trace_id']}."
    else:
        state["response"] = (
            f"Based on {summary.get('range', 'recent')} data, total spend is "
            f"{summary.get('total_spend')} VND and income {summary.get('total_income')} VND. "
            f"Largest txn: {summary.get('largest_txn', {}).get('amount')} VND. "
            f"Citations: {citations}. Trace: {state['trace_id']}."
        )
    return state


def memory_update(state: AgentState) -> AgentState:
    # Store only summary (no raw ledger / PII)
    audit_write(state["user_id"], state["trace_id"], {"summary": state["response"]})
    return state


def build_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("intent_router", intent_router)
    graph.add_node("suitability_guard", suitability_guard)
    graph.add_node("fetch_context", fetch_context)
    graph.add_node("retrieve_kb", retrieve_kb)
    graph.add_node("what_if", what_if)
    graph.add_node("reasoning", reasoning)
    graph.add_node("memory_update", memory_update)

    graph.set_entry_point("intent_router")
    graph.add_edge("intent_router", "suitability_guard")
    graph.add_edge("suitability_guard", "fetch_context")
    graph.add_edge("fetch_context", "retrieve_kb")
    graph.add_edge("retrieve_kb", "what_if")
    graph.add_edge("what_if", "reasoning")
    graph.add_edge("reasoning", "memory_update")
    graph.add_edge("memory_update", END)

    return graph.compile()


def run_agent(prompt: str, user_token: str, user_id: str) -> Dict[str, Any]:
    trace_id = f"trc_{uuid.uuid4().hex[:8]}"
    graph = build_graph()
    state = graph.invoke(
        {
            "prompt": prompt,
            "user_token": user_token,
            "user_id": user_id,
            "intent": "",
            "context": {},
            "kb": {},
            "response": "",
            "trace_id": trace_id,
        }
    )
    return {"response": state["response"], "trace_id": trace_id, "citations": state["kb"]}
