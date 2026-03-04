from __future__ import annotations

from typing import Any, Dict

from .store import InMemoryTTLStore


_STORE = InMemoryTTLStore()


def load_session(session_id: str) -> Dict[str, Any]:
    return _STORE.get_session(session_id)


def save_session(session_id: str, payload: Dict[str, Any], *, ttl_seconds: int = 3600) -> None:
    _STORE.put_session(session_id, payload, ttl_seconds=ttl_seconds)

