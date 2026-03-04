from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .errors import ValidationFailedError


@dataclass
class ToolInvocation:
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str
    trace_id: str
    idempotency_key: str = ""


@dataclass
class StockRiskProfile:
    risk_band: str = "unknown"
    horizon_months: int = 0
    liquidity_need: str = ""


@dataclass
class StockConstraints:
    education_only: bool = True
    suitability_required: bool = True


@dataclass
class StockContextSnapshot:
    net_cashflow: float = 0.0
    runway_months: float = 0.0
    anomaly_flags: List[str] = field(default_factory=list)


@dataclass
class StockAdvisoryRequest:
    user_id: str
    query: str
    risk_profile: StockRiskProfile = field(default_factory=StockRiskProfile)
    constraints: StockConstraints = field(default_factory=StockConstraints)
    context_snapshot: StockContextSnapshot = field(default_factory=StockContextSnapshot)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "query": self.query,
            "risk_profile": {
                "risk_band": self.risk_profile.risk_band,
                "horizon_months": int(self.risk_profile.horizon_months),
                "liquidity_need": self.risk_profile.liquidity_need,
            },
            "constraints": {
                "education_only": bool(self.constraints.education_only),
                "suitability_required": bool(self.constraints.suitability_required),
            },
            "context_snapshot": {
                "net_cashflow": float(self.context_snapshot.net_cashflow),
                "runway_months": float(self.context_snapshot.runway_months),
                "anomaly_flags": list(self.context_snapshot.anomaly_flags or []),
            },
        }


@dataclass
class StockSuitabilityCheck:
    status: str = "warn"
    reasons: List[str] = field(default_factory=list)


@dataclass
class StockAdvisoryResponse:
    summary: str
    alternatives: List[str] = field(default_factory=list)
    suitability_check: StockSuitabilityCheck = field(default_factory=StockSuitabilityCheck)
    citations: List[str] = field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    trace_ref: str = ""
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    portfolio_constraints: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "StockAdvisoryResponse":
        if not isinstance(payload, dict):
            raise ValidationFailedError("Stock agent response must be a JSON object.")
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise ValidationFailedError("Stock agent response is missing required field: summary.")

        raw_suitability = payload.get("suitability_check")
        if not isinstance(raw_suitability, dict):
            raw_suitability = {}
        status = str(raw_suitability.get("status") or "warn").strip().lower()
        if status not in {"pass", "warn", "deny"}:
            status = "warn"
        reasons = [
            str(item).strip()
            for item in raw_suitability.get("reasons", [])
            if isinstance(item, str) and str(item).strip()
        ]
        suitability_check = StockSuitabilityCheck(status=status, reasons=reasons)

        alternatives = [
            str(item).strip()
            for item in payload.get("alternatives", [])
            if isinstance(item, str) and str(item).strip()
        ]
        citations = [
            str(item).strip()
            for item in payload.get("citations", [])
            if isinstance(item, str) and str(item).strip()
        ]
        warnings = [
            str(item).strip()
            for item in payload.get("warnings", [])
            if isinstance(item, str) and str(item).strip()
        ]
        market_snapshot = payload.get("market_snapshot")
        if not isinstance(market_snapshot, dict):
            market_snapshot = {}
        portfolio_constraints = payload.get("portfolio_constraints")
        if not isinstance(portfolio_constraints, dict):
            fallback_constraints = payload.get("constraints")
            portfolio_constraints = fallback_constraints if isinstance(fallback_constraints, dict) else {}

        confidence_raw = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            summary=summary,
            alternatives=alternatives,
            suitability_check=suitability_check,
            citations=citations,
            confidence=confidence,
            warnings=warnings,
            trace_ref=str(payload.get("trace_ref") or "").strip(),
            market_snapshot=market_snapshot,
            portfolio_constraints=portfolio_constraints,
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "alternatives": list(self.alternatives or []),
            "suitability_check": {
                "status": self.suitability_check.status,
                "reasons": list(self.suitability_check.reasons or []),
            },
            "citations": list(self.citations or []),
            "confidence": float(self.confidence),
            "warnings": list(self.warnings or []),
            "trace_ref": self.trace_ref,
            "market_snapshot": dict(self.market_snapshot or {}),
            "portfolio_constraints": dict(self.portfolio_constraints or {}),
        }


@dataclass
class ExternalAgentResult:
    status: str
    reason_code: str
    payload: Dict[str, Any]
