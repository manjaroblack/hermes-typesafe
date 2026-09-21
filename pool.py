"""Shared bounded normalization for the closed routing pool."""

from __future__ import annotations

from typing import Any

try:
    from .limits import MAX_MODEL_BYTES
    from .questions import ROUTING_EFFORT_LEVELS, ROUTING_POOL_MAX, ROUTING_POOL_NAMES
except ImportError:  # pragma: no cover - flat plugin import
    from limits import MAX_MODEL_BYTES
    from questions import ROUTING_EFFORT_LEVELS, ROUTING_POOL_MAX, ROUTING_POOL_NAMES


REASONING_EFFORT_TOKENS = ROUTING_EFFORT_LEVELS


def _bounded_identifier(value: Any) -> str | None:
    if type(value) is not str or not value:
        return None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if len(encoded) > MAX_MODEL_BYTES:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    return value


def _normalized_effort(entry: dict[str, Any]) -> dict[str, Any]:
    allowed = entry.get("reasoning_allowed")
    default = entry.get("reasoning_default")
    if type(allowed) is not list or not allowed:
        return {}
    if any(type(token) is not str or token not in REASONING_EFFORT_TOKENS for token in allowed):
        return {}
    if len(set(allowed)) != len(allowed):
        return {}
    if type(default) is not str or default not in allowed:
        return {}
    return {"reasoning_allowed": list(allowed), "reasoning_default": default}


def normalize_routing_pool(value: Any) -> dict[str, dict[str, Any]] | None:
    """Detach valid identities and optional effort settings from a pool map."""

    if type(value) is not dict or not value or len(value) > ROUTING_POOL_MAX:
        return None
    cleaned: dict[str, dict[str, Any]] = {}
    for name, entry in value.items():
        if type(name) is not str or name not in ROUTING_POOL_NAMES:
            return None
        if type(entry) is not dict:
            return None
        model = _bounded_identifier(entry.get("model"))
        provider = _bounded_identifier(entry.get("provider"))
        if model is None or provider is None:
            return None
        normalized = {"model": model, "provider": provider}
        normalized.update(_normalized_effort(entry))
        cleaned[name] = normalized
    identities = {(entry["model"], entry["provider"]) for entry in cleaned.values()}
    if len(identities) != len(cleaned):
        return None
    return cleaned


def reasoning_effort_union(pool: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    """Return the product-ordered union of enabled label effort lists."""

    return tuple(
        token
        for token in REASONING_EFFORT_TOKENS
        if any(token in entry.get("reasoning_allowed", []) for entry in pool.values())
    )


__all__ = ["REASONING_EFFORT_TOKENS", "normalize_routing_pool", "reasoning_effort_union"]
