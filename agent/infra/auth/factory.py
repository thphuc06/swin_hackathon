from __future__ import annotations

from core.settings import AUTH_PROVIDER

from .cognito_provider import CognitoAuthProvider
from .jwt_provider import JwtAuthProvider


_AUTH_PROVIDER = None


def get_auth_provider():
    global _AUTH_PROVIDER
    if _AUTH_PROVIDER is not None:
        return _AUTH_PROVIDER
    provider = str(AUTH_PROVIDER or "").strip().lower()
    if provider == "cognito":
        _AUTH_PROVIDER = CognitoAuthProvider()
    elif provider == "jwt":
        _AUTH_PROVIDER = JwtAuthProvider()
    else:
        raise RuntimeError(f"Unsupported AUTH_PROVIDER '{provider}'.")
    return _AUTH_PROVIDER

