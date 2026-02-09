from __future__ import annotations

from typing import Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

IntentName = Literal["summary", "risk", "planning", "scenario", "invest", "out_of_scope"]
RouterMode = Literal["rule", "semantic_shadow", "semantic_enforce"]
RouteSource = Literal["rule", "semantic"]


class TopIntentScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: IntentName
    score: float = Field(ge=0.0, le=1.0)


class IntentExtractionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "intent_extraction_v1"
    intent: IntentName
    sub_intent: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    domain_relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    top2: list[TopIntentScore]
    slots: Dict[str, Any] = Field(default_factory=dict)
    scenario_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("top2")
    @classmethod
    def _validate_top2(cls, value: list[TopIntentScore]) -> list[TopIntentScore]:
        if len(value) != 2:
            raise ValueError("top2 must contain exactly 2 candidates")
        return value

    def top2_gap(self) -> float:
        if len(self.top2) < 2:
            return 0.0
        return float(self.top2[0].score - self.top2[1].score)


class ClarifyingQuestionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_text: str
    options: list[str] = Field(default_factory=list)
    max_questions: int = 2


class RouteDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RouterMode
    policy_version: str = "v1"
    final_intent: IntentName
    tool_bundle: list[str] = Field(default_factory=list)
    clarify_needed: bool = False
    clarifying_question: ClarifyingQuestionV1 | None = None
    reason_codes: list[str] = Field(default_factory=list)
    fallback_used: str | None = None
    source: RouteSource = "semantic"
