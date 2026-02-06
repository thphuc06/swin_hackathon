from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.auth import current_user
from app.services.store import store

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditWritePayload(BaseModel):
    trace_id: str
    event_type: str = "agent_summary"
    payload: dict


@router.post("")
def write_audit(payload: AuditWritePayload, user=Depends(current_user)):
    record = store.add_audit({
        "user_id": user.get("sub"),
        "trace_id": payload.trace_id,
        "event_type": payload.event_type,
        "payload": payload.payload,
    })
    return {"status": "ok", "audit": record}


@router.get("/{trace_id}")
def get_audit(trace_id: str, user=Depends(current_user)):
    for event in store.audit_events:
        if event.get("trace_id") == trace_id and event.get("user_id") == user.get("sub"):
            tool_chain = [
                item for item in store.tool_events
                if item.get("trace_id") == trace_id and item.get("user_id") == user.get("sub")
            ]
            return {
                **event,
                "tool_chain": tool_chain,
            }
    raise HTTPException(status_code=404, detail="Audit record not found")
