"""Single source of built-in TypeSafe questions and decision thresholds."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_MODEL = "jev-1.13.0"

# Guard and routing values are intentionally centralized here. Later feature phases
# import these names instead of repeating policy literals in callbacks.
GUARD_HIGH = 0.80
GUARD_MEDIUM = 0.50
SUGGESTION_GATE = 0.30
SUGGESTION_FITS = 0.30
SUGGESTION_SHORTLIST = 3
SUGGESTION_EXCERPT_CHARS = 700
ROUTING_HIGH = 0.80

GUARD_CHECKS = (
    "jailbreak_injection",
    "credential_exfiltration",
    "destructive_action",
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "model": DEFAULT_MODEL,
    "suggestion.enabled": False,
    "guardrails.enabled": False,
    "routing.enabled": False,
    "routing.mode": "first_turn",
    "routing.models": {},
}


def default_settings() -> dict[str, Any]:
    """Return a detached copy of inert plugin settings."""

    return deepcopy(DEFAULT_SETTINGS)
