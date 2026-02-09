from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EncodingDecisionName = Literal["pass", "repair", "fail_fast"]


class EncodingDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "encoding_decision_v1"
    decision: EncodingDecisionName
    mojibake_score: float = Field(ge=0.0, le=1.0)
    repair_applied: bool = False
    encoding_guess: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    input_fingerprint: str
