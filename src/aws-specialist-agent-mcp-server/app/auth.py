from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional

import requests
from fastapi import Header, HTTPException, status
from jose import jwt


def _parse_csv_env(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


VALID_APP_ENVS = {"local", "demo", "staging", "prod"}
LOCAL_APP_ENVS = {"local", "demo"}
DEPLOYED_APP_ENVS = {"staging", "prod"}


def _resolve_region(user_pool_id: str) -> str:
    region = str(os.getenv("AWS_REGION") or "").strip()
    if region:
        return region
    if "_" in user_pool_id:
        prefix = user_pool_id.split("_", 1)[0].strip()
        if prefix:
            return prefix
    return "us-east-1"


def _resolve_app_env() -> str:
    raw = str(os.getenv("APP_ENV") or "").strip().lower()
    if raw:
        if raw not in VALID_APP_ENVS:
            raise RuntimeError("APP_ENV must be one of: local, demo, staging, prod.")
        return raw

    if str(os.getenv("DEV_BYPASS_AUTH") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return "local"

    deploy_markers = (
        str(os.getenv("COGNITO_USER_POOL_ID") or "").strip(),
        str(os.getenv("COGNITO_CLIENT_ID") or "").strip(),
        str(os.getenv("COGNITO_ALLOWED_CLIENT_IDS") or "").strip(),
    )
    if any(marker for marker in deploy_markers):
        raise RuntimeError(
            "APP_ENV must be explicitly set to local, demo, staging, or prod when specialist auth is configured."
        )
    return "local"


class CognitoSettings:
    def __init__(self) -> None:
        self.app_env = _resolve_app_env()
        self.user_pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
        self.client_id = os.getenv("COGNITO_CLIENT_ID", "")
        allowed_client_ids = _parse_csv_env(os.getenv("COGNITO_ALLOWED_CLIENT_IDS", ""))
        self.allowed_client_ids = allowed_client_ids or ((self.client_id,) if self.client_id else ())
        self.service_client_ids = _parse_csv_env(os.getenv("COGNITO_SERVICE_CLIENT_IDS", ""))
        self.region = _resolve_region(self.user_pool_id)
        self.issuer = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
            if self.user_pool_id
            else ""
        )
        self.dev_bypass = os.getenv("DEV_BYPASS_AUTH", "false").lower() == "true"
        self.is_deployed_env = self.app_env in DEPLOYED_APP_ENVS
        self.allow_local_bypass = self.app_env in LOCAL_APP_ENVS
        self.validate_contract()

    def validate_contract(self) -> None:
        if self.dev_bypass and not self.allow_local_bypass:
            raise RuntimeError("DEV_BYPASS_AUTH is allowed only when APP_ENV is local or demo.")

        if self.is_deployed_env:
            missing: list[str] = []
            if not self.user_pool_id:
                missing.append("COGNITO_USER_POOL_ID")
            if not self.client_id:
                missing.append("COGNITO_CLIENT_ID")
            if missing:
                raise RuntimeError(
                    f"Deployed specialist auth requires explicit Cognito settings: {', '.join(missing)}."
                )


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


def _validate_access_token_claims(claims: Dict[str, Any], settings: CognitoSettings) -> str:
    token_use = str(claims.get("token_use") or "").strip().lower()
    if token_use != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expected Cognito AccessToken (token_use=access).",
        )
    return _validate_client_id(claims, settings)


def _caller_type_for_client(client_id: str, settings: CognitoSettings) -> str:
    if client_id and client_id in settings.service_client_ids:
        return "service"
    return "user"


def verify_jwt(authorization: Optional[str]) -> Dict[str, Any]:
    """Verify Cognito Access Tokens for Gateway -> specialist calls."""
    settings = CognitoSettings()
    if settings.dev_bypass:
        return {
            "sub": "demo-user",
            "email": "demo@jars.local",
            "client_id": "dev-bypass",
            "caller_type": "user",
            "token_use": "access",
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    client_id = _validate_access_token_claims(claims, settings)
    claims["client_id"] = client_id
    claims["caller_type"] = _caller_type_for_client(client_id, settings)
    claims["token_use"] = "access"
    return claims


def current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    return verify_jwt(authorization)


def _validate_startup_contract() -> None:
    CognitoSettings()


_validate_startup_contract()
