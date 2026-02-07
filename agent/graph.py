from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from typing import Any, Dict, TypedDict

import boto3
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from tools import (
    anomaly_signals,
    audit_write,
    cashflow_forecast_tool,
    jar_allocation_suggest_tool,
    kb_retrieve,
    risk_profile_non_investment_tool,
    spend_analytics,
    suitability_guard_tool,
)


class AgentState(TypedDict):
    user_token: str
    user_id: str
    prompt: str
    intent: str
    context: Dict[str, Any]
    kb: Dict[str, Any]
    tool_outputs: Dict[str, Any]
    tool_calls: list[str]
    education_only: bool
    response: str
    trace_id: str


load_dotenv()
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."


def _normalize_text(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )
    return stripped.lower()


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


def _requested_action(prompt: str) -> str:
    normalized = _normalize_text(prompt)
    for action in ["buy", "sell", "trade", "execute"]:
        if re.search(rf"\b{action}\b", normalized):
            return action
    return "advice"


def intent_router(state: AgentState) -> AgentState:
    normalized = _normalize_text(state["prompt"])
    if any(term in normalized for term in ["house", "saving", "goal", "plan", "mua nha", "tiet kiem"]):
        state["intent"] = "planning"
    elif any(term in normalized for term in ["risk", "runway", "anomaly", "alert"]):
        state["intent"] = "risk"
    elif any(term in normalized for term in ["invest", "stock", "buy", "sell", "trade", "dau tu"]):
        state["intent"] = "invest"
    else:
        state["intent"] = "summary"
    return state


def suitability_guard(state: AgentState) -> AgentState:
    decision = suitability_guard_tool(
        state["user_token"],
        user_id=state["user_id"],
        intent=state.get("intent", ""),
        requested_action=_requested_action(state["prompt"]),
        prompt=state["prompt"],
        trace_id=state["trace_id"],
    )
    state["tool_outputs"]["suitability_guard_v1"] = decision
    state["tool_calls"].append("suitability_guard_v1")
    state["education_only"] = bool(decision.get("education_only") or decision.get("decision") == "education_only")
    if not bool(decision.get("allow", True)):
        state["response"] = (
            f"{decision.get('refusal_message', 'Action is not allowed by policy.')} "
            f"Disclaimer: {decision.get('required_disclaimer', DEFAULT_DISCLAIMER)}. "
            f"Trace: {state['trace_id']}."
        )
    return state


def fetch_context(state: AgentState) -> AgentState:
    if state.get("response"):
        return state

    range_days = "90d" if state.get("intent") == "risk" else "30d"
    summary = spend_analytics(
        state["user_token"],
        user_id=state["user_id"],
        range_days=range_days,
        trace_id=state["trace_id"],
    )
    forecast = cashflow_forecast_tool(
        state["user_token"],
        user_id=state["user_id"],
        horizon="weekly_12",
        trace_id=state["trace_id"],
    )
    state["context"] = {"summary": summary, "forecast": forecast}
    state["tool_outputs"]["spend_analytics_v1"] = summary
    state["tool_outputs"]["cashflow_forecast_v1"] = forecast
    state["tool_calls"].append("spend_analytics_v1")
    state["tool_calls"].append("cashflow_forecast_v1")
    return state


def retrieve_kb(state: AgentState) -> AgentState:
    state["kb"] = kb_retrieve(state["prompt"], {"doc_type": "policy"}, state["user_token"])
    return state


def decision_engine(state: AgentState) -> AgentState:
    if state.get("response"):
        return state

    intent = state.get("intent", "summary")
    if intent == "risk":
        anomaly = anomaly_signals(
            state["user_token"],
            user_id=state["user_id"],
            lookback_days=90,
            trace_id=state["trace_id"],
        )
        risk = risk_profile_non_investment_tool(
            state["user_token"],
            user_id=state["user_id"],
            lookback_days=180,
            trace_id=state["trace_id"],
        )
        state["tool_outputs"]["anomaly_signals_v1"] = anomaly
        state["tool_outputs"]["risk_profile_non_investment_v1"] = risk
        state["tool_calls"].append("anomaly_signals_v1")
        state["tool_calls"].append("risk_profile_non_investment_v1")
    elif intent in {"planning", "summary"}:
        allocation = jar_allocation_suggest_tool(
            state["user_token"],
            user_id=state["user_id"],
            trace_id=state["trace_id"],
        )
        state["tool_outputs"]["jar_allocation_suggest_v1"] = allocation
        state["tool_calls"].append("jar_allocation_suggest_v1")
    elif intent == "invest":
        risk = risk_profile_non_investment_tool(
            state["user_token"],
            user_id=state["user_id"],
            lookback_days=180,
            trace_id=state["trace_id"],
        )
        state["tool_outputs"]["risk_profile_non_investment_v1"] = risk
        state["tool_calls"].append("risk_profile_non_investment_v1")
        state["education_only"] = True
    return state


def reasoning(state: AgentState) -> AgentState:
    if state.get("response"):
        return state

    citations = ", ".join([m.get("citation", "") for m in state.get("kb", {}).get("matches", []) if m.get("citation")])
    tool_chain = ", ".join(state.get("tool_calls", []))

    if state.get("education_only"):
        state["response"] = (
            "I can provide educational financial guidance only and cannot execute buy/sell actions. "
            f"Disclaimer: {DEFAULT_DISCLAIMER}. "
            f"Citations: {citations}. Trace: {state['trace_id']}. Tools: {tool_chain}."
        )
        return state

    prompt = (
        "You are a fintech assistant. Use only numeric context from tools. "
        "Do not provide investment advice. Keep answer concise.\n\n"
        f"Context: {json.dumps(state.get('context', {}))}\n"
        f"Tool outputs: {json.dumps(state.get('tool_outputs', {}))}\n"
        f"KB citations: {citations}\n"
        f"User prompt: {state['prompt']}\n"
    )
    generated = llm_generate(prompt)
    if generated:
        state["response"] = (
            f"{generated}\n"
            f"Citations: {citations}. Disclaimer: {DEFAULT_DISCLAIMER}. "
            f"Trace: {state['trace_id']}. Tools: {tool_chain}."
        )
    else:
        summary = state.get("context", {}).get("summary", {})
        state["response"] = (
            f"Recent spend is {summary.get('total_spend')} and income is {summary.get('total_income')} based on SQL-backed tools. "
            f"Citations: {citations}. Disclaimer: {DEFAULT_DISCLAIMER}. "
            f"Trace: {state['trace_id']}. Tools: {tool_chain}."
        )
    return state


def memory_update(state: AgentState) -> AgentState:
    payload = {
        "summary": state.get("response", ""),
        "tool_calls": state.get("tool_calls", []),
    }
    audit_write(state["user_id"], state["trace_id"], payload, state["user_token"])
    return state


def build_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("intent_router", intent_router)
    graph.add_node("suitability_guard", suitability_guard)
    graph.add_node("fetch_context", fetch_context)
    graph.add_node("retrieve_kb", retrieve_kb)
    graph.add_node("decision_engine", decision_engine)
    graph.add_node("reasoning", reasoning)
    graph.add_node("memory_update", memory_update)

    graph.set_entry_point("intent_router")
    graph.add_edge("intent_router", "suitability_guard")
    graph.add_edge("suitability_guard", "fetch_context")
    graph.add_edge("fetch_context", "retrieve_kb")
    graph.add_edge("retrieve_kb", "decision_engine")
    graph.add_edge("decision_engine", "reasoning")
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
            "tool_outputs": {},
            "tool_calls": [],
            "education_only": False,
            "response": "",
            "trace_id": trace_id,
        }
    )
    return {
        "response": state["response"],
        "trace_id": trace_id,
        "citations": state.get("kb", {}),
        "tool_calls": state.get("tool_calls", []),
        "tool_outputs": state.get("tool_outputs", {}),
    }
