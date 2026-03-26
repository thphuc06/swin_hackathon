from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

SchemaVersion = Literal["v1"]
ResultStatus = Literal["ok", "partial", "error", "blocked"]


@dataclass
class ActorInfo:
    actor_id: str
    user_id: str
    tenant_id: str = ""
    scopes: List[str] = field(default_factory=list)


@dataclass
class CorrelationInfo:
    session_id: str
    request_id: str
    trace_id: str
    parent_request_id: str = ""
    request_timestamp: str = ""


@dataclass
class RequestInfo:
    prompt: str
    intent: str = ""
    policy_flags: Dict[str, Any] = field(default_factory=dict)
    user_context: Dict[str, Any] = field(default_factory=dict)
    goals: List[Dict[str, Any]] = field(default_factory=list)
    session_summary: str = ""


@dataclass
class RoutingInfo:
    specialist_id: str
    tool_name: str


@dataclass
class SpecialistRequestEnvelope:
    schema_version: SchemaVersion
    actor: ActorInfo
    correlation: CorrelationInfo
    request: RequestInfo
    routing: RoutingInfo


@dataclass
class Warning:
    code: str
    message: str
    severity: Literal["info", "warn", "critical"] = "warn"


@dataclass
class Error:
    code: str
    message: str
    retryable: bool = False


@dataclass
class Citation:
    source_id: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    url: Optional[str] = None
    confidence: Optional[float] = None
    retrieved_at: Optional[str] = None


@dataclass
class ToolCallSummary:
    tool_name: str
    status: ResultStatus
    latency_ms: Optional[int] = None
    details: Optional[str] = None


@dataclass
class PolicyOutcome:
    suitability: Optional[Literal["pass", "warn", "fail", "unknown"]] = None
    reason: Optional[str] = None
    flags: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlannerRecommendation:
    title: str
    rationale: str
    priority: Literal["low", "medium", "high"] = "medium"
    expected_impact: Optional[str] = None


@dataclass
class PlannerNextAction:
    action: str
    owner: Optional[str] = None
    timeframe: Optional[str] = None


@dataclass
class PlannerResult:
    summary: str
    key_facts: List[str] = field(default_factory=list)
    recommendations: List[PlannerRecommendation] = field(default_factory=list)
    next_actions: List[PlannerNextAction] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    tool_trace: List[ToolCallSummary] = field(default_factory=list)
    warnings: List[Warning] = field(default_factory=list)


@dataclass
class StockRecommendation:
    ticker: str
    action: Literal["buy", "hold", "avoid"]
    rationale: str
    risk_level: Optional[str] = None


@dataclass
class StockAlternative:
    ticker: str
    rationale: str


@dataclass
class SuitabilityResult:
    status: Literal["pass", "warn", "fail", "unknown"]
    reason: Optional[str] = None


@dataclass
class StockResult:
    summary: str
    recommendations: List[StockRecommendation] = field(default_factory=list)
    alternatives: List[StockAlternative] = field(default_factory=list)
    suitability: Optional[SuitabilityResult] = None
    market_notes: List[str] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    warnings: List[Warning] = field(default_factory=list)


T = TypeVar("T")


@dataclass
class AgentResultEnvelope(Generic[T]):
    schema_version: SchemaVersion
    agent_id: str
    agent_version: str
    status: ResultStatus
    correlation: CorrelationInfo
    result: T
    summary: Optional[str] = None
    tool_name: Optional[str] = None
    policy: Optional[PolicyOutcome] = None
    warnings: List[Warning] = field(default_factory=list)
    errors: List[Error] = field(default_factory=list)


__all__ = [
    "ActorInfo",
    "AgentResultEnvelope",
    "Citation",
    "CorrelationInfo",
    "Error",
    "PlannerNextAction",
    "PlannerRecommendation",
    "PlannerResult",
    "PolicyOutcome",
    "RequestInfo",
    "ResultStatus",
    "RoutingInfo",
    "SchemaVersion",
    "SpecialistRequestEnvelope",
    "StockAlternative",
    "StockRecommendation",
    "StockResult",
    "SuitabilityResult",
    "ToolCallSummary",
    "Warning",
]
