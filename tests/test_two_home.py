"""Installed-wheel, real Hermes PluginManager two-home integration lane."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

PUBLIC_HERMES_SHA = "ee4452991d17534aa561f31ee55596d082aa94e7"
PUBLIC_HERMES_FIXTURE = "/tmp/hermes-typesafe-public-fixture"


_TWO_HOME_SCRIPT = r'''
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

fixture = Path(sys.argv[1]).resolve()
package_dir = Path(sys.argv[2]).resolve()

with tempfile.TemporaryDirectory(prefix="typesafe-two-home-") as temp:
    root = Path(temp).resolve()
    home_a = root / "home-a"
    home_b = root / "home-b"
    home_a.mkdir()
    home_b.mkdir()
    plugin_a = home_a / "plugins" / "typesafe"
    plugin_b = home_b / "plugins" / "typesafe"
    shutil.copytree(package_dir, plugin_a)
    shutil.copytree(package_dir, plugin_b)
    for name in tuple(os.environ):
        if name.startswith("HERMES_") or name in {"PYTHONPATH", "TYPESAFE_API_KEY"}:
            os.environ.pop(name, None)
    os.environ["HOME"] = str(root)
    sys.path.insert(0, str(fixture))

    from agent.secret_scope import reset_secret_scope, set_multiplex_active, set_secret_scope
    from hermes_cli.plugins import PluginManager
    from hermes_cli.plugins_manifest import PluginManifest
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.registry import registry

    set_multiplex_active(True)
    manifest_a = PluginManifest(name="typesafe", source="user", path=str(plugin_a))
    manifest_b = PluginManifest(name="typesafe", source="user", path=str(plugin_b))
    manager_a = PluginManager(scope_key=str(home_a))
    manager_b = PluginManager(scope_key=str(home_b))
    thread_ids_before = {thread.ident for thread in threading.enumerate()}
    manager_a._load_plugin(manifest_a)
    manager_b._load_plugin(manifest_b)
    thread_ids_after_register = {thread.ident for thread in threading.enumerate()}

    loaded_a = manager_a._plugins["typesafe"]
    loaded_b = manager_b._plugins["typesafe"]
    assert loaded_a.enabled and loaded_b.enabled
    assert loaded_a.error is None and loaded_b.error is None
    assert loaded_a.tools_registered == ["system_one"]
    assert loaded_b.tools_registered == ["system_one"]
    assert thread_ids_after_register == thread_ids_before
    assert "typesafe_sdk" not in sys.modules
    assert loaded_a.module.__name__ == "hermes_plugins.typesafe"
    assert loaded_b.module.__name__.startswith("hermes_plugins.typesafe__home_")
    assert loaded_a.module.__name__ != loaded_b.module.__name__
    assert loaded_a.manifest.path == str(plugin_a)
    assert loaded_b.manifest.path == str(plugin_b)
    assert Path(loaded_a.module.__file__).is_relative_to(plugin_a)
    assert Path(loaded_b.module.__file__).is_relative_to(plugin_b)
    assert loaded_a.module.__file__ != loaded_b.module.__file__

    entry_a = registry.get_entry("system_one", scope=manager_a.scope_key)
    entry_b = registry.get_entry("system_one", scope=manager_b.scope_key)
    assert entry_a is not None and entry_b is not None
    handler_a = entry_a.handler
    handler_b = entry_b.handler
    runtime_a = handler_a._typesafe_runtime
    runtime_b = handler_b._typesafe_runtime
    assert runtime_a._broker is None and runtime_b._broker is None

    class FakeClient:
        calls: list[tuple[str, str]] = []
        lock = threading.Lock()
        normal_started = threading.Event()
        normal_release = threading.Event()
        normal_count = 0
        stuck_started = threading.Event()
        stuck_cancelled = threading.Event()
        stuck_release = threading.Event()
        saturated_started = threading.Event()
        saturated_release = threading.Event()
        saturated_count = 0

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            with type(self).lock:
                type(self).calls.append((str(kwargs["api_key"]), str(kwargs["model"])))

        async def system_one(self, state, questions):
            del questions
            mode = state["mode"]
            label = state["label"]
            if mode == "normal-four":
                with type(self).lock:
                    type(self).normal_count += 1
                    if type(self).normal_count == 4:
                        type(self).normal_started.set()
                while not type(self).normal_release.is_set():
                    await asyncio.sleep(0.005)
            elif mode == "stuck":
                type(self).stuck_started.set()
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    type(self).stuck_cancelled.set()
                    while not type(self).stuck_release.is_set():
                        await asyncio.sleep(0.005)
                    raise
            elif mode == "saturated":
                with type(self).lock:
                    type(self).saturated_count += 1
                    if type(self).saturated_count == 4:
                        type(self).saturated_started.set()
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    while not type(self).saturated_release.is_set():
                        await asyncio.sleep(0.005)
                    raise
            return {
                "model": self.kwargs["model"],
                "answers": {"safe": {"type": "noul", "noul": 1.0}},
                "usage": {"input_tokens": None, "output_tokens": None},
                "label": label,
            }

    runtime_a._client_factory = FakeClient
    runtime_b._client_factory = FakeClient

    def invoke(handler, home: Path, key: str, model: str, label: str, mode: str):
        home_token = set_hermes_home_override(home)
        secret_token = set_secret_scope({"TYPESAFE_API_KEY": key})
        try:
            raw = handler(
                {
                    "state": {"label": label, "mode": mode},
                    "questions": {"safe": {"type": "noul", "instructions": "safe?"}},
                    "model": model,
                }
            )
            if type(raw) is not str:
                raise TypeError("handler must return JSON string")
            return json.loads(raw)
        finally:
            reset_secret_scope(secret_token)
            reset_hermes_home_override(home_token)

    with ThreadPoolExecutor(max_workers=5) as pool:
        normal_calls = [
            (handler_a, home_a, "home-a-key", "model-a", "a-normal"),
            (handler_b, home_b, "home-b-key", "model-b", "b-normal"),
            (handler_a, home_a, "home-a-key-2", "model-a-2", "a-normal-2"),
            (handler_b, home_b, "home-b-key-2", "model-b-2", "b-normal-2"),
        ]
        futures = [pool.submit(invoke, *args, "normal-four") for args in normal_calls]
        assert FakeClient.normal_started.wait(timeout=3)
        calls_before_fifth = len(FakeClient.calls)
        fifth = pool.submit(invoke, handler_a, home_a, "home-a-fifth", "model-fifth", "fifth", "normal-four")
        fifth_result = fifth.result(timeout=2)
        assert fifth_result["error"]["code"] == "unavailable"
        assert len(FakeClient.calls) == calls_before_fifth
        assert runtime_a._broker is runtime_b._broker
        assert runtime_a._broker.owner_identity()["module"] == "hermes_typesafe_broker.core"
        assert runtime_a._broker.owner_identity()["pid"] == os.getpid()
        assert runtime_a._broker.stats()["active_operations"] == 4
        assert runtime_a._broker.stats()["thread_count"] == 1
        FakeClient.normal_release.set()
        normal_results = [future.result(timeout=3) for future in futures]

    assert all("error" not in result for result in normal_results)
    assert {result["model"] for result in normal_results} == {"model-a", "model-b", "model-a-2", "model-b-2"}
    normal_call_keys = set(FakeClient.calls[:4])
    assert normal_call_keys == {
        ("home-a-key", "model-a"),
        ("home-b-key", "model-b"),
        ("home-a-key-2", "model-a-2"),
        ("home-b-key-2", "model-b-2"),
    }
    assert runtime_a._broker.stats()["active_operations"] == 0

    stuck_pool = ThreadPoolExecutor(max_workers=2)
    stuck_future = stuck_pool.submit(invoke, handler_a, home_a, "home-a-stuck", "model-a-stuck", "a-stuck", "stuck")
    assert FakeClient.stuck_started.wait(timeout=3)
    assert runtime_a._broker.stats()["active_operations"] == 1
    assert manager_a.unload("typesafe") is True
    assert FakeClient.stuck_cancelled.wait(timeout=3)
    assert runtime_a._broker.stats()["active_operations"] == 1
    assert runtime_a._lease is None
    b_after_unload = invoke(handler_b, home_b, "home-b-after", "model-b-after", "b-after", "normal")
    assert b_after_unload["model"] == "model-b-after"
    FakeClient.stuck_release.set()
    stuck_result = stuck_future.result(timeout=3)
    stuck_pool.shutdown(wait=True)
    assert stuck_result["error"]["code"] == "unavailable"
    assert runtime_a._broker.stats()["active_operations"] == 0
    assert runtime_b._lease is not None

    manager_a._load_plugin(manifest_a)
    loaded_a_reloaded = manager_a._plugins["typesafe"]
    assert loaded_a_reloaded.enabled and loaded_a_reloaded.error is None
    assert loaded_a_reloaded.module.__name__ == "hermes_plugins.typesafe"
    entry_a_reloaded = registry.get_entry("system_one", scope=manager_a.scope_key)
    assert entry_a_reloaded is not None and entry_a_reloaded.handler is not handler_a
    handler_a_reloaded = entry_a_reloaded.handler
    runtime_a_reloaded = handler_a_reloaded._typesafe_runtime
    runtime_a_reloaded._client_factory = FakeClient

    saturated_pool = ThreadPoolExecutor(max_workers=5)
    saturated_calls = [
        (handler_a_reloaded, home_a, "a-sat-1", "model-a-sat-1", "a-sat-1"),
        (handler_b, home_b, "b-sat-1", "model-b-sat-1", "b-sat-1"),
        (handler_a_reloaded, home_a, "a-sat-2", "model-a-sat-2", "a-sat-2"),
        (handler_b, home_b, "b-sat-2", "model-b-sat-2", "b-sat-2"),
    ]
    saturated_futures = [saturated_pool.submit(invoke, *args, "saturated") for args in saturated_calls]
    assert FakeClient.saturated_started.wait(timeout=3)
    assert runtime_a_reloaded._broker.stats()["active_operations"] == 4
    saturated_calls_before_fifth = len(FakeClient.calls)
    saturated_fifth = saturated_pool.submit(
        invoke, handler_b, home_b, "b-sat-fifth", "model-b-sat-fifth", "b-sat-fifth", "saturated"
    )
    saturated_fifth_result = saturated_fifth.result(timeout=2)
    assert saturated_fifth_result["error"]["code"] == "unavailable"
    assert len(FakeClient.calls) == saturated_calls_before_fifth
    assert runtime_a_reloaded._broker.stats()["active_operations"] == 4
    assert manager_a.unload("typesafe") is True
    assert runtime_a_reloaded._broker.stats()["active_operations"] == 4
    assert manager_b.unload("typesafe") is True
    assert runtime_a_reloaded._broker.stats()["active_operations"] == 4
    FakeClient.saturated_release.set()
    saturated_results = [future.result(timeout=3) for future in saturated_futures]
    saturated_pool.shutdown(wait=True)
    assert all(result["error"]["code"] == "unavailable" for result in saturated_results)
    assert runtime_a_reloaded._broker.stats()["active_operations"] == 0

    wrong_home = invoke(handler_b, home_a, "home-a-key", "wrong-model", "wrong-home", "normal")
    assert wrong_home["error"]["code"] == "unavailable"
    home_token = set_hermes_home_override(home_b)
    try:
        unscoped_raw = handler_b(
            {
                "state": {"label": "unscoped", "mode": "normal"},
                "questions": {"safe": {"type": "noul", "instructions": "safe?"}},
                "model": "unscoped-model",
            }
        )
    finally:
        reset_hermes_home_override(home_token)
    if type(unscoped_raw) is not str:
        raise TypeError("handler must return JSON string")
    unscoped = json.loads(unscoped_raw)
    assert unscoped["error"]["code"] == "unavailable"

    assert runtime_a_reloaded._broker.acquire("wrong-abi", runtime_a_reloaded._broker.BUILD_SHA256, b"x" * 32) is None
    assert runtime_a_reloaded._broker.stats()["thread_count"] == 1
    assert runtime_a_reloaded._broker.shutdown(time.monotonic() + 1.0) in {"closed", "broken"}
    assert runtime_a_reloaded._broker.stats()["thread_count"] == 0
    assert runtime_a_reloaded._broker.acquire(
        runtime_a_reloaded._broker.ABI, runtime_a_reloaded._broker.BUILD_SHA256, b"y" * 32
    ) is None
    manager_b.unload("typesafe")
    print(
        json.dumps(
            {
                "module_names": [loaded_a.module.__name__, loaded_b.module.__name__],
                "shared_broker": runtime_a._broker is runtime_b._broker,
                "owner_pid": runtime_a._broker.owner_identity()["pid"],
                "normal_results": len(normal_results),
                "fifth_rejected": True,
                "stuck_slot_charged": True,
                "reload_unload_verified": True,
                "shutdown_closed": runtime_a._broker.stats()["state"] in {"CLOSED", "BROKEN"},
            },
            sort_keys=True,
        )
    )
'''


def _fixture_path() -> tuple[Path, bool]:
    raw = os.environ.get("HERMES_TYPESAFE_HERMES_FIXTURE", PUBLIC_HERMES_FIXTURE)
    fixture = Path(raw)
    required = os.environ.get("HERMES_TYPESAFE_REQUIRE_FIXTURE", "").lower() in {"1", "true", "yes"}
    return fixture, required


def _wheel_required() -> bool:
    return os.environ.get("HERMES_TYPESAFE_REQUIRE_WHEEL", "").lower() in {"1", "true", "yes"}


def test_installed_wheel_real_two_home_plugin_manager_lane() -> None:
    if sys.version_info[:2] not in {(3, 11), (3, 12)}:
        pytest.skip("real Hermes two-home lane requires Python 3.11 or 3.12")
    fixture, required = _fixture_path()
    if not fixture.is_dir():
        if required:
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

    try:
        package_spec = importlib.util.find_spec("hermes_typesafe")
        if package_spec is None or not package_spec.submodule_search_locations:
            raise ImportError("installed hermes_typesafe package is not importable")
        package_dir = Path(next(iter(package_spec.submodule_search_locations))).resolve()
    except Exception as error:
        if _wheel_required():
            raise AssertionError("candidate hermes-typesafe wheel is not installed") from error
        pytest.skip("candidate hermes-typesafe wheel is not installed")
    if not package_dir.is_dir() or not (package_dir / "plugin.yaml").is_file():
        if _wheel_required():
            pytest.fail("candidate hermes-typesafe wheel does not expose a plugin package")
        pytest.skip("candidate hermes-typesafe wheel does not expose a plugin package")
    if package_dir == ROOT or package_dir.name != "hermes_typesafe":
        if _wheel_required():
            pytest.fail("two-home lane resolved the repository source instead of an installed wheel")
        pytest.skip("candidate hermes-typesafe wheel is not installed")

    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HERMES_") and name not in {"PYTHONPATH", "TYPESAFE_API_KEY"}
    }
    result = subprocess.run(
        [sys.executable, "-c", _TWO_HOME_SCRIPT, str(fixture), str(package_dir)],
        cwd=Path("/tmp"),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["module_names"][0] == "hermes_plugins.typesafe"
    assert "__home_" in payload["module_names"][1]
    assert payload["normal_results"] == 4
    assert payload["fifth_rejected"] is True
    assert payload["reload_unload_verified"] is True
    assert payload["shared_broker"] is True
    assert payload["shutdown_closed"] is True
    assert payload["stuck_slot_charged"] is True
