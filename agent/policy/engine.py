from __future__ import annotations

from typing import Any, Dict, Iterable, Set

from core.settings import ALLOW_LEGACY_LOCAL_AUTH, POLICY_ADAPTER, POLICY_ALLOWED_TOOLS

from .contracts import PolicyDecision


class SimplePolicyEngine:
    """MVP policy hook that can be swapped with Cedar adapter in P2."""

    def __init__(self, *, allowed_tools: Iterable[str] | None = None) -> None:
        self._allowed_tools: Set[str] = set(allowed_tools or [])

    def authorize_tool_call(self, tool_name: str, *, context: Dict[str, Any]) -> PolicyDecision:
        if not self._allowed_tools:
            if ALLOW_LEGACY_LOCAL_AUTH:
                return PolicyDecision(allow=True, reason_codes=["policy_allow_default_local_only"])
            return PolicyDecision(
                allow=False,
                reason_codes=["policy_no_allowed_tools_configured"],
                deny_code="POLICY_DENY",
                metadata={"tool_name": tool_name, "context_keys": sorted(context.keys())},
            )
        if tool_name in self._allowed_tools:
            return PolicyDecision(allow=True, reason_codes=["policy_allow_tool_whitelist"])
        return PolicyDecision(
            allow=False,
            reason_codes=["policy_tool_not_allowed"],
            deny_code="POLICY_DENY",
            metadata={"tool_name": tool_name, "context_keys": sorted(context.keys())},
        )


def _parse_allowed_tools(raw: str) -> list[str]:
    return [token.strip() for token in str(raw or "").split(",") if token.strip()]


def _build_policy_engine() -> Any:
    adapter = str(POLICY_ADAPTER or "simple").strip().lower()
    allowed_tools = _parse_allowed_tools(POLICY_ALLOWED_TOOLS)
    if adapter == "cedar":
        from .cedar_adapter import CedarPolicyAdapter

        return CedarPolicyAdapter()
    return SimplePolicyEngine(allowed_tools=allowed_tools)


_DEFAULT_ENGINE = _build_policy_engine()


def get_policy_engine() -> Any:
    return _DEFAULT_ENGINE
