from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Protocol


class MemoryStore(Protocol):
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        ...

    def set_session(self, session_id: str, data: Dict[str, Any], *, ttl_seconds: Optional[int] = None) -> None:
        ...

    def append_event(
        self,
        session_id: str,
        event: Dict[str, Any],
        *,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        ...

    def list_events(self, session_id: str) -> Iterable[Dict[str, Any]]:
        ...


__all__ = ["MemoryStore"]
