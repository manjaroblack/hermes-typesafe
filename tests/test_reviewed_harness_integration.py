"""Exact-head reviewed-fork composition proof for the active harness."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REVIEWED_HERMES_SHA = "b38c2858107e9d63f98c1d3a86bd00933fbd0661"
REVIEWED_HERMES_FIXTURE = "/tmp/hermes-typesafe-reviewed-fixture"


_COMPOSED_PROOF = r'''
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

fixture = Path(sys.argv[1]).resolve()
package_dir = Path(sys.argv[2]).resolve()
wire = {"calls": [], "guard_mode": "low"}
actual_tool_args = []
later_seen = []


def guard_answers(mode):
    scores = {
        "jailbreak_injection": 0.0,
        "credential_exfiltration": 0.0,
        "destructive_action": 0.0,
    }
    if mode == "medium":
        scores["credential_exfiltration"] = 0.5
    elif mode == "high":
        scores["destructive_action"] = 0.8
    elif mode == "missing":
        scores.pop("destructive_action")
    return {
        name: {"type": "noul", "noul": score}
        for name, score in scores.items()
    }


def sdk_response(state, questions, model):
    if "target_model" in questions:
        kind = "route"
        answers = {
            "target_model": {
                "type": "choice",
                "choice": "coding",
                "confidence": 0.9,
            },
            "current_model_mismatch": {"type": "noul", "noul": 0.9},
            "worth_breaking_cache": {"type": "noul", "noul": 0.1},
            "difficulty": {
                "type": "score",
                "score": 2.0,
                "legend": {
                    "0": "routine",
                    "1": "moderate",
                    "2": "difficult",
                    "3": "expert",
                },
            },
        }
    elif isinstance(state, dict) and set(state) == {"tool_name", "args"}:
        kind = "guard"
        answers = guard_answers(wire["guard_mode"])
    elif isinstance(state, str):
        kind = "final"
        answers = guard_answers("medium")
    else:
        raise AssertionError("unexpected reviewed harness projection")
    wire["calls"].append(
        {
            "kind": kind,
            "state": state,
            "question_names": tuple(questions),
            "model": model,
        }
    )
    return {
        "model": model,
        "answers": answers,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


class RetryPolicy:
    def __init__(self, *, max_retries):
        assert max_retries == 0


class SyntheticAsyncTypeSafeClient:
    def __init__(self, **kwargs):
        self.model = kwargs["model"]
        assert kwargs["api_key"] == "synthetic-key"
        assert kwargs["base_url"] == "https://api.typesafe.ai"
        assert kwargs["retry"].__class__ is RetryPolicy

    async def system_one(self, state, questions, *, model):
        assert model == self.model
        return sdk_response(state, questions, model)

    async def aclose(self):
        return None


sdk = types.ModuleType("typesafe_sdk")
sdk.RetryPolicy = RetryPolicy
sdk.AsyncTypeSafeClient = SyntheticAsyncTypeSafeClient
sys.modules["typesafe_sdk"] = sdk


def configure_home(home):
    home.mkdir(parents=True, exist_ok=True)
    plugin_root = home / "plugins" / "typesafe"
    shutil.copytree(
        package_dir,
        plugin_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    (home / "bundled-empty").mkdir()
    (home / "config.yaml").write_text(
        """
plugins:
  enabled:
    - typesafe
  entries:
    typesafe:
      settings:
        model: jev-1.13.0
        suggestion:
          enabled: false
        guardrails:
          enabled: true
        routing:
          enabled: true
          mode: first_turn
          models:
            cheap:
              model: model-cheap
              provider: provider-a
            coding:
              model: model-coding
              provider: provider-a
""".strip()
        + "\n",
        encoding="utf-8",
    )
    os.environ["HOME"] = str(home)
    os.environ["HERMES_HOME"] = str(home)
    os.environ["HERMES_BUNDLED_PLUGINS"] = str(home / "bundled-empty")
    os.environ.pop("HERMES_ENABLE_PROJECT_PLUGINS", None)


def plugin_status(manager):
    matches = [entry for entry in manager.list_plugins() if entry["name"] == "typesafe"]
    assert len(matches) == 1
    return matches[0]


def apply_output(turn_finalizer, text):
    agent = SimpleNamespace(
        session_id="session",
        model="model-cheap",
        _persist_disabled=True,
    )
    return turn_finalizer._apply_output_hooks(
        agent,
        text,
        logging.getLogger("reviewed-proof"),
        platform="cli",
        effective_task_id="task",
        turn_id="turn",
        original_user_message="request",
        messages=[],
    )[0]


with tempfile.TemporaryDirectory(prefix="typesafe-reviewed-harness-") as temp:
    root = Path(temp).resolve()
    for name in tuple(os.environ):
        if name.startswith("HERMES_") or name in {"PYTHONPATH", "TYPESAFE_API_KEY"}:
            os.environ.pop(name, None)
    assert not any(name.startswith("HERMES_KANBAN_") for name in os.environ)

    plugin_first_home = root / "plugin-first"
    configure_home(plugin_first_home)
    sys.path.insert(0, str(fixture))

    import model_tools
    from agent import turn_finalizer
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from hermes_cli.plugins import (
        PluginContext,
        discover_plugins,
        get_plugin_manager,
    )
    from hermes_cli.plugins_manifest import PluginManifest
    from hermes_cli.plugins_policy import canonical_args_digest
    from tools.approval import approve_session

    secret_token = set_secret_scope({"TYPESAFE_API_KEY": "synthetic-key"})
    managers = []
    try:
        discover_plugins()
        manager = get_plugin_manager()
        managers.append(manager)
        status = plugin_status(manager)
        assert status["enabled"] is True
        assert status["error"] is None
        assert status["tools"] == 1
        assert status["hooks"] == 3
        phases = manager.iter_hook_callbacks_with_phase("pre_tool_call")
        assert len(phases) == 1 and phases[0][1] == "decision"

        later_context = PluginContext(
            PluginManifest(name="later-transform", source="user"),
            manager,
        )

        def later_transform(response_text):
            later_seen.append(response_text)
            return f"later:{response_text}"

        later_context.register_hook("transform_llm_output", later_transform)

        route_results = manager.invoke_hook(
            "pre_llm_call",
            user_message="route current request",
            is_first_turn=True,
            model="model-cheap",
            provider="provider-a",
        )
        assert route_results == [
            {
                "model_switch": {
                    "model": "model-coding",
                    "provider": "provider-a",
                    "allow_cache_break": False,
                }
            }
        ]
        assert wire["calls"][0]["state"] == {
            "user_message": "route current request",
            "current_label": "cheap",
        }

        capture_context = PluginContext(
            PluginManifest(name="execution-capture", source="user"),
            manager,
        )

        def capture_tool(arguments, **host_kwargs):
            del host_kwargs
            actual_tool_args.append(dict(arguments))
            return json.dumps({"ok": True}, sort_keys=True)

        capture_context.register_tool(
            name="capture_tool",
            toolset="reviewed-proof",
            schema={"type": "object", "additionalProperties": True},
            handler=capture_tool,
            is_async=False,
            description="Synthetic reviewed-fork execution capture",
        )

        wire["guard_mode"] = "low"
        low = model_tools.handle_function_call(
            "capture_tool",
            {"value": "low"},
            task_id="task",
            tool_call_id="call-low",
            session_id="session",
            turn_id="turn",
        )
        assert json.loads(low) == {"ok": True}
        assert actual_tool_args == [{"value": "low"}]

        wire["guard_mode"] = "medium"
        denied_medium = model_tools.handle_function_call(
            "capture_tool",
            {"value": "medium"},
            task_id="task",
            tool_call_id="call-medium-denied",
            session_id="session",
            turn_id="turn",
        )
        assert "error" in json.loads(denied_medium)
        assert len(actual_tool_args) == 1

        generation = manager.get_hook_registration_generation("pre_tool_call")
        digest = canonical_args_digest({"value": "medium"})
        assert digest is not None
        approve_session(
            "default",
            f"plugin_rule:pre_tool_call:capture_tool:{generation}:{digest}",
        )
        approved_medium = model_tools.handle_function_call(
            "capture_tool",
            {"value": "medium"},
            task_id="task",
            tool_call_id="call-medium-approved",
            session_id="session",
            turn_id="turn",
        )
        assert json.loads(approved_medium) == {"ok": True}
        assert actual_tool_args[-1] == {"value": "medium"}

        wire["guard_mode"] = "high"
        high = model_tools.handle_function_call(
            "capture_tool",
            {"value": "high"},
            task_id="task",
            tool_call_id="call-high",
            session_id="session",
            turn_id="turn",
        )
        assert "error" in json.loads(high)
        assert len(actual_tool_args) == 2

        wire["guard_mode"] = "missing"
        missing = model_tools.handle_function_call(
            "capture_tool",
            {"value": "missing"},
            task_id="task",
            tool_call_id="call-missing",
            session_id="session",
            turn_id="turn",
        )
        assert "error" in json.loads(missing)
        assert len(actual_tool_args) == 2

        plugin_first = apply_output(turn_finalizer, "candidate final")
        assert plugin_first.startswith("Safety note:")
        assert plugin_first.endswith("candidate final")
        assert later_seen == ["candidate final"]
        plugin_final_calls = sum(call["kind"] == "final" for call in wire["calls"])
        assert plugin_final_calls == 1

        manager.unload()
        managers.remove(manager)

        earlier_home = root / "earlier-first"
        configure_home(earlier_home)
        earlier_manager = get_plugin_manager()
        managers.append(earlier_manager)
        earlier_context = PluginContext(
            PluginManifest(name="earlier-transform", source="user"),
            earlier_manager,
        )
        earlier_context.register_hook(
            "transform_llm_output",
            lambda response_text: f"earlier:{response_text}",
        )
        discover_plugins()
        earlier_status = plugin_status(earlier_manager)
        assert earlier_status["hooks"] == 3

        earlier_first = apply_output(turn_finalizer, "candidate final")
        assert earlier_first == "earlier:candidate final"
        assert sum(call["kind"] == "final" for call in wire["calls"]) == plugin_final_calls + 1
    finally:
        reset_secret_scope(secret_token)
        for manager in managers:
            manager.unload()

    assert all(call["model"] == "jev-1.13.0" for call in wire["calls"])
    print(
        json.dumps(
            {
                "actual_tool_dispatches": len(actual_tool_args),
                "first_turn_target": route_results[0]["model_switch"],
                "hook_count": status["hooks"],
                "plugin_first_transform": plugin_first.startswith("Safety note:"),
                "earlier_first_transform": earlier_first,
                "wire_kinds": [call["kind"] for call in wire["calls"]],
            },
            sort_keys=True,
        )
    )
'''


def _fixture_path() -> tuple[Path, bool]:
    raw = os.environ.get("HERMES_TYPESAFE_REVIEWED_FIXTURE", REVIEWED_HERMES_FIXTURE)
    required = os.environ.get("HERMES_TYPESAFE_REQUIRE_REVIEWED_FIXTURE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return Path(raw), required


def _candidate_package() -> Path:
    require_wheel = os.environ.get("HERMES_TYPESAFE_REQUIRE_WHEEL", "").lower() in {
        "1",
        "true",
        "yes",
    }
    spec = importlib.util.find_spec("hermes_typesafe")
    if spec is not None and spec.submodule_search_locations:
        candidate = Path(next(iter(spec.submodule_search_locations))).resolve()
        if candidate.is_dir():
            return candidate
    if require_wheel:
        pytest.fail("candidate hermes-typesafe wheel is not installed")
    pytest.skip("candidate hermes-typesafe wheel is not installed")


def test_reviewed_fork_real_plugin_manager_composes_all_harness_paths() -> None:
    if sys.version_info[:2] != (3, 12):
        pytest.skip("reviewed Hermes fixture lane requires CPython 3.12")
    fixture, required = _fixture_path()
    if not fixture.is_dir():
        if required:
            pytest.fail("required immutable reviewed Hermes fixture is not available")
        pytest.skip("immutable reviewed Hermes fixture is not available")

    fixture_head = subprocess.run(
        ["git", "-C", str(fixture), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert fixture_head.returncode == 0, fixture_head.stderr
    assert fixture_head.stdout.strip() == REVIEWED_HERMES_SHA

    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HERMES_") and name not in {"PYTHONPATH", "TYPESAFE_API_KEY"}
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _COMPOSED_PROOF,
            str(fixture),
            str(_candidate_package()),
        ],
        cwd="/tmp",
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["hook_count"] == 3
    assert payload["first_turn_target"] == {
        "model": "model-coding",
        "provider": "provider-a",
        "allow_cache_break": False,
    }
    assert payload["actual_tool_dispatches"] == 2
    assert payload["plugin_first_transform"] is True
    assert payload["earlier_first_transform"] == "earlier:candidate final"
