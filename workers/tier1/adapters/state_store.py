from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List

from ..contracts import Tier1Alert


class InMemoryStateStore:
    """Placeholder state store (Aurora/Supabase adapter swap later)."""

    def __init__(self) -> None:
        self._alerts_by_user: Dict[str, List[Tier1Alert]] = {}

    def save_alert(self, alert: Tier1Alert) -> None:
        self._alerts_by_user.setdefault(alert.user_id, []).append(alert)

    def list_alerts(self, user_id: str) -> list[dict]:
        return [asdict(item) for item in self._alerts_by_user.get(user_id, [])]

