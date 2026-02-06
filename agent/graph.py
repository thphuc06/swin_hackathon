from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from typing import Any, Dict, TypedDict

from langgraph.graph import END, StateGraph
import boto3
from dotenv import load_dotenv

from tools import (
    audit_write,
    decision_house_affordability,
    decision_investment_capacity,
    decision_savings_goal,
    decision_what_if,
    forecast_cashflow,
    forecast_runway,
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
    tool_outputs: Dict[str, Any]
    tool_calls: list[str]
    education_only: bool
    response: str
    trace_id: str


load_dotenv()

FINANCIAL_INTENTS = ["summary", "house", "saving", "invest", "largest_txn", "what_if", "risk"]


def _normalize_text(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


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


def _extract_amounts_vnd(prompt: str) -> list[float]:
    pattern = re.compile(r"(\d+(?:[.,]\d+)?)\s*(tỷ|ty|trieu|triệu|tr|m|k)?", flags=re.IGNORECASE)
    values: list[float] = []
    for match in pattern.finditer(prompt):
        raw_value = match.group(1).replace(",", ".")
        try:
            number = float(raw_value)
        except ValueError:
            continue
        unit = (match.group(2) or "").lower()
        if unit in {"tỷ", "ty"}:
            number *= 1_000_000_000
        elif unit in {"triệu", "trieu", "tr", "m"}:
            number *= 1_000_000
        elif unit == "k":
            number *= 1_000
        values.append(number)
    return values


def _extract_horizon_months(prompt: str, default: int = 12) -> int:
    found = re.search(r"(\d{1,3})\s*tháng", _normalize_text(prompt))
    if not found:
        return default
    return max(1, min(360, int(found.group(1))))


def intent_router(state: AgentState) -> AgentState:
    normalized = _normalize_text(state["prompt"])
    if any(
        term in normalized
        for term in [
            "house",
            "housing",
            "mortgage",
            "home",
            "apartment",
            "real estate",
            "mua nha",
            "nha",
        ]
    ):
        state["intent"] = "house"
    elif any(term in normalized for term in ["tiet kiem", "saving", "save", "muc tieu", "goal"]):
        state["intent"] = "saving"
    elif any(term in normalized for term in ["invest", "dau tu", "co phieu", "stock", "sell", "buy"]):
        state["intent"] = "invest"
    elif any(term in normalized for term in ["largest", "max"]):
        state["intent"] = "largest_txn"
    elif "60" in normalized:
        state["intent"] = "summary_60d"
    else:
        state["intent"] = "summary_30d"
    return state


def fetch_context(state: AgentState) -> AgentState:
    range_days = "60d" if "60" in state["intent"] else "30d"
    summary = sql_read_views(state["user_token"], range_days)
    forecast = forecast_cashflow(state["user_token"], "90d")
    state["context"] = {
        "summary": summary,
        "forecast": forecast,
    }
    state["tool_outputs"]["forecast_cashflow_core"] = forecast
    state["tool_calls"].append("forecast_cashflow_core")
    return state


def retrieve_kb(state: AgentState) -> AgentState:
    state["kb"] = kb_retrieve(state["prompt"], {"doc_type": "policy"}, state["user_token"])
    return state


def suitability_guard(state: AgentState) -> AgentState:
    if state.get("intent") in {"house", "saving"}:
        return state
    normalized = _normalize_text(state["prompt"])
    if state.get("intent") == "invest" or any(term in normalized for term in ["invest", "sell", "stock", "dau tu"]):
        state["education_only"] = True
    return state


def decision_engine(state: AgentState) -> AgentState:
    summary = state["context"].get("summary", {})
    forecast = state["context"].get("forecast", {})
    trace_id = state["trace_id"]

    if state["intent"] == "house":
        amounts = _extract_amounts_vnd(state["prompt"])
        house_price = amounts[0] if amounts else 3_000_000_000
        down_payment = amounts[1] if len(amounts) > 1 else house_price * 0.3
        monthly_income = float(summary.get("total_income", 0))
        house_payload = {
            "house_price": house_price,
            "down_payment": down_payment,
            "interest_rate": 10.0,
            "loan_years": 20,
            "fees": house_price * 0.02,
            "monthly_income": monthly_income,
            "existing_debt_payment": 0.0,
            "cash_buffer": max(0.0, monthly_income * 2),
            "forecast": forecast,
            "trace_id": trace_id,
        }
        house_result = decision_house_affordability(state["user_token"], house_payload)
        state["tool_outputs"]["evaluate_house_affordability"] = house_result
        state["tool_calls"].append("evaluate_house_affordability")

        what_if_payload = {
            "base_scenario": {
                "horizon_months": 12,
                "seasonality": True,
                "scenario_overrides": {},
            },
            "variants": [
                {"name": "delay_purchase_12m", "scenario_overrides": {"spend_delta_pct": -0.1}},
                {"name": "increase_down_payment", "scenario_overrides": {"spend_delta_pct": -0.05}},
            ],
            "goal": "house",
            "trace_id": trace_id,
        }
        what_if_result = decision_what_if(state["user_token"], what_if_payload)
        state["tool_outputs"]["simulate_what_if"] = what_if_result
        state["tool_calls"].append("simulate_what_if")

    elif state["intent"] == "saving":
        amounts = _extract_amounts_vnd(state["prompt"])
        target_amount = amounts[0] if amounts else 500_000_000
        horizon_months = _extract_horizon_months(state["prompt"], 24)
        savings_payload = {
            "target_amount": target_amount,
            "horizon_months": horizon_months,
            "forecast": forecast,
            "trace_id": trace_id,
        }
        savings_result = decision_savings_goal(state["user_token"], savings_payload)
        state["tool_outputs"]["evaluate_savings_goal"] = savings_result
        state["tool_calls"].append("evaluate_savings_goal")

    elif state["intent"] == "invest":
        monthly_spend = float(summary.get("total_spend", 0))
        invest_payload = {
            "risk_profile": "balanced",
            "emergency_target": monthly_spend * 6 if monthly_spend else 60_000_000,
            "cash_buffer": monthly_spend * 2 if monthly_spend else 20_000_000,
            "forecast": forecast,
            "trace_id": trace_id,
        }
        invest_result = decision_investment_capacity(state["user_token"], invest_payload)
        state["tool_outputs"]["evaluate_investment_capacity"] = invest_result
        state["tool_calls"].append("evaluate_investment_capacity")
        state["education_only"] = True

    runway_payload = {
        "forecast": forecast,
        "cash_buffer": float(summary.get("total_income", 0)),
        "stress_config": {"runway_threshold_months": 6},
        "trace_id": trace_id,
    }
    runway = forecast_runway(state["user_token"], runway_payload)
    state["tool_outputs"]["compute_runway_and_stress"] = runway
    state["tool_calls"].append("compute_runway_and_stress")
    return state


def reasoning(state: AgentState) -> AgentState:
    citations = ", ".join([m["citation"] for m in state["kb"].get("matches", [])])
    if state.get("education_only"):
        state["response"] = (
            "I can share educational guidance but cannot provide investment advice. "
            "Review your cashflow capacity, emergency fund, and risk profile before investing. "
            f"Citations: {citations}."
        )
        return state

    summary = state.get("context", {})
    tools_payload = state.get("tool_outputs", {})
    prompt = (
        "You are a fintech assistant. Use the numeric context only. "
        "Do not provide investment advice. Provide concise guidance.\n"
        "Use the KB citations list as grounding, but do NOT invent KB IDs. "
        "Do NOT include trace IDs or 'Citations:' labels in your response.\n\n"
        f"Context: {json.dumps(summary)}\n"
        f"Tool outputs: {json.dumps(tools_payload)}\n"
        f"KB citations (filenames): {citations}\n"
        f"User question: {state['prompt']}\n"
        "Answer with a short paragraph only."
    )
    generated = llm_generate(prompt)
    if generated:
        tool_chain = ", ".join(state["tool_calls"])
        state["response"] = (
            f"{generated}\n"
            f"Citations: {citations}. Trace: {state['trace_id']}. Tools: {tool_chain}."
        )
    else:
        tool_chain = ", ".join(state["tool_calls"])
        summary_data = summary.get("summary", {})
        state["response"] = (
            f"Based on {summary_data.get('range', 'recent')} data, total spend is "
            f"{summary_data.get('total_spend')} VND and income {summary_data.get('total_income')} VND. "
            f"Tool-driven decision context has been computed for your intent. "
            f"Citations: {citations}. Trace: {state['trace_id']}. Tools: {tool_chain}."
        )
    return state


def memory_update(state: AgentState) -> AgentState:
    payload = {
        "summary": state["response"],
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
        "citations": state["kb"],
        "tool_calls": state.get("tool_calls", []),
        "tool_outputs": state.get("tool_outputs", {}),
    }
