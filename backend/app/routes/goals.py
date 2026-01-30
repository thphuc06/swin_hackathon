from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import current_user
from app.services.store import store

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalPayload(BaseModel):
    name: str
    target_amount: float
    horizon_months: int


@router.post("")
def upsert_goal(payload: GoalPayload, user=Depends(current_user)):
    store.goals[user.get("sub")] = payload.model_dump()
    return {"status": "ok", "goal": payload.model_dump()}
