from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal["v1"]
ResultStatus = Literal["ok", "partial", "error", "blocked"]


class TraceInfo(BaseModel):
    trace_id: str
    request_id: str
    session_id: str
    agent_name: str
    tool_name: str
    schema_version: SchemaVersion
    latency_ms: Optional[int] = None
    reason_codes: List[str] = Field(default_factory=list)
    fallback_used: bool = False


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


class AgentResultEnvelope(BaseModel):
    schema_version: SchemaVersion
    agent_id: str
    agent_version: str
    tool_name: str
    status: ResultStatus
    result: PlannerResult
    summary: Optional[str] = None
    trace: Optional[TraceInfo] = None
    policy: Optional[PolicyOutcome] = None
    warnings: List[WarningItem] = Field(default_factory=list)
    errors: List[ErrorItem] = Field(default_factory=list)


class PlannerRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: SchemaVersion
    request_id: str
    session_id: str
    trace_id: str
    prompt: str
    user_context: Dict[str, Any] = Field(default_factory=dict)
    goals: List[Dict[str, Any]] = Field(default_factory=list)
    session_summary: Optional[str] = None
    policy_flags: Dict[str, Any] = Field(default_factory=dict)
    hints: Dict[str, Any] = Field(default_factory=dict)
    requested_outputs: List[str] = Field(default_factory=list)
