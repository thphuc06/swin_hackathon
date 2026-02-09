from __future__ import annotations

from typing import Any, Dict

from jsonschema import Draft202012Validator

LANGUAGE_ENUM = ["vi", "en"]

ANSWER_PLAN_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "language",
        "summary_lines",
        "key_metrics",
        "actions",
        "assumptions",
        "limitations",
        "disclaimer",
        "used_fact_ids",
        "used_insight_ids",
        "used_action_ids",
    ],
    "properties": {
        "schema_version": {"const": "answer_plan_v2"},
        "language": {"type": "string", "enum": LANGUAGE_ENUM},
        "summary_lines": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {"type": "string", "minLength": 1},
        },
        "key_metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["fact_id"],
                "properties": {
                    "fact_id": {"type": "string", "minLength": 1},
                    "label": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1},
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "disclaimer": {"type": "string", "minLength": 1},
        "used_fact_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "used_insight_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "used_action_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
    "additionalProperties": False,
}

_answer_plan_validator = Draft202012Validator(ANSWER_PLAN_JSON_SCHEMA)


def validate_answer_plan_payload(payload: Dict[str, Any]) -> list[str]:
    errors = sorted(_answer_plan_validator.iter_errors(payload), key=lambda item: list(item.path))
    messages: list[str] = []
    for item in errors:
        path = ".".join(str(part) for part in item.path)
        location = path if path else "$"
        messages.append(f"{location}: {item.message}")
    return messages
