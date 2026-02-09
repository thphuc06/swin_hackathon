from __future__ import annotations

from typing import Any, Dict

from jsonschema import Draft202012Validator

INTENT_ENUM = ["summary", "risk", "planning", "scenario", "invest", "out_of_scope"]

INTENT_EXTRACTION_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "intent", "confidence", "top2", "slots", "reason"],
    "properties": {
        "schema_version": {"const": "intent_extraction_v1"},
        "intent": {"type": "string", "enum": INTENT_ENUM},
        "sub_intent": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "domain_relevance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "top2": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["intent", "score"],
                "properties": {
                    "intent": {"type": "string", "enum": INTENT_ENUM},
                    "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "additionalProperties": False,
            },
        },
        "slots": {"type": "object"},
        "scenario_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "additionalProperties": False,
}

_validator = Draft202012Validator(INTENT_EXTRACTION_JSON_SCHEMA)


def validate_intent_extraction_payload(payload: Dict[str, Any]) -> list[str]:
    errors = sorted(_validator.iter_errors(payload), key=lambda item: list(item.path))
    messages: list[str] = []
    for item in errors:
        path = ".".join(str(part) for part in item.path)
        location = path if path else "$"
        messages.append(f"{location}: {item.message}")
    return messages
