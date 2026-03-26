from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import requests

from core.settings import (
    ALLOW_LEGACY_LOCAL_AUTH,
    CEDAR_POLICY_AUTH_TOKEN,
    CEDAR_POLICY_ENDPOINT,
    CEDAR_POLICY_FAIL_OPEN,
    CEDAR_POLICY_TIMEOUT_SECONDS,
)
from .contracts import PolicyDecision

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CedarPolicyAdapterConfig:
    endpoint: str
    auth_token: str
    timeout_seconds: float
    fail_open: bool
    allow_local_fail_open: bool

    @classmethod
    def from_env(cls) -> "CedarPolicyAdapterConfig":
        return cls(
            endpoint=str(CEDAR_POLICY_ENDPOINT or "").strip(),
            auth_token=str(CEDAR_POLICY_AUTH_TOKEN or "").strip(),
            timeout_seconds=max(0.2, float(CEDAR_POLICY_TIMEOUT_SECONDS or 2.0)),
            fail_open=bool(CEDAR_POLICY_FAIL_OPEN),
            allow_local_fail_open=bool(ALLOW_LEGACY_LOCAL_AUTH),
        )


class CedarPolicyAdapter:
    """HTTP adapter for Cedar-like authorization service."""

    def __init__(self, config: CedarPolicyAdapterConfig | None = None) -> None:
        self._config = config or CedarPolicyAdapterConfig.from_env()
        self._session = requests.Session()

    def authorize_tool_call(self, tool_name: str, *, context: Dict[str, Any]) -> PolicyDecision:
        if not self._config.endpoint:
            if self._config.allow_local_fail_open:
                return PolicyDecision(allow=True, reason_codes=["policy_fallback_no_cedar_endpoint_local_only"])
            return PolicyDecision(
                allow=False,
                reason_codes=["policy_cedar_missing_endpoint"],
                deny_code="POLICY_DENY",
                metadata={"tool_name": tool_name, "context_keys": sorted(context.keys())},
            )

        payload = {
            "principal": {
                "type": "user",
                "id": str(context.get("user_id") or ""),
            },
            "action": {"type": "tool_call", "id": tool_name},
            "resource": {"type": "agent_tool", "id": tool_name},
            "context": {
                "trace_id": str(context.get("trace_id") or ""),
                "intent": str(context.get("intent") or ""),
                "selected_agent": str(context.get("selected_agent") or ""),
                "extra": context,
            },
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._config.auth_token:
            token = self._config.auth_token
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"

        try:
            response = self._session.post(
                self._config.endpoint,
                json=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json() if response.text else {}
            allow = bool(data.get("allow", False))
            reason_codes = [
                str(item).strip()
                for item in data.get("reason_codes", [])
                if isinstance(item, str) and str(item).strip()
            ]
            deny_code = str(data.get("deny_code") or "").strip()
            metadata = data.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            if not reason_codes:
                reason_codes = ["policy_cedar_allow" if allow else "policy_cedar_deny"]
            return PolicyDecision(
                allow=allow,
                reason_codes=reason_codes,
                deny_code=deny_code,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cedar_authorize_failed tool=%s error=%s", tool_name, exc)
            if self._config.fail_open and self._config.allow_local_fail_open:
                return PolicyDecision(
                    allow=True,
                    reason_codes=["policy_cedar_error_fail_open_local_only"],
                    metadata={"error": str(exc)},
                )
            return PolicyDecision(
                allow=False,
                reason_codes=["policy_cedar_error_fail_closed"],
                deny_code="POLICY_DENY",
                metadata={"error": str(exc)},
            )

