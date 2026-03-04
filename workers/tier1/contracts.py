from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Tier1Event:
    event_type: str
    user_id: str
    trace_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)


@dataclass
class Tier1Alert:
    user_id: str
    trace_id: str
    title: str
    detail: str
    channel: str = "push"
    created_at: str = field(default_factory=_utc_now_iso)

