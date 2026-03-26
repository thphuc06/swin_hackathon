from __future__ import annotations

import json
import logging
import os
import urllib.request
from functools import lru_cache
from typing import Any, Dict

from core.settings import (
    APP_ENV,
    AUTH_DEV_BYPASS,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
    COGNITO_USER_POOL_ID,
)

from .provider import AuthResult

logger = logging.getLogger(__name__)


def _parse_csv_env(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _issuer() -> str:
    if not COGNITO_USER_POOL_ID:
        return ""
    region = COGNITO_REGION
    if not region and "_" in COGNITO_USER_POOL_ID:
        region = COGNITO_USER_POOL_ID.split("_", 1)[0]
    region = region or "us-east-1"
    return f"https://cognito-idp.{region}.amazonaws.com/{COGNITO_USER_POOL_ID}"


@lru_cache
def _jwks() -> Dict[str, Any]:
    iss = _issuer()
    if not iss:
        return {}
    url = f"{iss}/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=5) as response:  # nosec B310
        body = response.read().decode("utf-8")
    data = json.loads(body)
    return data if isinstance(data, dict) else {}


def _allowed_client_ids() -> tuple[str, ...]:
    allowed = _parse_csv_env(os.getenv("COGNITO_ALLOWED_CLIENT_IDS", ""))
    if allowed:
        return allowed
    return (COGNITO_CLIENT_ID,) if COGNITO_CLIENT_ID else ()


def _resolve_client_id(claims: Dict[str, Any]) -> str:
    client_id = claims.get("client_id")
    if isinstance(client_id, str) and client_id.strip():
        return client_id.strip()
    aud = claims.get("aud")
    if isinstance(aud, str) and aud.strip():
        return aud.strip()
    if isinstance(aud, (list, tuple)):
        for candidate in aud:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


class CognitoAuthProvider:
    """Cognito AccessToken verification adapter for deployed AWS mode."""

    def verify(self, authorization: str | None) -> AuthResult:
        if AUTH_DEV_BYPASS:
            return AuthResult(
                authenticated=True,
                subject="demo-user",
                claims={
                    "sub": "demo-user",
                    "scope": "dev:bypass",
                    "token_use": "access",
                    "client_id": "dev-bypass",
                    "app_env": APP_ENV,
                },
                reason="auth_dev_bypass_local_only",
            )

        if not authorization:
            return AuthResult(authenticated=False, reason="missing_authorization")
        parts = str(authorization).split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return AuthResult(authenticated=False, reason="invalid_token_format")
        token = parts[1]

        try:
            from jose import jwt  # type: ignore
        except Exception:
            logger.warning("python-jose dependency is missing for CognitoAuthProvider")
            return AuthResult(authenticated=False, reason="missing_python_jose_dependency")

        try:
            headers = jwt.get_unverified_header(token)
            kid = headers.get("kid")
            key = None
            for candidate in _jwks().get("keys", []):
                if isinstance(candidate, dict) and candidate.get("kid") == kid:
                    key = candidate
                    break
            if key is None:
                return AuthResult(authenticated=False, reason="unknown_signing_key")

            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=_issuer() or None,
                options={"verify_aud": False},
            )
            token_use = str(claims.get("token_use") or "").strip().lower()
            if token_use != "access":
                return AuthResult(authenticated=False, reason="expected_access_token")
            allowed_client_ids = _allowed_client_ids()
            if not allowed_client_ids:
                return AuthResult(authenticated=False, reason="missing_allowed_client_ids")
            client_id = _resolve_client_id(claims)
            if client_id not in allowed_client_ids:
                return AuthResult(authenticated=False, reason="invalid_client_id")
            subject = str(claims.get("sub") or "").strip()
            if not subject:
                return AuthResult(authenticated=False, reason="missing_subject_claim")
            claims["client_id"] = client_id
            claims["token_use"] = "access"
            return AuthResult(
                authenticated=True,
                subject=subject,
                claims=claims,
                reason="cognito_access_token_verified",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cognito_verify_failed error=%s", exc)
            return AuthResult(authenticated=False, reason=f"cognito_verify_failed:{type(exc).__name__}")

