from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict


def new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:8]}"


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def new_call_id(prefix: str = "call") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_idempotency_key(*, namespace: str, payload: Dict[str, Any], trace_id: str) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(f"{namespace}|{trace_id}|{encoded}".encode("utf-8")).hexdigest()
    return digest[:32]

