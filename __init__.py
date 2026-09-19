"""Hermes TypeSafe native plugin foundation.

Only the typed tool and the inert bundled-skill registration exist in this
phase. Guardrails, suggestion, routing, and provider execution are otherwise
intentionally held or deferred.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

if __package__:
    from .build_identity import build_identity as _build_identity
    from .questions import default_settings as _default_settings
    from .questions import DEFAULT_MODEL
    from .runtime import runtime_status
    from .skills_adapter import HELD_UNSUPPORTED_HOST, HeldSkillsAdapter
    from .tool_system_one import (
        API_KEY_ENV,
        SYSTEM_ONE_SCHEMA,
        _capture_home_identity,
        has_api_key,
        make_system_one_handler,
    )
else:  # pragma: no cover - pytest can collect a flat plugin root as ``__init__``
    from build_identity import build_identity as _build_identity
    from questions import DEFAULT_MODEL, default_settings as _default_settings
    from runtime import runtime_status
    from skills_adapter import HELD_UNSUPPORTED_HOST, HeldSkillsAdapter
    from tool_system_one import (
        API_KEY_ENV,
        SYSTEM_ONE_SCHEMA,
        _capture_home_identity,
        has_api_key,
        make_system_one_handler,
    )


_CONFIG_DEFAULTS = _default_settings()
_ROUTING_MODES = {"off", "first_turn", "cache_break_if_worth_it"}


def _config_value(ctx: Any, key: str, default: Any) -> Any:
    try:
        value = ctx.get_config(key, default)
    except Exception:
        return default
    return value


def _bounded_model_setting(value: Any) -> str:
    if type(value) is not str or len(value) > 128:
        return DEFAULT_MODEL
    stripped = value.strip()
    if not stripped:
        return DEFAULT_MODEL
    try:
        if len(stripped.encode("utf-8", errors="strict")) > 128:
            return DEFAULT_MODEL
    except UnicodeEncodeError:
        return DEFAULT_MODEL
    return stripped


def _read_settings(ctx: Any) -> dict[str, Any]:
    """Read only this plugin's relative settings, falling back inertly."""

    settings: dict[str, Any] = {}
    for key, default in _CONFIG_DEFAULTS.items():
        value = _config_value(ctx, key, default)
        if key == "model":
            settings[key] = _bounded_model_setting(value)
        elif key.endswith(".enabled"):
            settings[key] = value if type(value) is bool else default
        elif key == "routing.mode":
            settings[key] = value if type(value) is str and value in _ROUTING_MODES else default
        elif key == "routing.models":
            if type(value) is dict:
                cleaned_models: dict[str, str] = {}
                for model_name, model in value.items():
                    if len(cleaned_models) >= 16:
                        break
                    if (
                        type(model_name) is str
                        and type(model) is str
                        and model_name
                        and model
                        and len(model_name) <= 128
                        and len(model) <= 128
                    ):
                        cleaned_models[model_name] = model
                settings[key] = cleaned_models
            else:
                settings[key] = {}
        else:
            settings[key] = default
    return settings


def default_settings() -> dict[str, Any]:
    """Return the detached inert settings used by registration."""

    return _default_settings()


def build_identity() -> dict[str, Any]:
    """Expose source/build identity for offline packaging checks only."""

    return _build_identity()


def _register_bundled_skill(ctx: Any) -> None:
    """Register the shipped skill when the native context exposes that seam."""

    register_skill = getattr(ctx, "register_skill", None)
    if not callable(register_skill):
        return
    skill_path = Path(__file__).parent / "skills" / "typesafe-system-one" / "SKILL.md"
    if not skill_path.is_file():
        return
    register_skill("typesafe-system-one", skill_path)


def register(ctx: Any) -> None:
    """Register the one honest tool without hooks, persistence, or side effects."""

    settings = _read_settings(ctx)
    home_identity = _capture_home_identity()
    handler = make_system_one_handler(settings, home_identity=home_identity)
    on_unload = getattr(ctx, "on_unload", None)
    runtime = getattr(handler, "_typesafe_runtime", None)
    if runtime is not None and not callable(on_unload):
        runtime.close()
    elif callable(on_unload) and runtime is not None:
        try:
            on_unload(runtime.close)
        except Exception:
            runtime.close()
            raise
    try:
        _register_bundled_skill(ctx)
        ctx.register_tool(
            name="system_one",
            toolset="typesafe",
            schema=SYSTEM_ONE_SCHEMA,
            handler=handler,
            check_fn=lambda: has_api_key(
                home_identity=home_identity,
                require_home_identity=home_identity is not None,
            ),
            requires_env=[API_KEY_ENV],
            is_async=False,
            description=(
                "Run a typed TypeSafe decision batch when the reviewed runtime is available. "
                "Suggestion and guardrails remain held on this host."
            ),
        )
    except Exception:
        if runtime is not None:
            runtime.close()
        raise


__all__ = [
    "API_KEY_ENV",
    "HELD_UNSUPPORTED_HOST",
    "SYSTEM_ONE_SCHEMA",
    "HeldSkillsAdapter",
    "build_identity",
    "default_settings",
    "register",
    "runtime_status",
]
