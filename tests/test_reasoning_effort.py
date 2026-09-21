"""RED/GREEN contracts for closed-pool reasoning effort routing."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any

import pytest

try:
    import client
    import hermes_typesafe_broker.core as broker
    from harness import make_combined_pre_llm_handler
    from route import (
        ROUTING_CHOICE,
        ROUTING_DIFFICULTY,
        ROUTING_MISMATCH,
        ROUTING_WORTH,
        _validated_pool,
        build_routing_questions,
        evaluate_routing,
        format_model_switch_directive,
        make_routing_directive_handler,
    )
    from runtime import TypeSafeRuntime
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe import client
    import hermes_typesafe_broker.core as broker
    from hermes_typesafe.harness import make_combined_pre_llm_handler
    from hermes_typesafe.route import (
        ROUTING_CHOICE,
        ROUTING_DIFFICULTY,
        ROUTING_MISMATCH,
        ROUTING_WORTH,
        _validated_pool,
        build_routing_questions,
        evaluate_routing,
        format_model_switch_directive,
        make_routing_directive_handler,
    )
    from hermes_typesafe.runtime import TypeSafeRuntime

ROUTING_EFFORT = "reasoning_effort"


POOL = {
    "cheap": {
        "model": "z-ai/glm-5.3-flash",
        "provider": "openrouter",
        "reasoning_allowed": [],
        "ignored": {"nested": True},
    },
    "coding": {
        "model": "gpt-5.6-luna",
        "provider": "openai-codex",
        "reasoning_allowed": ["low", "medium", "high"],
        "reasoning_default": "medium",
        "ignored": "discarded",
    },
    "reasoning": {
        "model": "grok-4.6",
        "provider": "xai-oauth",
        "reasoning_allowed": ["low", "medium", "high"],
        "reasoning_default": "high",
    },
}


def route_response(
    *,
    target: str = "coding",
    effort: Any = "high",
    mismatch: float = 0.9,
    worth: float = 0.9,
    confidence: float | None = 0.9,
) -> dict[str, Any]:
    answers: dict[str, Any] = {
        ROUTING_CHOICE: {"type": "choice", "choice": target, "confidence": confidence},
        ROUTING_MISMATCH: {"type": "noul", "noul": mismatch},
        ROUTING_WORTH: {"type": "noul", "noul": worth},
        ROUTING_DIFFICULTY: {
            "type": "score",
            "score": 2.0,
            "legend": {0: "routine", 1: "moderate", 2: "difficult", 3: "expert"},
        },
    }
    if effort is not None:
        answers[ROUTING_EFFORT] = {"type": "choice", "choice": effort}
    return {"answers": answers}


def test_pool_normalization_preserves_identity_and_validates_optional_effort(plugin: Any) -> None:
    normalized = plugin._bounded_routing_models(POOL)
    assert set(normalized) == {"cheap", "coding", "reasoning"}
    assert normalized["cheap"] == {
        "model": "z-ai/glm-5.3-flash",
        "provider": "openrouter",
    }
    assert normalized["coding"]["reasoning_allowed"] == ["low", "medium", "high"]
    assert normalized["coding"]["reasoning_default"] == "medium"
    assert normalized["coding"] is not POOL["coding"]
    assert normalized["coding"]["reasoning_allowed"] is not POOL["coding"]["reasoning_allowed"]
    assert _validated_pool(POOL)["reasoning"]["reasoning_allowed"] == ["low", "medium", "high"]


@pytest.mark.parametrize(
    "bad_fields",
    [
        {"reasoning_allowed": []},
        {"reasoning_allowed": "low", "reasoning_default": "low"},
        {"reasoning_allowed": ["low", "low"], "reasoning_default": "low"},
        {"reasoning_allowed": ["low", "xhigh"], "reasoning_default": "low"},
        {"reasoning_allowed": ["low", "medium"], "reasoning_default": "high"},
        {"reasoning_allowed": ["low", "medium"]},
    ],
)
def test_malformed_optional_effort_disables_only_label(bad_fields: dict[str, Any]) -> None:
    models = {
        "coding": {
            "model": "gpt-5.6-luna",
            "provider": "openai-codex",
            **bad_fields,
        },
        "reasoning": {
            "model": "grok-4.6",
            "provider": "xai-oauth",
            "reasoning_allowed": ["low", "medium", "high"],
            "reasoning_default": "high",
        },
    }
    normalized = _validated_pool(models)
    assert normalized is not None
    assert normalized["coding"] == {"model": "gpt-5.6-luna", "provider": "openai-codex"}
    assert normalized["reasoning"]["reasoning_default"] == "high"


def test_routing_question_union_and_selected_default_drive_directive() -> None:
    questions = build_routing_questions(POOL)
    assert list(questions) == [
        ROUTING_CHOICE,
        ROUTING_MISMATCH,
        ROUTING_WORTH,
        ROUTING_DIFFICULTY,
        ROUTING_EFFORT,
    ]
    assert questions[ROUTING_EFFORT] == {
        "type": "choice",
        "instructions": "Which reasoning effort best fits the selected model label?",
        "criteria": {"low": None, "medium": None, "high": None},
    }

    decision = evaluate_routing(
        route_response(effort="not-allowed"),
        POOL,
        current_model="z-ai/glm-5.3-flash",
        current_provider="openrouter",
        mode="first_turn",
        is_first_turn=True,
    )
    assert decision is not None and decision.switch_worthy is True
    assert decision.reasoning_effort == "medium"
    assert format_model_switch_directive(decision, allow_cache_break=False) == {
        "model_switch": {
            "model": "gpt-5.6-luna",
            "provider": "openai-codex",
            "allow_cache_break": False,
            "reasoning_effort": "medium",
        }
    }


def test_missing_optional_effort_answer_survives_evaluator_and_uses_default() -> None:
    decision = evaluate_routing(
        route_response(effort=None),
        POOL,
        current_model="z-ai/glm-5.3-flash",
        current_provider="openrouter",
        mode="first_turn",
        is_first_turn=True,
    )
    assert decision is not None and decision.switch_worthy is True
    assert decision.reasoning_effort == "medium"


def test_empty_effort_union_omits_optional_question() -> None:
    questions = build_routing_questions(
        {"cheap": {"model": "z-ai/glm-5.3-flash", "provider": "openrouter"}}
    )
    assert ROUTING_EFFORT not in questions


def test_disabled_label_omits_effort_and_same_identity_effort_is_worthy() -> None:
    cheap = evaluate_routing(
        route_response(target="cheap", effort="high"),
        POOL,
        current_model="gpt-5.6-luna",
        current_provider="openai-codex",
        mode="first_turn",
        is_first_turn=True,
    )
    assert cheap is not None and cheap.reasoning_effort is None and cheap.switch_worthy is True

    same_identity = evaluate_routing(
        route_response(target="reasoning", effort="medium"),
        POOL,
        current_model="grok-4.6",
        current_provider="xai-oauth",
        mode="cache_break_if_worth_it",
        is_first_turn=False,
    )
    assert same_identity is not None
    assert same_identity.reasoning_effort == "medium"
    assert same_identity.switch_worthy is True


def test_first_turn_is_eligible_in_both_modes_and_later_only_cache_mode() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def execute_sync(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return route_response(effort="medium", worth=0.1)

    for mode in ("first_turn", "cache_break_if_worth_it"):
        runtime = Runtime()
        handler = make_routing_directive_handler(
            {"model": "jev-1.13.0", "routing.enabled": True, "routing.mode": mode, "routing.models": POOL},
            runtime=runtime,
            secret_reader=lambda: "key",
            require_home_identity=False,
        )
        result = handler("request", True, "z-ai/glm-5.3-flash", "openrouter")
        assert result is not None
        assert result["model_switch"]["allow_cache_break"] is False
        assert ROUTING_EFFORT in runtime.calls[0]["questions"]

    runtime = Runtime()
    handler = make_routing_directive_handler(
        {
            "model": "jev-1.13.0",
            "routing.enabled": True,
            "routing.mode": "cache_break_if_worth_it",
            "routing.models": POOL,
        },
        runtime=runtime,
        secret_reader=lambda: "key",
        require_home_identity=False,
    )
    assert handler("request", False, "z-ai/glm-5.3-flash", "openrouter") is None
    assert handler("request", True, "z-ai/glm-5.3-flash", "openrouter") is not None


def test_combined_route_passes_optional_questions_without_extra_rpc() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def execute_sync(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return route_response(effort="high")

    runtime = Runtime()
    handler = make_combined_pre_llm_handler(
        {
            "model": "jev-1.13.0",
            "routing.enabled": True,
            "routing.mode": "first_turn",
            "routing.models": POOL,
            "suggestion.enabled": False,
        },
        runtime=runtime,
        secret_reader=lambda: "key",
        require_home_identity=False,
    )
    result = handler("request", True, "z-ai/glm-5.3-flash", "openrouter")
    assert result == {
        "model_switch": {
            "model": "gpt-5.6-luna",
            "provider": "openai-codex",
            "allow_cache_break": False,
            "reasoning_effort": "high",
        }
    }
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["optional_choice_questions"] == (ROUTING_EFFORT,)


class FakeRetryPolicy:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class SyntheticSDKClient:
    response_mode = "valid"

    def __init__(self, **kwargs: Any) -> None:
        self.model = kwargs["model"]

    async def system_one(self, state: Any, questions: dict[str, dict[str, Any]], *, model: str) -> Any:
        del state
        answers: dict[str, Any] = {}
        for name, question in questions.items():
            kind = question["type"]
            if kind == "choice":
                choice = next(iter(question["criteria"]))
                if name == ROUTING_CHOICE:
                    choice = "coding"
                if name == ROUTING_EFFORT:
                    choice = {
                        "valid": "medium",
                        "missing": None,
                        "wrong": 1,
                        "outside": "xhigh",
                    }.get(self.response_mode, "medium")
                    if choice is None:
                        continue
                answers[name] = {"type": "choice", "choice": choice}
                if name == ROUTING_CHOICE:
                    answers[name]["confidence"] = 0.9
            elif kind == "noul":
                answers[name] = {"type": "noul", "noul": 0.9}
            else:
                answers[name] = {
                    "type": "score",
                    "score": 0.0,
                    "legend": {"0": "routine", "1": "moderate", "2": "difficult", "3": "expert"},
                }
        if self.response_mode == "extra":
            answers["unexpected"] = {"type": "noul", "noul": 0.1}
        return {"model": model, "answers": answers, "usage": {}}

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def clean_broker() -> Any:
    broker._reset_for_tests()
    yield
    broker.shutdown(9999999999.0)
    broker._reset_for_tests()


def runtime_with_synthetic_sdk(monkeypatch: pytest.MonkeyPatch) -> TypeSafeRuntime:
    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: SimpleNamespace(AsyncTypeSafeClient=SyntheticSDKClient, RetryPolicy=FakeRetryPolicy),
    )
    return TypeSafeRuntime(broker_loader=lambda: broker, client_factory=client.AsyncTypeSafeClient)


@pytest.mark.parametrize("mode, present", [("valid", True), ("missing", False), ("wrong", False), ("outside", False)])
@pytest.mark.skipif(
    sys.version_info[:2] not in {(3, 10), (3, 11), (3, 12)},
    reason="canonical broker supports CPython 3.10-3.12 main interpreters only",
)
def test_runtime_client_path_omits_only_invalid_optional_choice(
    monkeypatch: pytest.MonkeyPatch, mode: str, present: bool
) -> None:
    SyntheticSDKClient.response_mode = mode
    runtime = runtime_with_synthetic_sdk(monkeypatch)
    try:
        result = runtime.execute_sync(
            state="request",
            questions=build_routing_questions(POOL),
            model="jev-1.13.0",
            api_key="key",
            timeout=2.0,
            optional_choice_questions=(ROUTING_EFFORT,),
        )
    finally:
        runtime.close()
    assert (ROUTING_EFFORT in result["answers"]) is present
    if not present:
        decision = evaluate_routing(
            result,
            POOL,
            current_model="z-ai/glm-5.3-flash",
            current_provider="openrouter",
            mode="first_turn",
            is_first_turn=True,
        )
        assert decision is not None and decision.reasoning_effort == "medium"


@pytest.mark.skipif(
    sys.version_info[:2] not in {(3, 10), (3, 11), (3, 12)},
    reason="canonical broker supports CPython 3.10-3.12 main interpreters only",
)
def test_runtime_client_path_keeps_core_and_envelope_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    SyntheticSDKClient.response_mode = "extra"
    runtime = runtime_with_synthetic_sdk(monkeypatch)
    with pytest.raises(client.ClientError) as error:
        try:
            runtime.execute_sync(
                state="request",
                questions=build_routing_questions(POOL),
                model="jev-1.13.0",
                api_key="key",
                timeout=2.0,
                optional_choice_questions=(ROUTING_EFFORT,),
            )
        finally:
            runtime.close()
    assert error.value.code == "invalid_response"


def test_ordinary_system_one_remains_strict_for_optional_named_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    SyntheticSDKClient.response_mode = "missing"
    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: SimpleNamespace(AsyncTypeSafeClient=SyntheticSDKClient, RetryPolicy=FakeRetryPolicy),
    )

    async def run() -> None:
        wrapper = client.AsyncTypeSafeClient(api_key="key")
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one("request", build_routing_questions(POOL))
        assert error.value.code == "invalid_response"

    asyncio.run(run())


def test_optional_choice_policy_rejects_non_choice_or_unrequested_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: pytest.fail("SDK must not load for invalid local optional policy"),
    )

    async def run() -> None:
        wrapper = client.AsyncTypeSafeClient(api_key="key")
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one(
                "request",
                {"plain": {"type": "noul", "instructions": "plain"}},
                optional_choice_questions=("plain",),
            )
        assert error.value.code == "invalid_input"

    asyncio.run(run())
