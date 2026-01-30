from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import current_user
from app.services.store import store

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/{trace_id}")
def get_audit(trace_id: str, user=Depends(current_user)):
    for event in store.audit_events:
        if event.get("trace_id") == trace_id and event.get("user_id") == user.get("sub"):
            return event
    raise HTTPException(status_code=404, detail="Audit record not found")
