"""RED contract for bounded JSON preflight and request caps."""

from __future__ import annotations

import json
import math
from typing import cast

import pytest

try:
    from limits import (
        MAX_CONTAINER_ITEMS,
        MAX_JSON_NODES,
        MAX_MODEL_BYTES,
        MAX_OPTION_NAME_BYTES,
        MAX_OPTIONS,
        MAX_QUESTION_NAME_BYTES,
        MAX_QUESTIONS,
        MAX_REQUEST_BYTES,
        MAX_RESPONSE_BYTES,
        MAX_SCORE_LEVELS,
        MAX_STATE_BYTES,
        MAX_STRING_BYTES,
        LimitsError,
        bound_response_bytes,
        preflight_request,
        preflight_state,
    )
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe.limits import (
        MAX_CONTAINER_ITEMS,
        MAX_JSON_NODES,
        MAX_MODEL_BYTES,
        MAX_OPTION_NAME_BYTES,
        MAX_OPTIONS,
        MAX_QUESTION_NAME_BYTES,
        MAX_QUESTIONS,
        MAX_REQUEST_BYTES,
        MAX_RESPONSE_BYTES,
        MAX_SCORE_LEVELS,
        MAX_STATE_BYTES,
        MAX_STRING_BYTES,
        LimitsError,
        bound_response_bytes,
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


def test_preflight_exact_and_one_over_question_option_level_and_string_caps() -> None:
    minimal = {"type": "noul", "instructions": "x"}
    exact_questions = {str(index): minimal for index in range(MAX_QUESTIONS)}
    preflight_request(state="ok", questions=exact_questions, model="m" * MAX_MODEL_BYTES)
    with pytest.raises(LimitsError) as error:
        preflight_request(
            state="ok",
            questions={**exact_questions, "one-over": minimal},
            model="m" * MAX_MODEL_BYTES,
        )
    assert error.value.code == "payload_too_large"

    exact_options = {str(index): None for index in range(MAX_OPTIONS)}
    preflight_request(
        state="ok",
        questions={"choice": {"type": "choice", "instructions": "x", "criteria": exact_options}},
        model="m",
    )
    with pytest.raises(LimitsError) as error:
        preflight_request(
            state="ok",
            questions={
                "choice": {
                    "type": "choice",
                    "instructions": "x",
                    "criteria": {**exact_options, "one-over": None},
                }
            },
            model="m",
        )
    assert error.value.code == "payload_too_large"

    exact_levels = ["x"] * MAX_SCORE_LEVELS
    preflight_request(
        state="ok",
        questions={"score": {"type": "score", "instructions": "x", "criteria": exact_levels}},
        model="m",
    )
    with pytest.raises(LimitsError) as error:
        preflight_request(
            state="ok",
            questions={
                "score": {"type": "score", "instructions": "x", "criteria": [*exact_levels, "x"]}
            },
            model="m",
        )
    assert error.value.code == "payload_too_large"

    preflight_state("x" * MAX_STRING_BYTES)
    with pytest.raises(LimitsError) as error:
        preflight_state("x" * (MAX_STRING_BYTES + 1))
    assert error.value.code == "payload_too_large"
    with pytest.raises(LimitsError) as error:
        preflight_state("é" * (MAX_STRING_BYTES // 2 + 1))
    assert error.value.code == "payload_too_large"

    preflight_request(
        state="ok",
        questions={"q" * MAX_QUESTION_NAME_BYTES: minimal},
        model="m",
    )
    with pytest.raises(LimitsError) as error:
        preflight_request(
            state="ok",
            questions={"q" * (MAX_QUESTION_NAME_BYTES + 1): minimal},
            model="m",
        )
    assert error.value.code == "payload_too_large"

    exact_option_name = "o" * MAX_OPTION_NAME_BYTES
    preflight_request(
        state="ok",
        questions={
            "choice": {
                "type": "choice",
                "instructions": "x",
                "criteria": {exact_option_name: None},
            }
        },
        model="m",
    )
    with pytest.raises(LimitsError) as error:
        preflight_request(
            state="ok",
            questions={
                "choice": {
                    "type": "choice",
                    "instructions": "x",
                    "criteria": {"o" * (MAX_OPTION_NAME_BYTES + 1): None},
                }
            },
            model="m",
        )
    assert error.value.code == "payload_too_large"

    preflight_state(["x"] * MAX_CONTAINER_ITEMS)
    with pytest.raises(LimitsError) as error:
        preflight_state(["x"] * (MAX_CONTAINER_ITEMS + 1))
    assert error.value.code == "payload_too_large"

    assert bound_response_bytes(b"x" * MAX_RESPONSE_BYTES) == b"x" * MAX_RESPONSE_BYTES
    with pytest.raises(LimitsError) as error:
        bound_response_bytes(b"x" * (MAX_RESPONSE_BYTES + 1))
    assert error.value.code == "response_too_large"


def test_preflight_exact_and_one_over_request_byte_cap() -> None:
    questions = {
        f"q{index}": {"type": "noul", "instructions": "x" * 8_192}
        for index in range(15)
    }

    def request_for(last_instruction_length: int) -> dict[str, object]:
        return {
            "state": "ok",
            "questions": {
                **questions,
                "q15": {"type": "noul", "instructions": "x" * last_instruction_length},
            },
            "model": "m",
        }

    def encoded_length(last_instruction_length: int) -> int:
        return len(
            json.dumps(
                request_for(last_instruction_length),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        )

    low, high, exact_length = 0, 8_192, None
    while low <= high:
        middle = (low + high) // 2
        size = encoded_length(middle)
        if size <= MAX_REQUEST_BYTES:
            if size == MAX_REQUEST_BYTES:
                exact_length = middle
                break
            low = middle + 1
        else:
            high = middle - 1
    assert exact_length is not None
    request = request_for(exact_length)
    checked = preflight_request(**request)
    assert len(checked.canonical_bytes) == MAX_REQUEST_BYTES
    request["questions"]["q15"]["instructions"] += "x"  # type: ignore[index]
    with pytest.raises(LimitsError) as error:
        preflight_request(**request)
    assert error.value.code == "payload_too_large"


def test_preflight_envelope_depth_eight_is_allowed_and_nine_is_rejected() -> None:
    state: object = "leaf"
    for _ in range(8):
        state = {"next": state}
    preflight_request(state=state, questions={"q": {"type": "noul", "instructions": "x"}}, model="m")
    state = {"next": state}
    with pytest.raises(LimitsError) as error:
        preflight_request(state=state, questions={"q": {"type": "noul", "instructions": "x"}}, model="m")
    assert error.value.code == "payload_too_large"


def test_preflight_counts_shared_dag_visits_at_exact_node_cap() -> None:
    shared = {"leaf": "x"}
    children: list[list[object]] = [[] for _ in range(256)]
    for index in range(1_275):
        children[index // 6].append(shared)
    children[212].extend(["x", "x"])
    state = children
    checked = preflight_request(
        state=state,
        questions={"q": {"type": "noul", "instructions": "x"}},
        model="m",
    )
    assert checked.state == state
    children[212].append("x")
    with pytest.raises(LimitsError) as error:
        preflight_request(
            state=state,
            questions={"q": {"type": "noul", "instructions": "x"}},
            model="m",
        )
    assert error.value.code == "payload_too_large"
    assert MAX_JSON_NODES == 4_096


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
