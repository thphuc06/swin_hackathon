from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from .adapters.queue_client import InMemoryEventQueue
from .adapters.state_store import InMemoryStateStore
from .contracts import Tier1Event
from .processors.alert_processor import derive_alerts


class Tier1PipelineRunner:
    """Event -> queue -> processor -> state-store pipeline skeleton."""

    def __init__(
        self,
        *,
        queue: InMemoryEventQueue | None = None,
        state_store: InMemoryStateStore | None = None,
    ) -> None:
        self.queue = queue or InMemoryEventQueue()
        self.state_store = state_store or InMemoryStateStore()

    def enqueue_event(self, event: Tier1Event) -> None:
        self.queue.publish(event)

    def process_once(self) -> Dict[str, Any]:
        event = self.queue.consume()
        if event is None:
            return {"status": "idle", "processed": 0, "alerts": []}

        alerts = derive_alerts(event)
        for alert in alerts:
            self.state_store.save_alert(alert)
        return {
            "status": "ok",
            "processed": 1,
            "event_type": event.event_type,
            "alerts": [asdict(item) for item in alerts],
        }

