from __future__ import annotations

from typing import Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LanguageCode = Literal["vi", "en"]
SeverityLevel = Literal["low", "medium", "high"]


class FactV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    label: str
    value: Any
    value_text: str
    unit: str = ""
    timeframe: str = ""
    source_tool: str
    source_path: str


class KeyMetricV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    label: str = ""


class InsightV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight_id: str
    kind: str
    severity: SeverityLevel = "medium"
    message_seed: str
    supporting_fact_ids: list[str] = Field(default_factory=list)


class ActionCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    priority: int = Field(default=50, ge=1, le=99)
    action_type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    supporting_insight_ids: list[str] = Field(default_factory=list)


class EvidencePackV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evidence_pack_v1"
    intent: str
    language: LanguageCode
    facts: list[FactV1] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    policy_flags: Dict[str, Any] = Field(default_factory=dict)


class AdvisoryContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "advisory_context_v1"
    intent: str
    language: LanguageCode
    facts: list[FactV1] = Field(default_factory=list)
    insights: list[InsightV1] = Field(default_factory=list)
    actions: list[ActionCandidateV1] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    policy_flags: Dict[str, Any] = Field(default_factory=dict)


class AnswerPlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "answer_plan_v2"
    language: LanguageCode
    summary_lines: list[str]
    key_metrics: list[KeyMetricV1] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str
    used_fact_ids: list[str] = Field(default_factory=list)
    used_insight_ids: list[str] = Field(default_factory=list)
    used_action_ids: list[str] = Field(default_factory=list)

    @field_validator("summary_lines")
    @classmethod
    def _validate_summary_lines(cls, value: list[str]) -> list[str]:
        if not (3 <= len(value) <= 5):
            raise ValueError("summary_lines must contain between 3 and 5 lines")
        if any(not str(line).strip() for line in value):
            raise ValueError("summary_lines must not contain empty lines")
        return value

    @field_validator("actions")
    @classmethod
    def _validate_actions(cls, value: list[str]) -> list[str]:
        if not (2 <= len(value) <= 4):
            raise ValueError("actions must contain between 2 and 4 entries")
        if any(not str(item).strip() for item in value):
            raise ValueError("actions must not contain empty entries")
        return value
