"""Hermes TypeSafe native plugin foundation.

Only the typed tool registration exists in this phase. Guardrails, suggestion,
routing, and provider execution are intentionally held or deferred.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .build_identity import build_identity as _build_identity
from .questions import default_settings as _default_settings
from .questions import DEFAULT_MODEL
from .runtime import runtime_status
from .tool_system_one import API_KEY_ENV, SYSTEM_ONE_SCHEMA, has_api_key, system_one


_CONFIG_DEFAULTS = _default_settings()
_ROUTING_MODES = {"off", "first_turn", "cache_break_if_worth_it"}


def _config_value(ctx: Any, key: str, default: Any) -> Any:
    try:
        value = ctx.get_config(key, default)
    except Exception:
        return default
    return value


def _read_settings(ctx: Any) -> dict[str, Any]:
    """Read only this plugin's relative settings, falling back inertly."""

    settings: dict[str, Any] = {}
    for key, default in _CONFIG_DEFAULTS.items():
        value = _config_value(ctx, key, default)
        if key == "model":
            settings[key] = value.strip() if isinstance(value, str) and value.strip() else DEFAULT_MODEL
        elif key.endswith(".enabled"):
            settings[key] = value if isinstance(value, bool) else default
        elif key == "routing.mode":
            settings[key] = value if isinstance(value, str) and value in _ROUTING_MODES else default
        elif key == "routing.models":
            settings[key] = dict(value) if isinstance(value, Mapping) else {}
        else:
            settings[key] = default
    return settings


def default_settings() -> dict[str, Any]:
    """Return the detached inert settings used by registration."""

    return _default_settings()


def build_identity() -> dict[str, Any]:
    """Expose source/build identity for offline packaging checks only."""

    return _build_identity()


def register(ctx: Any) -> None:
    """Register the one honest tool without hooks, persistence, or side effects."""

    _read_settings(ctx)
    ctx.register_tool(
        name="system_one",
        toolset="typesafe",
        schema=SYSTEM_ONE_SCHEMA,
        handler=system_one,
        check_fn=has_api_key,
        requires_env=[API_KEY_ENV],
        is_async=False,
        description=(
            "Run a typed TypeSafe decision batch when the reviewed runtime is available. "
            "The foundation release reports runtime_unavailable."
        ),
    )


__all__ = [
    "API_KEY_ENV",
    "SYSTEM_ONE_SCHEMA",
    "build_identity",
    "default_settings",
    "register",
    "runtime_status",
]
