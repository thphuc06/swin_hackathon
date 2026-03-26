from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .in_memory_store import InMemoryStore
from .memory_interface import MemoryStore


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class MemoryContext:
    session_id: str
    trace_id: str
    request_timestamp: str
    prompt: str
    response: str
    tool_calls: list[str]
    agent_outputs: Dict[str, Any]


_MEMORY_STORE: Optional[MemoryStore] = None


def initialize_memory_store() -> Optional[MemoryStore]:
    global _MEMORY_STORE
    if not _env_bool("ENABLE_AGENT_MEMORY", False):
        _MEMORY_STORE = None
        return None
    if _MEMORY_STORE is None:
        _MEMORY_STORE = InMemoryStore()
    return _MEMORY_STORE


def get_memory_store() -> Optional[MemoryStore]:
    return _MEMORY_STORE


def build_memory_context(state: Dict[str, Any]) -> MemoryContext:
    return MemoryContext(
        session_id=str(state.get("session_id") or ""),
        trace_id=str(state.get("trace_id") or ""),
        request_timestamp=str(state.get("request_timestamp") or _utc_now_iso()),
        prompt=str(state.get("prompt") or ""),
        response=str(state.get("response") or ""),
        tool_calls=list(state.get("tool_calls", []) if isinstance(state.get("tool_calls"), list) else []),
        agent_outputs=dict(state.get("agent_outputs", {}) if isinstance(state.get("agent_outputs"), dict) else {}),
    )


__all__ = [
    "MemoryContext",
    "build_memory_context",
    "get_memory_store",
    "initialize_memory_store",
]
