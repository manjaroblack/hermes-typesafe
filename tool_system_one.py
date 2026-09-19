"""Offline system_one registration contract for the foundation release."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


API_KEY_ENV = "TYPESAFE_API_KEY"
TOOL_NAME = "system_one"

# The schema is deliberately self-contained: no other Hermes tool names or
# provider-specific schema references are exposed to the model.
_NOUl = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "noul"},
        "instructions": {"type": "string", "minLength": 1},
        "criteria": {"type": "boolean"},
    },
    "required": ["type", "instructions"],
}
_CHOICE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "choice"},
        "instructions": {"type": "string", "minLength": 1},
        "criteria": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"type": "string"},
        },
    },
    "required": ["type", "instructions", "criteria"],
}
_SCORE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "score"},
        "instructions": {"type": "string", "minLength": 1},
        "criteria": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string"},
        },
    },
    "required": ["type", "instructions", "criteria"],
}

QUESTION_SCHEMA = {"oneOf": [_NOUl, _CHOICE, _SCORE]}

SYSTEM_ONE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "state": {
            "oneOf": [
                {"type": "string"},
                {"type": "object"},
                {"type": "array"},
            ],
        },
        "questions": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": QUESTION_SCHEMA,
        },
        "model": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["state", "questions"],
}



def _read_scoped_secret() -> str | None:
    """Read the one host-provided secret through Hermes' scoped seam.

    Import and lookup are deferred until the host asks whether the tool is
    available. There is intentionally no environment fallback: an unscoped or
    unavailable secret seam makes the tool unavailable.
    """

    try:
        from agent.secret_scope import get_secret
    except Exception:
        return None
    try:
        value = get_secret(API_KEY_ENV, None)
    except Exception:
        return None
    return value if isinstance(value, str) else None



def has_api_key() -> bool:
    """Return whether a non-blank scoped TypeSafe key is available."""

    value = _read_scoped_secret()
    return bool(value and value.strip())



def system_one(arguments: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    """Return the honest C-phase response without creating a client or RPC."""

    del arguments
    return {
        "error": {
            "code": "runtime_unavailable",
            "message": (
                "TypeSafe runtime is unavailable in the foundation release; "
                "no inference was attempted."
            ),
        }
    }
