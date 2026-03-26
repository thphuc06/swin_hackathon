from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal["v1"]
ResultStatus = Literal["ok", "partial", "error", "blocked"]


class ActorInfo(BaseModel):
    actor_id: str
    user_id: str
    tenant_id: str = ""
    scopes: List[str] = Field(default_factory=list)


class CorrelationInfo(BaseModel):
    session_id: str
    request_id: str
    trace_id: str
    parent_request_id: str = ""
    request_timestamp: str = ""


class RequestInfo(BaseModel):
    prompt: str
    intent: str = ""
    policy_flags: Dict[str, Any] = Field(default_factory=dict)
    user_context: Dict[str, Any] = Field(default_factory=dict)
    goals: List[Dict[str, Any]] = Field(default_factory=list)
    session_summary: str = ""


class RoutingInfo(BaseModel):
    specialist_id: str
    tool_name: str


class SpecialistRequestEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: SchemaVersion
    actor: ActorInfo
    correlation: CorrelationInfo
    request: RequestInfo
    routing: RoutingInfo


class WarningItem(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warn", "critical"] = "warn"


class ErrorItem(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Citation(BaseModel):
    source_id: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    url: Optional[str] = None
    confidence: Optional[float] = None
    retrieved_at: Optional[str] = None


class ToolCallSummary(BaseModel):
    tool_name: str
    status: ResultStatus
    latency_ms: Optional[int] = None
    details: Optional[str] = None


class PolicyOutcome(BaseModel):
    suitability: Optional[Literal["pass", "fail", "unknown"]] = None
    reason: Optional[str] = None
    flags: Dict[str, Any] = Field(default_factory=dict)


class PlannerRecommendation(BaseModel):
    title: str
    rationale: str
    priority: Literal["low", "medium", "high"] = "medium"
    expected_impact: Optional[str] = None


class PlannerNextAction(BaseModel):
    action: str
    owner: Optional[str] = None
    timeframe: Optional[str] = None


class PlannerResult(BaseModel):
    summary: str
    key_facts: List[str] = Field(default_factory=list)
    recommendations: List[PlannerRecommendation] = Field(default_factory=list)
    next_actions: List[PlannerNextAction] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    tool_trace: List[ToolCallSummary] = Field(default_factory=list)
    warnings: List[WarningItem] = Field(default_factory=list)


class PlannerHumanReadableContract(BaseModel):
    summary: str
    key_facts: List[str] = Field(default_factory=list)
    recommendations: List[PlannerRecommendation] = Field(default_factory=list)
    next_actions: List[PlannerNextAction] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    warnings: List[WarningItem] = Field(default_factory=list)


class PlannerStandardizedContract(BaseModel):
    contract_spec_version: str
    txt_render_spec_version: str
    report_title: str
    section_order: List[str] = Field(default_factory=list)
    sections: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    human_readable: PlannerHumanReadableContract


class AgentResultEnvelope(BaseModel):
    schema_version: SchemaVersion
    agent_id: str
    agent_version: str
    status: ResultStatus
    correlation: CorrelationInfo
    result: PlannerResult
    summary: Optional[str] = None
    tool_name: Optional[str] = None
    policy: Optional[PolicyOutcome] = None
    standardized_contract: Optional[PlannerStandardizedContract] = None
    warnings: List[WarningItem] = Field(default_factory=list)
    errors: List[ErrorItem] = Field(default_factory=list)
