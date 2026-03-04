from __future__ import annotations

from typing import Any, Dict


class NoopExporter:
    def export_trace(self, envelope: Dict[str, Any]) -> None:
        _ = envelope
        return None

