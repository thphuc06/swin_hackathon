from __future__ import annotations

import threading
import time
from typing import Any, Dict


class InMemoryTTLStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def get_session(self, session_id: str) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            record = self._data.get(session_id)
            if record is None:
                return {}
            expires_at, payload = record
            if expires_at <= now:
                del self._data[session_id]
                return {}
            return dict(payload)

    def put_session(self, session_id: str, value: Dict[str, Any], *, ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds))
        with self._lock:
            self._data[session_id] = (time.time() + ttl, dict(value or {}))

