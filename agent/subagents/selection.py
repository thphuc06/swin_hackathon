from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .catalog import AgentCatalog, SpecialistDescriptor


@dataclass
class SelectionContext:
    intent: Optional[str] = None
    confidence: Optional[float] = None
    required_domains: List[str] = field(default_factory=list)
    allowed_agent_ids: List[str] = field(default_factory=list)
    denied_agent_ids: List[str] = field(default_factory=list)


_COST_ORDER = {"low": 0, "medium": 1, "high": 2}
_LATENCY_ORDER = {"low": 0, "medium": 1, "high": 2}


def _domain_match(agent: SpecialistDescriptor, required_domains: Iterable[str]) -> bool:
    if not required_domains:
        return True
    agent_domains = {d.lower() for d in agent.domains}
    for domain in required_domains:
        if domain.lower() in agent_domains:
            return True
    return False


def _intent_allowed(agent: SpecialistDescriptor, intent: Optional[str]) -> bool:
    if intent is None or agent.policy is None:
        return True
    allowed = agent.policy.allowed_intents
    if not allowed:
        return True
    return intent in allowed


def _confidence_ok(agent: SpecialistDescriptor, confidence: Optional[float]) -> bool:
    if confidence is None:
        return True
    min_conf = agent.routing.min_confidence
    if min_conf is None:
        return True
    return confidence >= min_conf


def _rank(agent: SpecialistDescriptor) -> tuple:
    cost = _COST_ORDER.get(agent.routing.cost_tier, 3)
    latency = _LATENCY_ORDER.get(agent.routing.latency_class, 3)
    return (-agent.routing.priority, cost, latency)


def select_specialist(catalog: AgentCatalog, context: SelectionContext) -> Optional[SpecialistDescriptor]:
    candidates = []
    for agent in catalog.agents:
        if not agent.enabled:
            continue
        if context.allowed_agent_ids and agent.id not in context.allowed_agent_ids:
            continue
        if context.denied_agent_ids and agent.id in context.denied_agent_ids:
            continue
        if not _domain_match(agent, context.required_domains):
            continue
        if not _intent_allowed(agent, context.intent):
            continue
        if not _confidence_ok(agent, context.confidence):
            continue
        candidates.append(agent)

    if not candidates:
        return None

    candidates.sort(key=_rank)
    return candidates[0]


__all__ = [
    "SelectionContext",
    "select_specialist",
]
