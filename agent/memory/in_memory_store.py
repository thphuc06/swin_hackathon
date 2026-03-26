from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, Optional

from .memory_interface import MemoryStore


class InMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, value in self._sessions.items() if value.get("expires_at", 0) and value["expires_at"] <= now]
        for key in expired:
            self._sessions.pop(key, None)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            session = self._sessions.get(session_id)
            if not session:
                return None
            return dict(session.get("data", {}))

    def set_session(self, session_id: str, data: Dict[str, Any], *, ttl_seconds: Optional[int] = None) -> None:
        expires_at = 0.0
        if ttl_seconds:
            expires_at = time.time() + max(1, int(ttl_seconds))
        with self._lock:
            self._sessions[session_id] = {
                "data": dict(data),
                "events": list(self._sessions.get(session_id, {}).get("events", [])),
                "expires_at": expires_at,
            }

    def append_event(
        self,
        session_id: str,
        event: Dict[str, Any],
        *,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        expires_at = 0.0
        if ttl_seconds:
            expires_at = time.time() + max(1, int(ttl_seconds))
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                record = {"data": {}, "events": [], "expires_at": expires_at}
            record.setdefault("events", []).append(dict(event))
            if expires_at:
                record["expires_at"] = expires_at
            self._sessions[session_id] = record

    def list_events(self, session_id: str) -> Iterable[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            record = self._sessions.get(session_id) or {}
            return list(record.get("events", []))


__all__ = ["InMemoryStore"]
