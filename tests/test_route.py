"""RED/GREEN contracts for advisory routing hints."""

from __future__ import annotations

import logging
from typing import Any

import pytest

try:
    from route import (
        ROUTING_CHOICE,
        ROUTING_DIFFICULTY,
        ROUTING_MISMATCH,
        ROUTING_WORTH,
        build_routing_questions,
        compose_advisory_context,
        evaluate_routing,
        format_routing_hint,
        make_routing_handler,
    )
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe.route import (
        ROUTING_CHOICE,
        ROUTING_DIFFICULTY,
        ROUTING_MISMATCH,
        ROUTING_WORTH,
        build_routing_questions,
        compose_advisory_context,
        evaluate_routing,
        format_routing_hint,
        make_routing_handler,
    )


POOL = {
    "cheap": {"model": "jev-cheap", "provider": "typesafe"},
    "coding": {"model": "jev-coding", "provider": "typesafe"},
}


def response(
    *,
    target: str = "coding",
    mismatch: float = 0.8,
    worth: float = 0.8,
    confidence: float | None = 0.8,
    difficulty: float = 2.0,
) -> dict[str, Any]:
    return {
        "answers": {
            ROUTING_CHOICE: {
                "type": "choice",
                "choice": target,
                "confidence": confidence,
            },
            ROUTING_MISMATCH: {"type": "noul", "noul": mismatch},
            ROUTING_WORTH: {"type": "noul", "noul": worth},
            ROUTING_DIFFICULTY: {
                "type": "score",
                "score": difficulty,
                "legend": {0: "routine", 1: "moderate", 2: "difficult", 3: "expert"},
            },
        }
    }


def test_routing_questions_are_one_typed_batch_with_configured_labels() -> None:
    questions = build_routing_questions(POOL)

    assert list(questions) == [ROUTING_CHOICE, ROUTING_MISMATCH, ROUTING_WORTH, ROUTING_DIFFICULTY]
    assert questions[ROUTING_CHOICE]["type"] == "choice"
    assert set(questions[ROUTING_CHOICE]["criteria"]) == set(POOL)
    assert questions[ROUTING_MISMATCH]["type"] == "noul"
    assert questions[ROUTING_WORTH]["type"] == "noul"
    assert questions[ROUTING_DIFFICULTY]["type"] == "score"
    assert len(questions[ROUTING_DIFFICULTY]["criteria"]) == 4


@pytest.mark.parametrize("field", ["mismatch", "confidence"])
def test_shared_switch_gates_are_inclusive_and_difficulty_never_overrides(field: str) -> None:
    passing = evaluate_routing(
        response(difficulty=0),
        POOL,
        current_model="jev-cheap",
        mode="first_turn",
    )
    assert passing is not None and passing.switch_worthy is True

    below = {"mismatch": 0.8, "worth": 0.8, "confidence": 0.8}
    below[field] = 0.799999
    decision = evaluate_routing(
        response(
            mismatch=below["mismatch"],
            worth=below["worth"],
            confidence=below["confidence"],
            difficulty=3,
        ),
        POOL,
        current_model="jev-cheap",
        mode="first_turn",
    )
    assert decision is not None and decision.switch_worthy is False


def test_cache_worth_is_required_only_for_later_turn_routing() -> None:
    first_turn = evaluate_routing(
        response(worth=0.1),
        POOL,
        current_model="jev-cheap",
        mode="first_turn",
    )
    later_turn = evaluate_routing(
        response(worth=0.1),
        POOL,
        current_model="jev-cheap",
        mode="cache_break_if_worth_it",
    )

    assert first_turn is not None and first_turn.switch_worthy is True
    assert later_turn is not None and later_turn.switch_worthy is False


def test_current_unknown_and_duplicate_model_identity_never_claim_switch() -> None:
    same = evaluate_routing(response(), POOL, current_model="jev-coding")
    assert same is not None and same.switch_worthy is False

    unknown_winner = evaluate_routing(response(target="unknown"), POOL, current_model="jev-cheap")
    assert unknown_winner is None

    duplicate_pool = {
        "cheap": {"model": "jev-shared", "provider": "provider-a"},
        "coding": {"model": "jev-shared", "provider": "provider-b"},
    }
    duplicate = evaluate_routing(response(), duplicate_pool, current_model="jev-shared")
    assert duplicate is not None and duplicate.switch_worthy is False

    provider_resolved = evaluate_routing(
        response(), duplicate_pool, current_model="jev-shared", current_provider="provider-a"
    )
    assert provider_resolved is not None and provider_resolved.switch_worthy is True

    unknown_current = evaluate_routing(response(), POOL, current_model="not-configured")
    assert unknown_current is not None and unknown_current.switch_worthy is False


def test_hint_is_advisory_and_composition_is_deterministic() -> None:
    hint = format_routing_hint("coding")
    assert hint == "Routing hint: consider the configured coding model for this request. No model switch was performed."
    assert "switch_model" not in hint
    assert compose_advisory_context("skill context", hint) == f"skill context\n\n{hint}"
    assert compose_advisory_context(None, hint) == hint
    assert compose_advisory_context(hint, hint) == hint
    assert compose_advisory_context(None, None) is None


class FakeRuntime:
    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result
        self.error = error

    def execute_sync(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def enabled_settings(*, mode: str = "first_turn", enabled: bool = True, models: Any = POOL) -> dict[str, Any]:
    return {
        "model": "jev-1.13.0",
        "routing.enabled": enabled,
        "routing.mode": mode,
        "routing.models": models,
    }


def test_handler_sends_only_current_message_once_and_returns_hint() -> None:
    runtime = FakeRuntime(response())
    handler = make_routing_handler(
        enabled_settings(),
        runtime=runtime,
        secret_reader=lambda: "synthetic-key",
        require_home_identity=False,
    )

    class Poison:
        def __repr__(self) -> str:
            raise AssertionError("unknown callback value was inspected")

        def __iter__(self) -> Any:
            raise AssertionError("unknown callback value was iterated")

    result = handler(
        user_message="current user request",
        is_first_turn=True,
        model="jev-cheap",
        conversation_history=Poison(),
        system_prompt=Poison(),
    )

    assert result == format_routing_hint("coding")
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["state"] == "current user request"
    assert runtime.calls[0]["api_key"] == "synthetic-key"
    assert runtime.calls[0]["questions"][ROUTING_CHOICE]["criteria"] == {"cheap": None, "coding": None}
    assert runtime.calls[0]["model"] == "jev-1.13.0"
    assert runtime.calls[0]["timeout"] <= 2.0


@pytest.mark.parametrize(
    "settings, kwargs, key",
    [
        (enabled_settings(enabled=False), {"user_message": "x", "is_first_turn": True}, "key"),
        (enabled_settings(mode="off"), {"user_message": "x", "is_first_turn": True}, "key"),
        (enabled_settings(models={}), {"user_message": "x", "is_first_turn": True}, "key"),
        (enabled_settings(), {"user_message": "x", "is_first_turn": False}, "key"),
        (enabled_settings(), {"user_message": "x", "is_first_turn": True}, None),
    ],
)
def test_disabled_ineligible_or_keyless_handler_does_not_call_runtime(
    settings: dict[str, Any], kwargs: dict[str, Any], key: str | None
) -> None:
    runtime = FakeRuntime(response())
    handler = make_routing_handler(
        settings,
        runtime=runtime,
        secret_reader=lambda: key,
        require_home_identity=False,
    )

    assert handler(**kwargs) is None
    assert runtime.calls == []


def test_faults_fail_open_without_stale_context() -> None:
    runtime = FakeRuntime(error=RuntimeError("provider sentinel"))
    handler = make_routing_handler(
        enabled_settings(),
        runtime=runtime,
        secret_reader=lambda: "key",
        require_home_identity=False,
    )

    assert handler(user_message="x", is_first_turn=True, model="jev-cheap") is None
    assert len(runtime.calls) == 1


def test_handler_stops_before_runtime_when_absolute_budget_is_expired() -> None:
    runtime = FakeRuntime(response())
    ticks = iter((10.0, 13.0))
    handler = make_routing_handler(
        enabled_settings(),
        runtime=runtime,
        secret_reader=lambda: "key",
        require_home_identity=False,
        clock=lambda: next(ticks),
    )

    assert handler(user_message="x", is_first_turn=True, model="jev-cheap") is None
    assert runtime.calls == []


def test_advisory_compatibility_handler_never_claims_a_switch(caplog: pytest.LogCaptureFixture) -> None:
    runtime = FakeRuntime(response())
    handler = make_routing_handler(
        enabled_settings(mode="cache_break_if_worth_it"),
        runtime=runtime,
        secret_reader=lambda: "key",
        require_home_identity=False,
    )

    with caplog.at_level(logging.INFO):
        result = handler(user_message="x", is_first_turn=False, model="jev-cheap")
    assert result == format_routing_hint("coding")
    assert "would have switched" not in caplog.text

    caplog.clear()
    runtime.result = response(worth=0.799999)
    with caplog.at_level(logging.INFO):
        assert handler(user_message="x", is_first_turn=False, model="jev-cheap") is None
    assert "would have switched" not in caplog.text
