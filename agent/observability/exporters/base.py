from __future__ import annotations

from typing import Any, Dict, Protocol


class ObservabilityExporter(Protocol):
    def export_trace(self, envelope: Dict[str, Any]) -> None:
        ...

