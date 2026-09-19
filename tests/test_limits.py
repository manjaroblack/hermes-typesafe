"""RED contract for bounded JSON preflight and request caps."""

from __future__ import annotations

import json
import math
from typing import cast

import pytest

try:
    from limits import (
        MAX_CONTAINER_ITEMS,
        MAX_MODEL_BYTES,
        MAX_REQUEST_BYTES,
        MAX_STATE_BYTES,
        LimitsError,
        preflight_request,
        preflight_state,
    )
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe.limits import (
        MAX_CONTAINER_ITEMS,
        MAX_MODEL_BYTES,
        MAX_REQUEST_BYTES,
        MAX_STATE_BYTES,
        LimitsError,
        preflight_request,
        preflight_state,
    )


def question(kind: str = "noul") -> dict[str, object]:
    if kind == "choice":
        return {
            "type": "choice",
            "instructions": {"nested": ["choose", {"weight": 1}]},
            "criteria": {"yes": {"description": "yes"}, "no": None},
        }
    if kind == "score":
        return {
            "type": "score",
            "instructions": ["score", {"nested": True}],
            "criteria": ["low", {"mid": [1, 2]}, "high"],
        }
    return {
        "type": "noul",
        "instructions": "is this true?",
        "criteria": {"true": "yes", "false": {"description": "no"}},
    }


def test_preflight_accepts_all_state_roots_and_preserves_nested_json() -> None:
    for state in ["text", {"nested": [1, False, None]}, ["text", {"n": 2}]]:
        checked = preflight_request(
            state=state,
            questions={"decision": question()},
            model="jev-1.13.0",
        )
        assert checked.state == state
        assert checked.questions["decision"]["criteria"]["false"]["description"] == "no"


def test_preflight_rejects_scalar_null_bool_empty_questions_before_sdk() -> None:
    for state in [None, True, 1, 1.0]:
        with pytest.raises(LimitsError) as error:
            preflight_state(state)
        assert error.value.code == "invalid_input"
    with pytest.raises(LimitsError) as error:
        preflight_request(state="ok", questions={}, model="jev-1.13.0")
    assert error.value.code == "invalid_input"


def test_preflight_rejects_nonfinite_cycles_and_custom_json_types() -> None:
    for state in [float("nan"), float("inf")]:
        with pytest.raises(LimitsError):
            preflight_state(state)
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(LimitsError) as error:
        preflight_state(cyclic)
    assert error.value.code == "invalid_input"

    class Poison(dict[str, object]):
        def __iter__(self):  # pragma: no cover - a rejection must precede this
            raise AssertionError("custom mapping was inspected")

    with pytest.raises(LimitsError):
        preflight_state(Poison(value="x"))


def test_preflight_exact_and_one_over_state_request_model_and_container_caps() -> None:
    # Find a deterministic exact boundary using the real canonical representation.
    payload: list[str] = ["x" * 8_192, "x" * 8_192, "x" * 8_192, ""]
    while len(json.dumps(payload, ensure_ascii=True, separators=(",", ":"))) < MAX_STATE_BYTES:
        payload[-1] += "x"
    assert len(json.dumps(payload, ensure_ascii=True, separators=(",", ":"))) <= MAX_STATE_BYTES
    preflight_state(payload)
    payload.append("x")
    with pytest.raises(LimitsError) as error:
        preflight_state(payload)
    assert error.value.code == "payload_too_large"

    with pytest.raises(LimitsError) as error:
        preflight_request(
            state="ok",
            questions={"decision": question()},
            model="m" * (MAX_MODEL_BYTES + 1),
        )
    assert error.value.code == "payload_too_large"

    too_many = {str(index): question() for index in range(MAX_CONTAINER_ITEMS + 1)}
    with pytest.raises(LimitsError) as error:
        preflight_request(state="ok", questions=too_many, model="jev-1.13.0")
    assert error.value.code == "payload_too_large"


def test_preflight_depth_and_utf8_boundaries() -> None:
    nested: object = "leaf"
    for _ in range(8):
        nested = {"next": nested}
    preflight_state(nested)
    nested = {"next": nested}
    nested = {"next": nested}
    with pytest.raises(LimitsError):
        preflight_state(nested)

    with pytest.raises(LimitsError):
        preflight_state("\ud800")
    assert math.isfinite(0.5)


def test_preflight_rejects_trailing_control_characters_in_names_and_model() -> None:
    for model in ("jev-1.13.0\n", "jev-1.13.0\r"):
        with pytest.raises(LimitsError) as error:
            preflight_request(state="ok", questions={"decision": question()}, model=model)
        assert error.value.code == "invalid_input"
    with pytest.raises(LimitsError) as error:
        preflight_request(state="ok", questions={"decision\n": question()}, model="jev-1.13.0")
    assert error.value.code == "invalid_input"


def test_preflight_request_size_is_canonical_and_bounded() -> None:
    checked = preflight_request(
        state={"b": 2, "a": 1},
        questions={"d": question("choice"), "s": question("score")},
        model="jev-1.13.0",
    )
    assert checked.request_bytes == checked.canonical_bytes
    assert len(checked.canonical_bytes) <= MAX_REQUEST_BYTES
    assert checked.canonical_bytes.startswith(b'{"model":"jev-1.13.0"')


def test_preflight_returns_detached_primitive_data() -> None:
    state = {"nested": {"value": "before"}}
    questions = {"decision": question("choice")}
    checked = preflight_request(state=state, questions=questions, model="jev-1.13.0")

    state["nested"]["value"] = "after"
    questions["decision"]["criteria"]["yes"]["description"] = "changed"

    checked_state = cast(dict[str, dict[str, str]], checked.state)
    assert checked_state["nested"]["value"] == "before"
    assert checked.questions["decision"]["criteria"]["yes"]["description"] == "yes"
