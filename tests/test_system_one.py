"""RED contract for the typed system_one tool boundary."""

from __future__ import annotations

import json

import pytest

try:
    import tool_system_one as tool
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe import tool_system_one as tool


def mixed_arguments() -> dict[str, object]:
    return {
        "state": {"message": "hello", "nested": [1, {"safe": True}]},
        "questions": {
            "safe": {"type": "noul", "instructions": "is this safe?"},
            "tone": {
                "type": "choice",
                "instructions": {"question": "tone"},
                "criteria": {"calm": None, "angry": {"hint": "upset"}},
            },
            "difficulty": {
                "type": "score",
                "instructions": ["difficulty"],
                "criteria": ["easy", {"name": "hard"}],
            },
        },
    }


def test_mixed_batch_is_projected_once_and_returns_typed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, object, object, object]] = []
    monkeypatch.setattr(tool, "_read_scoped_secret", lambda: "scoped-key")

    def fake_execute(state: object, questions: object, model: object, *, api_key: object, settings: object) -> dict[str, object]:
        calls.append((state, questions, model, api_key))
        return {
            "model": model,
            "answers": {"safe": {"type": "noul", "noul": 0.9}},
            "usage": {"input_tokens": None, "output_tokens": None},
        }

    monkeypatch.setattr(tool, "_execute_request", fake_execute)
    result = tool.system_one(mixed_arguments())

    assert len(calls) == 1
    state, questions, model, api_key = calls[0]
    assert state == mixed_arguments()["state"]
    assert questions == mixed_arguments()["questions"]
    assert model == "jev-1.13.0"
    assert api_key == "scoped-key"
    assert result["answers"]["safe"]["noul"] == 0.9


def test_model_override_is_validated_and_ambient_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "_read_scoped_secret", lambda: "scoped-key")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "ambient-model")
    captured: dict[str, object] = {}

    def fake_execute(state: object, questions: object, model: object, *, api_key: object, settings: object) -> dict[str, object]:
        captured.update({"model": model, "api_key": api_key})
        return {"model": model, "answers": {}, "usage": {}}

    monkeypatch.setattr(tool, "_execute_request", fake_execute)
    arguments = mixed_arguments()
    arguments["model"] = "custom-model"
    result = tool.system_one(arguments)
    assert captured == {"model": "custom-model", "api_key": "scoped-key"}
    assert result["model"] == "custom-model"


def test_malformed_questions_are_rejected_before_runtime_or_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "_read_scoped_secret", lambda: "scoped-key")
    monkeypatch.setattr(tool, "_execute_request", lambda **_: pytest.fail("runtime invoked before preflight"))
    arguments = mixed_arguments()
    arguments["questions"] = {"bad": {"type": "choice", "instructions": "missing criteria"}}
    result = tool.system_one(arguments)
    assert result["error"]["code"] == "invalid_input"
    assert "criteria" not in json.dumps(result)


def test_handler_rejects_reserved_internal_kwargs_without_raw_type_error() -> None:
    handler = tool.make_system_one_handler({}, home_identity="home")
    raw = handler(_runtime=object())
    assert type(raw) is str
    result = json.loads(raw)
    assert result["error"]["code"] == "invalid_input"


def test_keyless_and_blank_key_are_unavailable_without_runtime_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "_execute_request", lambda **_: pytest.fail("runtime invoked without key"))
    for key in (None, "", "   "):
        monkeypatch.setattr(tool, "_read_scoped_secret", lambda key=key: key)
        result = tool.system_one(mixed_arguments())
        assert result["error"]["code"] == "unavailable"


def test_oversized_scoped_key_is_unavailable_without_runtime_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "_read_scoped_secret", lambda: "k" * 4_097)
    monkeypatch.setattr(tool, "_execute_request", lambda **_: pytest.fail("runtime invoked with oversized key"))
    result = tool.system_one(mixed_arguments())
    assert result["error"]["code"] == "unavailable"


def test_provider_errors_are_static_and_never_include_raw_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "_read_scoped_secret", lambda: "scoped-key")

    class FakeError(Exception):
        code = "auth_failed"
        message = "TypeSafe authentication failed."
        body = "secret-body-sentinel"

    def fail(*_: object, **__: object) -> object:
        raise FakeError("raw-exception-sentinel")

    monkeypatch.setattr(tool, "_execute_request", fail)
    result = tool.system_one(mixed_arguments())
    encoded = json.dumps(result)
    assert result["error"] == {"code": "auth_failed", "message": "TypeSafe authentication failed."}
    assert "secret-body-sentinel" not in encoded
    assert "raw-exception-sentinel" not in encoded
