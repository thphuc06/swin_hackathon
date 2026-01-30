from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import current_user

router = APIRouter(prefix="/aggregates", tags=["aggregates"])


@router.get("/summary")
def summary(range: str = "30d", user=Depends(current_user)):
    return {
        "range": range,
        "user_id": user.get("sub"),
        "total_spend": 14200000,
        "total_income": 38200000,
        "largest_txn": {"merchant": "Techcombank", "amount": 5500000},
    }
