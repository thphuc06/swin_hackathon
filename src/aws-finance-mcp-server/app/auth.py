from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional

import requests
from fastapi import Header, HTTPException, status
from jose import jwt


class CognitoSettings:
    def __init__(self) -> None:
        self.user_pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
        self.client_id = os.getenv("COGNITO_CLIENT_ID", "")
        self.region = os.getenv("AWS_REGION", "us-west-2")
        self.issuer = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
            if self.user_pool_id
            else ""
        )
        self.dev_bypass = os.getenv("DEV_BYPASS_AUTH", "false").lower() == "true"


@lru_cache
def _jwks() -> Dict:
    settings = CognitoSettings()
    if not settings.issuer:
        return {}
    jwks_url = f"{settings.issuer}/.well-known/jwks.json"
    return requests.get(jwks_url, timeout=5).json()


def _get_key(token: str) -> Optional[Dict]:
    headers = jwt.get_unverified_header(token)
    for key in _jwks().get("keys", []):
        if key.get("kid") == headers.get("kid"):
            return key
    return None


def verify_jwt(authorization: Optional[str]) -> Dict:
    settings = CognitoSettings()
    if settings.dev_bypass:
        return {"sub": "demo-user", "email": "demo@jars.local"}

    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    token = parts[1]
    key = _get_key(token)
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown key")

    try:
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.client_id or None,
            issuer=settings.issuer or None,
            options={"verify_aud": bool(settings.client_id)},
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def current_user(authorization: Optional[str] = Header(None)) -> Dict:
    return verify_jwt(authorization)
