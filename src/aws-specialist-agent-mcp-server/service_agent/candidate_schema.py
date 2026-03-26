from __future__ import annotations

import json
import re
from typing import Any

from service_agent.contracts import CandidateSet


def extract_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("empty candidate payload")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    start_positions = [index for index, char in enumerate(text) if char == "{"]  # small text; linear scan is fine here
    for start in start_positions:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
    raise ValueError("candidate payload does not contain a valid JSON object")


def parse_candidate_set(raw_payload: Any) -> CandidateSet:
    if isinstance(raw_payload, CandidateSet):
        return raw_payload
    if isinstance(raw_payload, str):
        raw_payload = extract_json_object(raw_payload)
    return CandidateSet.model_validate(raw_payload)
