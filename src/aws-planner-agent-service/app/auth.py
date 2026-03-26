from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status


def _strip_bearer(token: str) -> str:
    raw = token.strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def require_planner_auth(authorization: Optional[str] = Header(None)) -> None:
    expected = str(os.getenv("PLANNER_AGENT_AUTH_TOKEN") or "").strip()
    if not expected:
        return
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    provided = _strip_bearer(authorization)
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
