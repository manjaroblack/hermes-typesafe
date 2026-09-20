"""Supported-fork harness activation contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import ROOT

try:
    from harness import supports_reviewed_harness
except ModuleNotFoundError:
    from hermes_typesafe.harness import supports_reviewed_harness


CAPABILITIES = frozenset(
    {
        "pre_llm_call.model_switch.v1",
        "pre_tool_call.decision.v1",
        "skills.snapshot.v1",
    }
)


class SupportedContext:
    capabilities = CAPABILITIES

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any, str]] = []
        self.unload: list[Any] = []
        self.skills = [
            SimpleNamespace(
                name="demo",
                description="Demo procedure",
                excerpt="Use the demo procedure.",
            )
        ]

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_hook(self, name: str, callback: Any, *, phase: str = "normal") -> None:
        self.hooks.append((name, callback, phase))

    def on_unload(self, callback: Any) -> None:
        self.unload.append(callback)

    def register_skill(self, name: str, path: Path, **kwargs: Any) -> None:
        del kwargs
        assert name == "typesafe-system-one"
        assert path == ROOT / "skills" / "typesafe-system-one" / "SKILL.md"

    def skills_snapshot(self) -> Any:
        return SimpleNamespace(generation="generation-1", entries=tuple(self.skills))


def settings() -> dict[str, Any]:
    return {
        "suggestion.enabled": True,
        "guardrails.enabled": True,
        "routing.enabled": True,
        "routing.mode": "first_turn",
        "routing.models": {
            "cheap": {"model": "model-cheap", "provider": "provider-a"},
            "coding": {"model": "model-coding", "provider": "provider-a"},
        },
    }


def test_supported_host_registers_one_combined_llm_guard_and_final_hooks(plugin: Any) -> None:
    context = SupportedContext(settings())

    plugin.register(context)

    assert [name for name, _callback, _phase in context.hooks] == [
        "pre_llm_call",
        "pre_tool_call",
        "transform_llm_output",
    ]
    assert [phase for name, _callback, phase in context.hooks if name == "pre_tool_call"] == ["decision"]
    assert len(context.unload) == 1


def test_flags_on_without_complete_fork_capabilities_hold_all_harness_callbacks(plugin: Any) -> None:
    context = SupportedContext(settings())
    context.capabilities = frozenset()

    plugin.register(context)

    assert context.hooks == []
    assert [entry["name"] for entry in context.tools] == ["system_one"]


def test_variadic_kwargs_do_not_substitute_for_explicit_phase_support() -> None:
    class VariadicContext:
        capabilities = CAPABILITIES

        def register_hook(self, name: str, callback: Any, **kwargs: Any) -> None:
            del name, callback, kwargs

        def skills_snapshot(self) -> Any:
            return None

    assert supports_reviewed_harness(VariadicContext()) is False


@pytest.mark.parametrize("enabled", [False])
def test_all_harness_flags_off_registers_no_callbacks(plugin: Any, enabled: bool) -> None:
    config = {
        "suggestion.enabled": enabled,
        "guardrails.enabled": enabled,
        "routing.enabled": enabled,
        "routing.models": {},
        "routing.mode": "off",
    }
    context = SupportedContext(config)

    plugin.register(context)

    assert context.hooks == []
    assert len(context.unload) == 1
