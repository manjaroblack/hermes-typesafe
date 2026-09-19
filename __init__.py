"""Hermes TypeSafe native plugin with typed tool and advisory routing.

Guardrails and skill suggestion remain held on the inspected host. Routing is
an opt-in, current-message-only hint and never changes model or host state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

if __package__:
    from .build_identity import build_identity as _get_build_identity
    from .questions import (
        DEFAULT_MODEL,
        ROUTING_MODES,
        ROUTING_POOL_MAX,
        ROUTING_POOL_NAMES,
        default_settings as _default_settings,
    )
    from .runtime import runtime_status
    from .route import make_routing_handler
    from .skills_adapter import HELD_UNSUPPORTED_HOST, HeldSkillsAdapter
    from .tool_system_one import (
        API_KEY_ENV,
        SYSTEM_ONE_SCHEMA,
        _capture_home_identity,
        has_api_key,
        make_system_one_handler,
    )
else:  # pragma: no cover - pytest can collect a flat plugin root as ``__init__``
    from build_identity import build_identity as _get_build_identity
    from questions import (
        DEFAULT_MODEL,
        ROUTING_MODES,
        ROUTING_POOL_MAX,
        ROUTING_POOL_NAMES,
        default_settings as _default_settings,
    )
    from runtime import runtime_status
    from route import make_routing_handler
    from skills_adapter import HELD_UNSUPPORTED_HOST, HeldSkillsAdapter
    from tool_system_one import (
        API_KEY_ENV,
        SYSTEM_ONE_SCHEMA,
        _capture_home_identity,
        has_api_key,
        make_system_one_handler,
    )


_CONFIG_DEFAULTS = _default_settings()
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


def _bounded_routing_models(value: Any) -> dict[str, dict[str, str]]:
    """Detach the strict four-label routing map or return an inert pool."""

    if type(value) is not dict or len(value) > ROUTING_POOL_MAX:
        return {}
    if not value:
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for name, entry in value.items():
        if name not in ROUTING_POOL_NAMES or type(entry) is not dict or set(entry) != {"model", "provider"}:
            return {}
        model = entry.get("model")
        provider = entry.get("provider")
        if type(model) is not str or type(provider) is not str or not model or not provider:
            return {}
        try:
            model_bytes = model.encode("utf-8", errors="strict")
            provider_bytes = provider.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return {}
        if len(model_bytes) > 128 or len(provider_bytes) > 128:
            return {}
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in model + provider):
            return {}
        cleaned[name] = {"model": model, "provider": provider}
    return cleaned


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
            settings[key] = (
                value
                if type(value) is str and value in ROUTING_MODES
                else default
            )
        elif key == "routing.models":
            settings[key] = _bounded_routing_models(value)
        else:
            settings[key] = default
    return settings


def default_settings() -> dict[str, Any]:
    """Return the detached inert settings used by registration."""

    return _default_settings()


def build_identity() -> dict[str, Any]:
    """Expose source/build identity for offline packaging checks only."""

    return _get_build_identity()


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
    """Register the typed tool and optional advisory hook without persistence."""

    settings = _read_settings(ctx)
    home_identity = _capture_home_identity()
    handler = make_system_one_handler(settings, home_identity=home_identity)
    runtimes = [getattr(handler, "_typesafe_runtime", None)]
    route_handler = None
    on_unload = getattr(ctx, "on_unload", None)
    if callable(on_unload) and settings.get("routing.enabled") is True and settings.get("routing.mode") != "off":
        candidate = make_routing_handler(
            settings,
            home_identity=home_identity,
            require_home_identity=True,
        )
        if getattr(candidate, "_routing_pool", None) is not None:
            route_handler = candidate
            runtimes.append(getattr(candidate, "_typesafe_runtime", None))
        else:
            candidate_runtime = getattr(candidate, "_typesafe_runtime", None)
            if candidate_runtime is not None:
                candidate_runtime.close()

    def close_runtimes() -> None:
        for runtime in runtimes:
            if runtime is not None:
                runtime.close()

    if callable(on_unload):
        try:
            on_unload(close_runtimes)
        except Exception:
            close_runtimes()
            raise
    else:
        close_runtimes()
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
        register_hook = getattr(ctx, "register_hook", None)
        if route_handler is not None and callable(register_hook):
            register_hook("pre_llm_call", route_handler)
    except Exception:
        close_runtimes()
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
