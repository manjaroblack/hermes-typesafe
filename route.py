"""Bounded model-routing helpers for the reviewed TypeSafe host harness.

The supported-host directive callback returns a host-applied `{model, provider}`
directive. The legacy pure advisory helper remains available for offline
compatibility tests and is not registered by the plugin.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

try:
    from .limits import MAX_MODEL_BYTES, MAX_STRING_BYTES
    from .questions import (
        DEFAULT_MODEL,
        ROUTING_CHOICE,
        ROUTING_DIFFICULTY,
        ROUTING_EFFORT,
        ROUTING_DIFFICULTY_LEVELS,
        ROUTING_ACTIVE_MODES,
        ROUTING_HIGH,
        ROUTING_MISMATCH,
        ROUTING_MODES,
        ROUTING_POOL_NAMES,
        ROUTING_WORTH,
        USEFUL_HOOK_SECONDS,
        routing_questions,
    )
    from .pool import normalize_routing_pool, reasoning_effort_union
    from .runtime import HOOK_TIMEOUT_SECONDS, TypeSafeRuntime
    from .tool_system_one import _home_matches, _read_scoped_secret, _valid_scoped_secret
except ImportError:  # pragma: no cover - flat plugin import
    from limits import MAX_MODEL_BYTES, MAX_STRING_BYTES
    from questions import (
        DEFAULT_MODEL,
        ROUTING_CHOICE,
        ROUTING_DIFFICULTY,
        ROUTING_EFFORT,
        ROUTING_DIFFICULTY_LEVELS,
        ROUTING_ACTIVE_MODES,
        ROUTING_HIGH,
        ROUTING_MISMATCH,
        ROUTING_MODES,
        ROUTING_POOL_NAMES,
        ROUTING_WORTH,
        USEFUL_HOOK_SECONDS,
        routing_questions,
    )
    from pool import normalize_routing_pool, reasoning_effort_union
    from runtime import HOOK_TIMEOUT_SECONDS, TypeSafeRuntime
    from tool_system_one import _home_matches, _read_scoped_secret, _valid_scoped_secret

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Validated routing evidence detached from the host callback payload."""

    target_name: str
    target_model: str
    target_provider: str
    mismatch: float
    worth_breaking_cache: float
    confidence: float | None
    difficulty: float
    switch_worthy: bool
    reasoning_effort: str | None = None


def _finite_probability(value: Any) -> float | None:
    if type(value) not in (int, float) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        return None
    return number


def _bounded_identifier(value: Any, *, allow_empty: bool = False) -> str | None:
    if type(value) is not str or (not allow_empty and not value):
        return None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if len(encoded) > MAX_MODEL_BYTES:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    return value


def _validated_pool(models: Any) -> dict[str, dict[str, Any]] | None:
    pool = normalize_routing_pool(models)
    if pool is None:
        return None
    return pool


def _answers(response: Any) -> dict[str, Any] | None:
    if type(response) is not dict:
        return None
    answers = response.get("answers")
    return answers if type(answers) is dict else None


def _typed_answer(answers: Mapping[str, Any], name: str, kind: str) -> dict[str, Any] | None:
    answer = answers.get(name)
    if type(answer) is not dict or answer.get("type") != kind:
        return None
    return answer


def _valid_user_message(value: Any) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= MAX_STRING_BYTES


def _unique_models(pool: Mapping[str, Mapping[str, Any]]) -> bool:
    model_names = [entry["model"] for entry in pool.values()]
    return len(model_names) == len(set(model_names))


def _unique_identities(pool: Mapping[str, Mapping[str, Any]]) -> bool:
    identities = {(entry["model"], entry["provider"]) for entry in pool.values()}
    return len(identities) == len(pool)


def _current_identity_is_unambiguous(
    pool: Mapping[str, Mapping[str, Any]], current_model: Any, current_provider: Any = None
) -> bool:
    current = _bounded_identifier(current_model)
    provider = None if current_provider is None else _bounded_identifier(current_provider)
    if current is None or (current_provider is not None and provider is None):
        return False
    if current_provider is None and not _unique_models(pool):
        return False
    if not _unique_identities(pool):
        return False
    matches = [
        entry for entry in pool.values()
        if entry["model"] == current and (provider is None or entry["provider"] == provider)
    ]
    return len(matches) == 1


def build_routing_questions(models: Any) -> dict[str, dict[str, Any]]:
    """Build the one typed batch from a validated local model pool."""

    pool = _validated_pool(models)
    if pool is None:
        raise ValueError("routing model pool is invalid")
    return routing_questions(tuple(pool), effort_options=reasoning_effort_union(pool))


def evaluate_routing(
    response: Any,
    models: Any,
    *,
    current_model: Any,
    current_provider: Any = None,
    mode: Any = "cache_break_if_worth_it",
    is_first_turn: Any | None = None,
) -> RoutingDecision | None:
    """Validate one response and apply the selected routing mode's switch gates."""

    pool = _validated_pool(models)
    if pool is None or mode not in ROUTING_ACTIVE_MODES:
        return None
    answers = _answers(response)
    effort_options = reasoning_effort_union(pool)
    expected = {ROUTING_CHOICE, ROUTING_MISMATCH, ROUTING_WORTH, ROUTING_DIFFICULTY}
    if answers is None or not expected <= set(answers):
        return None
    optional_names = set(answers) - expected
    if optional_names and (not effort_options or optional_names != {ROUTING_EFFORT}):
        return None

    choice = _typed_answer(answers, ROUTING_CHOICE, "choice")
    mismatch_answer = _typed_answer(answers, ROUTING_MISMATCH, "noul")
    worth_answer = _typed_answer(answers, ROUTING_WORTH, "noul")
    difficulty_answer = _typed_answer(answers, ROUTING_DIFFICULTY, "score")
    if choice is None or mismatch_answer is None or worth_answer is None or difficulty_answer is None:
        return None

    target_name = choice.get("choice")
    if type(target_name) is not str or target_name not in pool:
        return None
    mismatch = _finite_probability(mismatch_answer.get("noul"))
    worth = _finite_probability(worth_answer.get("noul"))
    raw_difficulty = difficulty_answer.get("score")
    if mismatch is None or worth is None or type(raw_difficulty) not in (int, float) or isinstance(raw_difficulty, bool):
        return None
    difficulty = float(raw_difficulty)
    criteria = difficulty_answer.get("legend")
    if (
        type(criteria) is not dict
        or not math.isfinite(difficulty)
        or difficulty < 0
        or difficulty > len(ROUTING_DIFFICULTY_LEVELS) - 1
    ):
        return None
    allowed_criteria = set(range(len(ROUTING_DIFFICULTY_LEVELS)))
    normalized_criteria: set[int] = set()
    for key in criteria:
        if type(key) is int and key in allowed_criteria:
            normalized_criteria.add(key)
        elif type(key) is str and key.isdecimal() and int(key) in allowed_criteria:
            normalized_criteria.add(int(key))
        else:
            return None
    if normalized_criteria != set(range(len(ROUTING_DIFFICULTY_LEVELS))):
        return None

    raw_confidence = choice.get("confidence")
    confidence = None if raw_confidence is None else _finite_probability(raw_confidence)
    if raw_confidence is not None and confidence is None:
        return None

    target_model = pool[target_name]["model"]
    target_provider = pool[target_name]["provider"]
    reasoning_effort = None
    if effort_options:
        selected = pool[target_name]
        allowed = selected.get("reasoning_allowed", [])
        effort_answer = _typed_answer(answers, ROUTING_EFFORT, "choice")
        candidate = effort_answer.get("choice") if effort_answer is not None else None
        if type(candidate) is str and candidate in effort_options and candidate in allowed:
            reasoning_effort = candidate
        else:
            default = selected.get("reasoning_default")
            if type(default) is str and default in allowed:
                reasoning_effort = default
    current = _bounded_identifier(current_model)
    current_provider_value = None if current_provider is None else _bounded_identifier(current_provider)
    same_target = target_model == current and (
        current_provider is None or target_provider == current_provider_value
    )
    first_turn = mode == "first_turn" if is_first_turn is None else is_first_turn
    if type(first_turn) is not bool:
        return None
    eligible = first_turn is True or (mode == "cache_break_if_worth_it" and first_turn is False)
    switch_worthy = (
        eligible
        and mismatch >= ROUTING_HIGH
        and (first_turn or worth >= ROUTING_HIGH)
        and confidence is not None
        and confidence >= ROUTING_HIGH
        and current is not None
        and _current_identity_is_unambiguous(pool, current, current_provider)
        and (not same_target or reasoning_effort is not None)
    )
    return RoutingDecision(
        target_name=target_name,
        target_model=target_model,
        target_provider=target_provider,
        reasoning_effort=reasoning_effort,
        mismatch=mismatch,
        worth_breaking_cache=worth,
        confidence=confidence,
        difficulty=difficulty,
        switch_worthy=switch_worthy,
    )


def format_routing_hint(target_name: str) -> str:
    """Format a static current-user advisory suffix for a configured label."""

    if type(target_name) is not str or target_name not in ROUTING_POOL_NAMES:
        raise ValueError("routing target is invalid")
    return (
        f"Routing hint: consider the configured {target_name} model for this request. "
        "No model switch was performed."
    )


def format_model_switch_directive(decision: RoutingDecision, *, allow_cache_break: bool) -> dict[str, Any]:
    """Return the reviewed fork directive; the host turn thread applies it."""

    if not decision.switch_worthy or type(allow_cache_break) is not bool:
        raise ValueError("routing decision is not switch-worthy")
    directive = {
        "model": decision.target_model,
        "provider": decision.target_provider,
        "allow_cache_break": allow_cache_break,
    }
    if decision.reasoning_effort is not None:
        directive["reasoning_effort"] = decision.reasoning_effort
    return {"model_switch": directive}


def _current_label(pool: Mapping[str, Mapping[str, Any]], current_model: Any, current_provider: Any) -> str | None:
    if not _current_identity_is_unambiguous(pool, current_model, current_provider):
        return None
    model = _bounded_identifier(current_model)
    provider = _bounded_identifier(current_provider)
    matches = [
        name for name, entry in pool.items()
        if entry["model"] == model and (provider is None or entry["provider"] == provider)
    ]
    return matches[0] if len(matches) == 1 else None


def make_routing_directive_handler(
    settings: Mapping[str, Any],
    *,
    runtime: Any = None,
    secret_reader: Callable[[], Any] | None = None,
    home_identity: str | None = None,
    require_home_identity: bool = True,
    clock: Callable[[], float] = time.monotonic,
    logger: logging.Logger | None = None,
) -> Callable[..., dict[str, Any] | None]:
    """Create a supported-host callback returning a host-applied model directive."""

    detached = {key: value for key, value in settings.items() if type(key) is str}
    enabled = detached.get("routing.enabled", False)
    mode = detached.get("routing.mode", "off")
    pool = _validated_pool(detached.get("routing.models", {}))
    selected_model = detached.get("model", DEFAULT_MODEL)
    if selected_model != DEFAULT_MODEL:
        selected_model = None
    active_runtime = runtime or TypeSafeRuntime(
        settings=detached,
        home_identity=home_identity,
        require_home_identity=require_home_identity,
    )
    read_secret = secret_reader or _read_scoped_secret
    del logger

    def handler(
        user_message: Any,
        is_first_turn: Any = False,
        model: Any = None,
        provider: Any = None,
    ) -> dict[str, Any] | None:
        started = clock()
        if (
            pool is None
            or selected_model is None
            or enabled is not True
            or mode not in ROUTING_ACTIVE_MODES
        ):
            return None
        if type(is_first_turn) is not bool:
            return None
        if not (is_first_turn is True or (mode == "cache_break_if_worth_it" and is_first_turn is False)):
            return None
        current_label = _current_label(pool, model, provider)
        if current_label is None or type(provider) is not str or not provider or not _valid_user_message(user_message):
            return None
        if not _home_matches(home_identity, required=require_home_identity):
            return None
        try:
            key = read_secret()
        except Exception:
            return None
        if not _valid_scoped_secret(key):
            return None
        remaining = min(HOOK_TIMEOUT_SECONDS, USEFUL_HOOK_SECONDS - (clock() - started))
        if remaining <= 0:
            return None
        try:
            questions = build_routing_questions(pool)
            runtime_kwargs: dict[str, Any] = {
                "state": {"user_message": user_message, "current_label": current_label},
                "questions": questions,
                "model": selected_model,
                "api_key": key,
                "timeout": min(remaining, HOOK_TIMEOUT_SECONDS),
            }
            if ROUTING_EFFORT in questions:
                runtime_kwargs["optional_choice_questions"] = (ROUTING_EFFORT,)
            result = active_runtime.execute_sync(**runtime_kwargs)
            decision = evaluate_routing(
                result,
                pool,
                current_model=model,
                current_provider=provider,
                mode=mode,
                is_first_turn=is_first_turn,
            )
        except Exception:
            return None
        if decision is None or not decision.switch_worthy:
            return None
        allow_cache_break = is_first_turn is False
        return format_model_switch_directive(decision, allow_cache_break=allow_cache_break)

    handler._typesafe_runtime = active_runtime  # type: ignore[attr-defined]
    handler._routing_pool = pool  # type: ignore[attr-defined]
    return handler


def compose_advisory_context(suggestion_context: Any, routing_hint: Any) -> str | None:
    """Compose future suggestion text before routing text without duplicates."""

    parts: list[str] = []
    for value in (suggestion_context, routing_hint):
        if type(value) is not str or not value.strip() or value in parts:
            continue
        parts.append(value)
    return "\n\n".join(parts) or None


def _eligible(mode: Any, enabled: Any, is_first_turn: Any) -> bool:
    if enabled is not True or type(mode) is not str or mode not in ROUTING_MODES:
        return False
    if mode == "off" or type(is_first_turn) is not bool:
        return False
    return is_first_turn is True or (mode == "cache_break_if_worth_it" and is_first_turn is False)


def make_routing_handler(
    settings: Mapping[str, Any],
    *,
    runtime: Any = None,
    secret_reader: Callable[[], Any] | None = None,
    home_identity: str | None = None,
    require_home_identity: bool = True,
    clock: Callable[[], float] = time.monotonic,
    logger: logging.Logger | None = None,
) -> Callable[..., str | None]:
    """Create a synchronous fail-open ``pre_llm_call`` advisory callback."""

    detached = {key: value for key, value in settings.items() if type(key) is str}
    enabled = detached.get("routing.enabled", False)
    mode = detached.get("routing.mode", "first_turn")
    pool = _validated_pool(detached.get("routing.models", {}))
    selected_model = detached.get("model", DEFAULT_MODEL)
    if _bounded_identifier(selected_model) is None:
        selected_model = DEFAULT_MODEL
    active_runtime = runtime or TypeSafeRuntime(
        settings=detached,
        home_identity=home_identity,
        require_home_identity=require_home_identity,
    )
    read_secret = secret_reader or _read_scoped_secret
    del logger

    def handler(**kwargs: Any) -> str | None:
        deadline = clock() + HOOK_TIMEOUT_SECONDS
        # Deliberately read only the documented projection; unknown kwargs remain untouched.
        user_message = kwargs.get("user_message")
        is_first_turn = kwargs.get("is_first_turn", False)
        current_model = kwargs.get("model")
        if pool is None or not _eligible(mode, enabled, is_first_turn):
            return None
        if not _valid_user_message(user_message) or not _current_identity_is_unambiguous(pool, current_model):
            return None
        if not _home_matches(home_identity, required=require_home_identity):
            return None
        try:
            key = read_secret()
        except Exception:
            return None
        if not _valid_scoped_secret(key):
            return None
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        try:
            questions = build_routing_questions(pool)
            runtime_kwargs: dict[str, Any] = {
                "state": user_message,
                "questions": questions,
                "model": selected_model,
                "api_key": key,
                "timeout": remaining,
            }
            if ROUTING_EFFORT in questions:
                runtime_kwargs["optional_choice_questions"] = (ROUTING_EFFORT,)
            result = active_runtime.execute_sync(**runtime_kwargs)
            decision = evaluate_routing(
                result,
                pool,
                current_model=current_model,
                mode=mode,
                is_first_turn=is_first_turn,
            )
        except Exception:
            return None
        if decision is None or not decision.switch_worthy:
            return None
        return format_routing_hint(decision.target_name)

    handler._typesafe_runtime = active_runtime  # type: ignore[attr-defined]
    handler._routing_pool = pool  # type: ignore[attr-defined]
    return handler


# Descriptive aliases for fixture callers and future integration work.
evaluate_route = evaluate_routing
build_route_questions = build_routing_questions
format_hint = format_routing_hint


__all__ = [
    "ROUTING_CHOICE",
    "ROUTING_DIFFICULTY",
    "ROUTING_EFFORT",
    "ROUTING_MISMATCH",
    "ROUTING_POOL_NAMES",
    "ROUTING_WORTH",
    "RoutingDecision",
    "build_route_questions",
    "build_routing_questions",
    "compose_advisory_context",
    "evaluate_route",
    "evaluate_routing",
    "format_model_switch_directive",
    "format_hint",
    "format_routing_hint",
    "make_routing_directive_handler",
    "make_routing_handler",
]
