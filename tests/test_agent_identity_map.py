from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from identity_map import IdentityContractError, clear_user_id_map_cache, resolve_runtime_user_ids


@contextmanager
def temp_env(**updates):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_user_id_map_cache()
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_user_id_map_cache()


class AgentIdentityMapTests(unittest.TestCase):
    def test_authenticated_subject_is_the_runtime_data_user_id(self) -> None:
        subject = "11111111-2222-3333-4444-555555555555"
        with temp_env():
            actor_id, data_user_id = resolve_runtime_user_ids(
                payload_user_id=None,
                auth_subject=subject,
            )

        self.assertEqual(subject, actor_id)
        self.assertEqual(subject, data_user_id)

    def test_payload_user_id_mismatch_is_rejected(self) -> None:
        with temp_env():
            with self.assertRaises(IdentityContractError):
                resolve_runtime_user_ids(
                    payload_user_id="spoofed-user-id",
                    auth_subject="real-cognito-subject",
                )

    def test_missing_authenticated_subject_is_rejected(self) -> None:
        with temp_env():
            with self.assertRaises(IdentityContractError):
                resolve_runtime_user_ids(
                    payload_user_id="seeded-user-id",
                    auth_subject="",
                )


if __name__ == "__main__":
    unittest.main()
