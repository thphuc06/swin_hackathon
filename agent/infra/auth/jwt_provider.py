from __future__ import annotations

import base64
import json
from typing import Any, Dict

from core.settings import AUTH_DEV_BYPASS

from .provider import AuthResult


def _decode_payload_without_verify(token: str) -> Dict[str, Any]:
    segments = token.split(".")
    if len(segments) < 2:
        return {}
    payload_b64 = segments[1]
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    payload_bytes = base64.urlsafe_b64decode((payload_b64 + padding).encode("utf-8"))
    payload_obj = json.loads(payload_bytes.decode("utf-8"))
    return payload_obj if isinstance(payload_obj, dict) else {}


class JwtAuthProvider:
    """Lightweight provider for local/dev non-Cognito auth."""

    def verify(self, authorization: str | None) -> AuthResult:
        if AUTH_DEV_BYPASS:
            return AuthResult(
                authenticated=True,
                subject="demo-user",
                claims={"sub": "demo-user", "scope": "dev:bypass"},
                reason="auth_dev_bypass",
            )

        if not authorization or not str(authorization).strip():
            return AuthResult(authenticated=False, reason="missing_authorization")
        token_value = str(authorization).strip()
        if token_value.lower().startswith("bearer "):
            token_value = token_value[7:].strip()
        if not token_value:
            return AuthResult(authenticated=False, reason="missing_token")
        try:
            claims = _decode_payload_without_verify(token_value)
            subject = str(claims.get("sub") or claims.get("username") or "").strip()
            if not subject:
                subject = "anonymous"
            return AuthResult(authenticated=True, subject=subject, claims=claims, reason="jwt_unverified_decode")
        except Exception:  # noqa: BLE001
            return AuthResult(authenticated=False, reason="invalid_jwt_payload")

