from __future__ import annotations

from collections import deque
from typing import Optional

from ..contracts import Tier1Event


class InMemoryEventQueue:
    """Simple queue adapter placeholder (SQS swap in Phase 2+)."""

    def __init__(self) -> None:
        self._queue: deque[Tier1Event] = deque()

    def publish(self, event: Tier1Event) -> None:
        self._queue.append(event)

    def consume(self) -> Optional[Tier1Event]:
        if not self._queue:
            return None
        return self._queue.popleft()

    def size(self) -> int:
        return len(self._queue)

