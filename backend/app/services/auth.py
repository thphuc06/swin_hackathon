from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional

import requests
from fastapi import Header, HTTPException, status
from jose import jwt


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return str(value)
    # Defensive fallback for BOM-prefixed key names in malformed .env files.
    bom_value = os.getenv(f"\ufeff{name}")
    if bom_value is not None:
        return str(bom_value)
    return default


def _resolve_region(user_pool_id: str) -> str:
    region = _get_env("AWS_REGION", "").strip()
    if region:
        return region
    if "_" in user_pool_id:
        prefix = user_pool_id.split("_", 1)[0].strip()
        if prefix:
            return prefix
    return "us-east-1"


class CognitoSettings:
    def __init__(self) -> None:
        self.user_pool_id = _get_env("COGNITO_USER_POOL_ID", "").strip()
        self.client_id = _get_env("COGNITO_CLIENT_ID", "").strip()
        self.region = _resolve_region(self.user_pool_id)
        self.issuer = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
            if self.user_pool_id
            else ""
        )
        self.dev_bypass = _get_env("DEV_BYPASS_AUTH", "false").lower() == "true"


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
