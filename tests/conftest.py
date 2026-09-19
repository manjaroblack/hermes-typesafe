"""Offline registration fixtures for the native TypeSafe plugin."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Generator

import pytest


ROOT = Path(__file__).resolve().parents[1]


class RecordingContext:
    """Small PluginContext seam that records only registration behavior."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.config_reads: list[str] = []
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []
        self.set_config_calls: list[tuple[str, Any]] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        self.config_reads.append(key)
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        self.set_config_calls.append((key, value))
        raise AssertionError("registration must not persist plugin configuration")

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_hook(self, hook_name: str, callback: Any) -> None:
        self.hooks.append((hook_name, callback))


@pytest.fixture
def recording_context() -> RecordingContext:
    return RecordingContext()


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch) -> Generator[ModuleType, None, None]:
    """Load the flat repository package under its distribution import name."""

    for name in tuple(sys.modules):
        if name == "hermes_typesafe" or name.startswith("hermes_typesafe."):
            del sys.modules[name]

    spec = importlib.util.spec_from_file_location(
        "hermes_typesafe",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not construct source package spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hermes_typesafe"] = module
    spec.loader.exec_module(module)
    yield module

    for name in tuple(sys.modules):
        if name == "hermes_typesafe" or name.startswith("hermes_typesafe."):
            del sys.modules[name]
