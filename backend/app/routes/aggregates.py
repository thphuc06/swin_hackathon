from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import current_user
from app.services.finance import spend_analytics

router = APIRouter(prefix="/aggregates", tags=["aggregates"])


@router.get("/summary")
def summary(range: str = "30d", user=Depends(current_user)):
    return spend_analytics(
        auth_user_id=user.get("sub", ""),
        user_id=user.get("sub", ""),
        range_value=range,
    )
