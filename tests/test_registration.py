"""RED contract for TypeSafe C foundation registration and packaging."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import ROOT


PUBLIC_HERMES_SHA = "ee4452991d17534aa561f31ee55596d082aa94e7"
PUBLIC_HERMES_FIXTURE = "/tmp/hermes-typesafe-public-fixture"


@pytest.mark.usefixtures("plugin")
def test_manifest_declares_only_the_registered_tool_and_required_secret() -> None:
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: typesafe" in manifest
    assert "requires_env:" in manifest
    assert "TYPESAFE_API_KEY" in manifest
    assert "provides_tools:" in manifest
    assert "system_one" in manifest
    assert "provides_hooks: []" in manifest
    assert "pre_tool_call" not in manifest
    assert "transform_llm_output" not in manifest
    assert "capabilities:" not in manifest


def test_register_reads_only_plugin_relative_defaults_and_registers_no_hooks(
    plugin: Any, recording_context: Any
) -> None:
    plugin.register(recording_context)

    assert [entry["name"] for entry in recording_context.tools] == ["system_one"]
    assert recording_context.hooks == []
    assert recording_context.set_config_calls == []
    assert all(not key.startswith("plugins.") for key in recording_context.config_reads)
    assert set(recording_context.config_reads) == {
        "model",
        "suggestion.enabled",
        "guardrails.enabled",
        "routing.enabled",
        "routing.mode",
        "routing.models",
    }


def test_missing_and_blank_keys_fail_closed_without_environment_fallback(
    plugin: Any, recording_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugin.tool_system_one, "_read_scoped_secret", lambda: None)
    plugin.register(recording_context)
    check_fn = recording_context.tools[0]["check_fn"]
    assert check_fn() is False

    monkeypatch.setattr(plugin.tool_system_one, "_read_scoped_secret", lambda: "   ")
    assert check_fn() is False
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


def test_present_synthetic_key_exposes_mixed_typed_schema_without_fake_answer(
    plugin: Any, recording_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugin.tool_system_one, "_read_scoped_secret", lambda: "synthetic-key")
    plugin.register(recording_context)
    entry = recording_context.tools[0]

    assert entry["check_fn"]() is True
    schema = entry["schema"]
    question_schema = schema["properties"]["questions"]["additionalProperties"]
    kinds = {
        variant["properties"]["type"]["const"]
        for variant in question_schema["oneOf"]
    }
    assert kinds == {"noul", "choice", "score"}
    assert entry["toolset"] == "typesafe"

    result = entry["handler"]({"state": "synthetic", "questions": {}})
    assert result["error"]["code"] == "runtime_unavailable"
    assert "answers" not in result
    assert "synthetic-key" not in json.dumps(result)


def test_import_and_registration_do_not_start_network_client_or_thread(
    plugin: Any, recording_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import threading

    class ForbiddenSocket:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("registration attempted network access")

    class ForbiddenThread:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("registration attempted thread creation")

    monkeypatch.setattr(socket, "socket", ForbiddenSocket)
    monkeypatch.setattr(threading, "Thread", ForbiddenThread)
    before = set(sys.modules)
    plugin.register(recording_context)
    assert "typesafe_sdk" not in set(sys.modules) - before


def test_default_settings_are_inert_and_centralized_in_questions(plugin: Any) -> None:
    settings = plugin.default_settings()

    assert settings == {
        "model": "jev-1.13.0",
        "suggestion.enabled": False,
        "guardrails.enabled": False,
        "routing.enabled": False,
        "routing.mode": "first_turn",
        "routing.models": {},
    }
    assert plugin.questions.GUARD_HIGH == 0.80
    assert plugin.questions.GUARD_MEDIUM == 0.50
    assert plugin.questions.SUGGESTION_SHORTLIST == 3
    assert plugin.questions.SUGGESTION_EXCERPT_CHARS == 700


def test_source_build_identity_is_reproducible(plugin: Any) -> None:
    identity = plugin.build_identity()

    assert identity["abi"] == "typesafe-broker-v1"
    assert len(identity["build_sha256"]) == 64
    assert all(char in "0123456789abcdef" for char in identity["build_sha256"])


def test_flat_source_import_without_package_context_is_safe() -> None:
    script = "import runpy; runpy.run_path('__init__.py', run_name='__init__')"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_ci_pins_and_requires_public_hermes_fixture_on_python_312() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert PUBLIC_HERMES_SHA in workflow
    assert "Fetch immutable Hermes integration fixture" in workflow
    assert f"git init {PUBLIC_HERMES_FIXTURE}" in workflow
    assert "if: matrix.python-version == '3.12'" in workflow
    assert f"HERMES_TYPESAFE_HERMES_FIXTURE: {PUBLIC_HERMES_FIXTURE}" in workflow
    assert "HERMES_TYPESAFE_REQUIRE_FIXTURE:" in workflow


def test_real_namespaced_plugin_manager_loads_and_unloads_in_isolation() -> None:
    if sys.version_info < (3, 11):
        pytest.skip("public Hermes fixture integration requires Python >=3.11")
    fixture = Path(os.environ.get("HERMES_TYPESAFE_HERMES_FIXTURE", PUBLIC_HERMES_FIXTURE))
    fixture_required = os.environ.get("HERMES_TYPESAFE_REQUIRE_FIXTURE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if not fixture.is_dir():
        if fixture_required:
            pytest.fail("required immutable Hermes fixture is not available")
        pytest.skip("immutable Hermes fixture is not available")

    fixture_head = subprocess.run(
        ["git", "-C", str(fixture), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert fixture_head.returncode == 0, fixture_head.stderr
    assert fixture_head.stdout.strip() == PUBLIC_HERMES_SHA

    script = r'''
import json
import os
import sys
import tempfile
from pathlib import Path

fixture = Path(sys.argv[1])
plugin_dir = Path(sys.argv[2])

with tempfile.TemporaryDirectory(prefix="typesafe-hermes-home-") as home:
    isolated_home = Path(home)
    for name in tuple(os.environ):
        if name.startswith("HERMES_") or name in {"PYTHONPATH", "TYPESAFE_API_KEY"}:
            os.environ.pop(name, None)
    os.environ["HOME"] = str(isolated_home)
    os.environ["HERMES_HOME"] = str(isolated_home)
    assert Path.home() == isolated_home
    assert not any(name.startswith("HERMES_KANBAN_") for name in os.environ)

    sys.path.insert(0, str(fixture))
    from hermes_cli.plugins import PluginManager
    from hermes_cli.plugins_manifest import PluginManifest

    manager = PluginManager(scope_key=str(isolated_home))
    manifest = PluginManifest(name="typesafe", source="user", path=str(plugin_dir))
    manager._load_plugin(manifest)
    loaded = manager._plugins["typesafe"]
    module_names = sorted(name for name in sys.modules if name.startswith("hermes_plugins.typesafe"))
    result = {
        "enabled": loaded.enabled,
        "error": loaded.error,
        "tools": loaded.tools_registered,
        "hooks": loaded.hooks_registered,
        "module_names": module_names,
    }
    manager.unload()
    print(json.dumps(result, sort_keys=True))
'''
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HERMES_") and name not in {"PYTHONPATH", "TYPESAFE_API_KEY"}
    }
    result = subprocess.run(
        [sys.executable, "-c", script, str(fixture), str(ROOT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["enabled"] is True
    assert payload["error"] is None
    assert payload["tools"] == ["system_one"]
    assert payload["hooks"] == []
    assert payload["module_names"]
    assert all(name.startswith("hermes_plugins.typesafe") for name in payload["module_names"])
