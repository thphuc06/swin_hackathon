from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.auth import current_user
from app.services.store import store

router = APIRouter(prefix="/transactions", tags=["transactions"])


class TransferRequest(BaseModel):
    jar_id: str
    category_id: str
    amount: float = Field(gt=0)
    counterparty: str


@router.post("/transfer")
def transfer(payload: TransferRequest, user=Depends(current_user)):
    record = store.add_transaction({
        **payload.model_dump(),
        "user_id": user.get("sub"),
        "type": "transfer",
    })
    return {"status": "ok", "transaction": record}


@router.get("")
def list_transactions(range: str = "30d", user=Depends(current_user)):
    return {
        "range": range,
        "items": [t for t in store.transactions if t.get("user_id") == user.get("sub")],
    }
