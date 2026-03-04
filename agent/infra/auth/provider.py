from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Protocol


@dataclass
class AuthResult:
    authenticated: bool
    subject: str = ""
    claims: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class AuthProvider(Protocol):
    def verify(self, authorization: str | None) -> AuthResult:
        ...

