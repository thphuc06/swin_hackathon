from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional

import requests
from fastapi import Header, HTTPException, status
from jose import jwt


def _parse_csv_env(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


class CognitoSettings:
    def __init__(self) -> None:
        self.user_pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
        self.client_id = os.getenv("COGNITO_CLIENT_ID", "")
        allowed_client_ids = _parse_csv_env(os.getenv("COGNITO_ALLOWED_CLIENT_IDS", ""))
        self.allowed_client_ids = allowed_client_ids or ((self.client_id,) if self.client_id else ())
        self.service_client_ids = _parse_csv_env(os.getenv("COGNITO_SERVICE_CLIENT_IDS", ""))
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


def _resolve_client_id(claims: Dict[str, Any]) -> str:
    client_id = claims.get("client_id")
    if isinstance(client_id, str) and client_id.strip():
        return client_id.strip()
    aud = claims.get("aud")
    if isinstance(aud, str):
        return aud.strip()
    if isinstance(aud, (list, tuple)):
        for candidate in aud:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _validate_client_id(claims: Dict[str, Any], settings: CognitoSettings) -> str:
    if not settings.allowed_client_ids:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth client allow-list is not configured",
        )
    client_id = _resolve_client_id(claims)
    if client_id not in settings.allowed_client_ids:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid client_id")
    return client_id


def _caller_type_for_client(client_id: str, settings: CognitoSettings) -> str:
    if client_id and client_id in settings.service_client_ids:
        return "service"
    return "user"


def verify_jwt(authorization: Optional[str]) -> Dict[str, Any]:
    settings = CognitoSettings()
    if settings.dev_bypass:
        return {
            "sub": "demo-user",
            "email": "demo@jars.local",
            "client_id": "dev-bypass",
            "caller_type": "user",
        }

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
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.issuer or None,
            options={"verify_aud": False},
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    client_id = _validate_client_id(claims, settings)
    claims["client_id"] = client_id
    claims["caller_type"] = _caller_type_for_client(client_id, settings)
    return claims


def current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    return verify_jwt(authorization)
