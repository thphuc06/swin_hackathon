from __future__ import annotations

import hashlib
import json
from typing import Any, Dict
from urllib.parse import urlparse

import requests

from config import BACKEND_API_BASE, BEDROCK_KB_ID


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]

def _is_local_backend() -> bool:
    try:
        host = urlparse(BACKEND_API_BASE).hostname or ""
    except ValueError:
        host = ""
    return host in {"localhost", "127.0.0.1"} or host.endswith(".local")


def _mock_summary(range_days: str) -> Dict[str, Any]:
    return {
        "range": range_days,
        "total_spend": 14_200_000,
        "total_income": 38_200_000,
        "largest_txn": {"amount": 5_500_000, "merchant": "Techcombank"},
        "jar_breakdown": [
            {"jar": "Bills", "amount": 4_200_000},
            {"jar": "Living", "amount": 6_800_000},
            {"jar": "Goals", "amount": 3_200_000},
        ],
        "note": "Mocked context (backend not reachable from runtime).",
    }


def sql_read_views(user_token: str, range_days: str) -> Dict[str, Any]:
    if _is_local_backend():
        return _mock_summary(range_days)
    headers = {"Authorization": user_token} if user_token else {}
    try:
        response = requests.get(
            f"{BACKEND_API_BASE}/aggregates/summary",
            params={"range": range_days},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return _mock_summary(range_days)


def goals_get_set(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _is_local_backend():
        return {"status": "mocked", "payload": payload}
    headers = {"Authorization": user_token} if user_token else {}
    response = requests.post(
        f"{BACKEND_API_BASE}/goals",
        json=payload,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def notifications_send(user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if _is_local_backend():
        return {"status": "mocked", "payload": payload}
    headers = {"Authorization": user_token} if user_token else {}
    response = requests.post(
        f"{BACKEND_API_BASE}/notifications",
        json=payload,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def kb_retrieve(query: str, filters: Dict[str, str]) -> Dict[str, Any]:
    if not BEDROCK_KB_ID:
        return {"matches": [], "note": "KB not configured"}
    # Placeholder for Knowledge Bases retrieve. Replace with bedrock-agent runtime call.
    return {
        "matches": [
            {"id": "kb-03", "text": "Risk suitability guidance", "citation": "KB-03"},
            {"id": "kb-07", "text": "Housing affordability template", "citation": "KB-07"},
        ],
        "filters": filters,
    }


def code_interpreter_run(expression: str) -> Dict[str, Any]:
    # Placeholder for AgentCore Code Interpreter invocation.
    return {"result": f"Computed ETA for: {expression}", "assumptions": {"inflation": 0.04}}


def audit_write(user_id: str, trace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"trace_id": trace_id, "payload_hash": _hash_payload(payload)}
