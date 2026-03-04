from __future__ import annotations

from typing import Dict, List

from ..contracts import Tier1Alert, Tier1Event


def derive_alerts(event: Tier1Event) -> List[Tier1Alert]:
    payload: Dict[str, object] = event.payload if isinstance(event.payload, dict) else {}
    alerts: List[Tier1Alert] = []
    risk_flags = payload.get("risk_flags", [])
    if isinstance(risk_flags, list) and "runway_below_threshold" in risk_flags:
        alerts.append(
            Tier1Alert(
                user_id=event.user_id,
                trace_id=event.trace_id,
                title="Runway Alert",
                detail="Runway below threshold. Review spend and cash buffer.",
                channel="push",
            )
        )
    if isinstance(risk_flags, list) and "stress_scenario_negative_cash" in risk_flags:
        alerts.append(
            Tier1Alert(
                user_id=event.user_id,
                trace_id=event.trace_id,
                title="Stress Scenario Alert",
                detail="Stress scenario indicates negative cashflow risk.",
                channel="email",
            )
        )
    return alerts

