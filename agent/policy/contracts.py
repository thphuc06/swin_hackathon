from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class PolicyDecision:
    allow: bool
    reason_codes: list[str] = field(default_factory=list)
    deny_code: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "allow": bool(self.allow),
            "reason_codes": list(self.reason_codes or []),
            "deny_code": self.deny_code,
            "metadata": dict(self.metadata or {}),
        }

