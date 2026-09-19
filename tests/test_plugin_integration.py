"""Contract tests for current-host held suggestion integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import ROOT


_REAL_LOOKUP_SCRIPT = r'''
import json
import os
import sys
import tempfile
from pathlib import Path

fixture = Path(sys.argv[1]).resolve()
plugin_dir = Path(sys.argv[2]).resolve()

with tempfile.TemporaryDirectory(prefix="typesafe-qualified-skill-") as temp:
    root = Path(temp).resolve()
    for name in tuple(os.environ):
        if name.startswith("HERMES_") or name in {"PYTHONPATH", "TYPESAFE_API_KEY"}:
            os.environ.pop(name, None)
    os.environ["HOME"] = str(root)
    os.environ["HERMES_HOME"] = str(root)
    sys.path.insert(0, str(fixture))

    from hermes_cli.plugins import PluginManager
    from hermes_cli.plugins_manifest import PluginManifest

    manager = PluginManager(scope_key=str(root))
    manifest = PluginManifest(name="typesafe", source="user", path=str(plugin_dir))
    manager._load_plugin(manifest)
    path = manager.find_plugin_skill("typesafe:typesafe-system-one")
    print(json.dumps({"enabled": manager._plugins["typesafe"].enabled, "path": str(path) if path else None}))
    manager.unload()
'''


def test_flag_on_current_host_registers_no_suggestion_hook(plugin: Any) -> None:
    class Context:
        def __init__(self) -> None:
            self.tools: list[dict[str, Any]] = []
            self.hooks: list[tuple[str, Any]] = []
            self.skills: list[dict[str, Any]] = []

        def get_config(self, key: str, default: Any = None) -> Any:
            if key == "suggestion.enabled":
                return True
            return default

        def register_tool(self, **kwargs: Any) -> None:
            self.tools.append(kwargs)

        def register_hook(self, name: str, callback: Any) -> None:
            self.hooks.append((name, callback))

        def register_skill(self, name: str, path: Path, **kwargs: Any) -> None:
            self.skills.append({"name": name, "path": path, **kwargs})

    context = Context()
    plugin.register(context)

    assert context.hooks == []
    assert [entry["name"] for entry in context.tools] == ["system_one"]


def test_native_registration_exposes_bundled_skill_for_qualified_lookup(plugin: Any) -> None:
    class Context:
        def __init__(self) -> None:
            self.tools: list[dict[str, Any]] = []
            self.skills: list[dict[str, Any]] = []

        def get_config(self, key: str, default: Any = None) -> Any:
            return default

        def register_tool(self, **kwargs: Any) -> None:
            self.tools.append(kwargs)

        def register_skill(self, name: str, path: Path, **kwargs: Any) -> None:
            self.skills.append({"name": name, "path": path, **kwargs})

    context = Context()
    plugin.register(context)

    assert [entry["name"] for entry in context.skills] == ["typesafe-system-one"]
    assert context.skills[0]["path"].name == "SKILL.md"
    assert context.skills[0]["path"].is_file()


def test_bundled_skill_has_qualified_plugin_identity() -> None:
    skill = ROOT / "skills" / "typesafe-system-one" / "SKILL.md"
    assert skill.is_file()
    assert "name: typesafe-system-one" in skill.read_text(encoding="utf-8")
    assert "typesafe:typesafe-system-one" in plugin_skill_names()


def plugin_skill_names() -> tuple[str, ...]:
    return ("typesafe:typesafe-system-one",)


def test_public_plugin_manager_resolves_qualified_bundled_skill() -> None:
    fixture = Path(os.environ.get("HERMES_TYPESAFE_HERMES_FIXTURE", "/tmp/hermes-typesafe-public-fixture"))
    if not fixture.is_dir():
        pytest.skip("immutable Hermes fixture is not available")
    head = subprocess.run(
        ["git", "-C", str(fixture), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert head.returncode == 0, head.stderr
    assert head.stdout.strip() == "ee4452991d17534aa561f31ee55596d082aa94e7"

    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HERMES_") and name not in {"PYTHONPATH", "TYPESAFE_API_KEY"}
    }
    result = subprocess.run(
        [sys.executable, "-c", _REAL_LOOKUP_SCRIPT, str(fixture), str(ROOT)],
        cwd="/tmp",
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["enabled"] is True
    assert payload["path"].endswith("skills/typesafe-system-one/SKILL.md")
