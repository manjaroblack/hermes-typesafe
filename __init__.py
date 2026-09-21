"""Hermes TypeSafe native plugin with typed tool and capability-gated hooks.

The reviewed harness activates only on the complete fork capability set; the
current host remains inert without those markers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

if __package__:
    from .build_identity import build_identity as _get_build_identity
    from .questions import (
        DEFAULT_MODEL,
        ROUTING_MODES,
        default_settings as _default_settings,
    )
    from .pool import normalize_routing_pool
    from .runtime import TypeSafeRuntime, runtime_status
    from .harness import (
        _eligible_routing_pool,
        make_combined_pre_llm_handler,
        make_final_guard_handler,
        make_pre_tool_guard_handler,
        register_hook_checked,
        supports_reviewed_harness,
    )
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
        default_settings as _default_settings,
    )
    from pool import normalize_routing_pool
    from runtime import TypeSafeRuntime, runtime_status
    from harness import (
        _eligible_routing_pool,
        make_combined_pre_llm_handler,
        make_final_guard_handler,
        make_pre_tool_guard_handler,
        register_hook_checked,
        supports_reviewed_harness,
    )
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


def _bounded_routing_models(value: Any) -> dict[str, dict[str, Any]]:
    """Detach the bounded routing map or return an inert pool."""

    return normalize_routing_pool(value) or {}


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
                else _CONFIG_DEFAULTS["routing.mode"]
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
    """Register the typed tool and capability-gated reviewed callbacks without persistence."""

    settings = _read_settings(ctx)
    home_identity = _capture_home_identity()
    handler = make_system_one_handler(settings, home_identity=home_identity)
    runtimes = [getattr(handler, "_typesafe_runtime", None)]
    if supports_reviewed_harness(ctx):
        harness_runtime = None
        pre_llm_enabled = (
            settings.get("suggestion.enabled") is True
            or _eligible_routing_pool(settings) is not None
        )
        harness_settings_enabled = pre_llm_enabled or settings.get("guardrails.enabled") is True
        if harness_settings_enabled:
            harness_runtime = TypeSafeRuntime(
                settings=settings,
                home_identity=home_identity,
                require_home_identity=True,
            )
            runtimes.append(harness_runtime)
        if harness_runtime is not None and pre_llm_enabled:
            combined = make_combined_pre_llm_handler(
                settings,
                snapshot_reader=getattr(ctx, "skills_snapshot", None),
                runtime=harness_runtime,
                home_identity=home_identity,
                require_home_identity=True,
            )
            register_hook_checked(ctx, "pre_llm_call", combined)
        if harness_runtime is not None and settings.get("guardrails.enabled") is True:
            pre_tool = make_pre_tool_guard_handler(
                settings,
                runtime=harness_runtime,
                home_identity=home_identity,
                require_home_identity=True,
            )
            final = make_final_guard_handler(
                settings,
                runtime=harness_runtime,
                home_identity=home_identity,
                require_home_identity=True,
            )
            register_hook_checked(ctx, "pre_tool_call", pre_tool, phase="decision")
            register_hook_checked(ctx, "transform_llm_output", final)
    on_unload = getattr(ctx, "on_unload", None)

    def close_runtimes() -> None:
        seen: set[int] = set()
        for runtime in runtimes:
            if runtime is not None and id(runtime) not in seen:
                seen.add(id(runtime))
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
                "Capability-gated hooks remain inert when the fork markers are absent."
            ),
        )
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
