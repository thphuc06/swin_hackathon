from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AgentCoreError(Exception):
    code: str
    message: str
    retryable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "metadata": dict(self.metadata or {}),
        }


class ValidationFailedError(AgentCoreError):
    def __init__(self, message: str, metadata: Dict[str, Any] | None = None) -> None:
        super().__init__("VALIDATION_FAILED", message, retryable=False, metadata=metadata or {})


class PolicyDeniedError(AgentCoreError):
    def __init__(self, message: str, metadata: Dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_DENY", message, retryable=False, metadata=metadata or {})


class DataInsufficientError(AgentCoreError):
    def __init__(self, message: str, metadata: Dict[str, Any] | None = None) -> None:
        super().__init__("DATA_INSUFFICIENT", message, retryable=False, metadata=metadata or {})


class ToolTimeoutError(AgentCoreError):
    def __init__(self, message: str, metadata: Dict[str, Any] | None = None) -> None:
        super().__init__("TOOL_TIMEOUT", message, retryable=True, metadata=metadata or {})


class ToolUnavailableError(AgentCoreError):
    def __init__(self, message: str, metadata: Dict[str, Any] | None = None) -> None:
        super().__init__("TOOL_UNAVAILABLE", message, retryable=True, metadata=metadata or {})


class ExternalAgentUnavailableError(AgentCoreError):
    def __init__(self, message: str, metadata: Dict[str, Any] | None = None, retryable: bool = True) -> None:
        super().__init__("EXTERNAL_AGENT_UNAVAILABLE", message, retryable=retryable, metadata=metadata or {})

