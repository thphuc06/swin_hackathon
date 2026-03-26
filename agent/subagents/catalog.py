from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import jsonschema

SCHEMA_VERSION = "v1"
DEFAULT_CATALOG_PATH = Path(__file__).with_name("agent_catalog.v1.json")
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schemas").joinpath("agent_catalog.v1.json")


@dataclass
class RoutingMetadata:
    cost_tier: str
    latency_class: str
    safety_class: str
    parallelizable: bool
    priority: int = 0
    min_confidence: Optional[float] = None


@dataclass
class PolicyMetadata:
    requires_suitability: bool = False
    allowed_intents: List[str] = field(default_factory=list)


@dataclass
class SpecialistDescriptor:
    id: str
    tool_name: str
    tool_version: str
    input_schema: str
    output_schema: str
    domains: List[str]
    capabilities: List[str]
    routing: RoutingMetadata
    enabled: bool
    gateway_tool_name: Optional[str] = None
    policy: Optional[PolicyMetadata] = None


@dataclass
class AgentCatalog:
    schema_version: str
    agents: List[SpecialistDescriptor]


def _load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(catalog: Dict, schema: Dict) -> None:
    jsonschema.validate(instance=catalog, schema=schema)


def _parse_agent(agent: Dict) -> SpecialistDescriptor:
    routing = agent.get("routing", {})
    policy = agent.get("policy")
    return SpecialistDescriptor(
        id=agent["id"],
        tool_name=agent["tool_name"],
        tool_version=agent["tool_version"],
        input_schema=agent["input_schema"],
        output_schema=agent["output_schema"],
        domains=agent.get("domains", []),
        capabilities=agent.get("capabilities", []),
        routing=RoutingMetadata(
            cost_tier=routing["cost_tier"],
            latency_class=routing["latency_class"],
            safety_class=routing["safety_class"],
            parallelizable=routing["parallelizable"],
            priority=routing.get("priority", 0),
            min_confidence=routing.get("min_confidence"),
        ),
        enabled=agent.get("enabled", True),
        gateway_tool_name=agent.get("gateway_tool_name"),
        policy=PolicyMetadata(
            requires_suitability=policy.get("requires_suitability", False),
            allowed_intents=policy.get("allowed_intents", []),
        ) if policy is not None else None,
    )


def load_catalog(
    catalog_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
) -> AgentCatalog:
    path = catalog_path or DEFAULT_CATALOG_PATH
    schema = _load_json(schema_path or DEFAULT_SCHEMA_PATH)
    data = _load_json(path)

    _validate(data, schema)

    agents = [_parse_agent(agent) for agent in data.get("agents", [])]
    return AgentCatalog(schema_version=data.get("schema_version", SCHEMA_VERSION), agents=agents)


__all__ = [
    "AgentCatalog",
    "PolicyMetadata",
    "RoutingMetadata",
    "SpecialistDescriptor",
    "load_catalog",
]
