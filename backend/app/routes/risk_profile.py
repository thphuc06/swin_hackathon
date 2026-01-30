from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import current_user
from app.services.store import store

router = APIRouter(prefix="/risk-profile", tags=["risk-profile"])


class RiskProfilePayload(BaseModel):
    profile: str
    notes: str | None = None


@router.get("")
def get_risk_profile(user=Depends(current_user)):
    profiles = [p for p in store.risk_profiles if p.get("user_id") == user.get("sub")]
    return {"current": profiles[-1] if profiles else None}


@router.post("")
def add_risk_profile(payload: RiskProfilePayload, user=Depends(current_user)):
    record = {
        **payload.model_dump(),
        "user_id": user.get("sub"),
        "version": len(store.risk_profiles) + 1,
    }
    store.risk_profiles.append(record)
    return {"status": "ok", "risk_profile": record}
