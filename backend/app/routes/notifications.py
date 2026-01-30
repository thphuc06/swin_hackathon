from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import current_user
from app.services.store import store

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationCreate(BaseModel):
    title: str
    detail: str
    trace_id: str


@router.get("")
def list_notifications(user=Depends(current_user)):
    return {
        "items": [n for n in store.notifications if n.get("user_id") == user.get("sub")],
    }


@router.post("")
def create_notification(payload: NotificationCreate, user=Depends(current_user)):
    record = store.add_notification({
        **payload.model_dump(),
        "user_id": user.get("sub"),
    })
    return {"status": "ok", "notification": record}
