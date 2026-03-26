from __future__ import annotations

from typing import Tuple


class IdentityContractError(ValueError):
    """Raised when the runtime identity envelope violates the P0 contract."""


def clear_user_id_map_cache() -> None:
    """Compatibility no-op after removing env-based identity remapping."""


def resolve_data_user_id(actor_id: str) -> str:
    return str(actor_id or "").strip()


def resolve_runtime_user_ids(*, payload_user_id: str | None, auth_subject: str | None) -> Tuple[str, str]:
    normalized_payload_user_id = str(payload_user_id or "").strip()
    normalized_auth_subject = str(auth_subject or "").strip()

    if not normalized_auth_subject:
        raise IdentityContractError("Authenticated subject is required to resolve runtime user identity.")

    if normalized_payload_user_id and normalized_payload_user_id != normalized_auth_subject:
        raise IdentityContractError("payload user_id must match the authenticated subject.")

    return normalized_auth_subject, normalized_auth_subject
