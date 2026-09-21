"""Reviewed fork-harness callbacks for suggestion, guardrails, final screening, and routing."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

try:
    from .guard import (
        GuardInputError,
        build_tool_guard_request,
        evaluate_tool_arguments,
        represent_final_text,
    )
    from .limits import LimitsError, _validate_and_encode
    from .questions import (
        DEFAULT_MODEL,
        FINAL_GUARD_QUESTIONS,
        GUARD_STATIC_SENSITIVE_BLOCK,
        GUARD_STATIC_TOOL_BLOCK,
        GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX,
        HARNESS_CAPABILITIES,
        HOOK_TIMEOUT_SECONDS,
        MAX_FINAL_RPC,
        MAX_GUARD_RPC,
        MAX_PRE_LLM_RPC,
        MAX_STATE_BYTES,
        ROUTING_ACTIVE_MODES,
        ROUTING_EFFORT,
        SUGGESTION_MISS_CONTEXT,
        USEFUL_HOOK_SECONDS,
    )
    from .route import (
        _current_label,
        _validated_pool,
        build_routing_questions,
        evaluate_routing,
        format_model_switch_directive,
    )
    from .runtime import TypeSafeRuntime
    from .skills_adapter import host_snapshot_to_verified, snapshots_match
    from .suggest import (
        build_rank_request,
        build_rerank_request,
        evaluate_suggestion,
        rank_shortlist,
    )
    from .tool_system_one import _home_matches, _read_scoped_secret, _valid_scoped_secret
except ImportError:  # pragma: no cover - flat plugin import
    from guard import GuardInputError, build_tool_guard_request, evaluate_tool_arguments, represent_final_text
    from limits import LimitsError, _validate_and_encode
    from questions import (
        DEFAULT_MODEL,
        FINAL_GUARD_QUESTIONS,
        GUARD_STATIC_SENSITIVE_BLOCK,
        GUARD_STATIC_TOOL_BLOCK,
        GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX,
        HARNESS_CAPABILITIES,
        HOOK_TIMEOUT_SECONDS,
        MAX_FINAL_RPC,
        MAX_GUARD_RPC,
        MAX_PRE_LLM_RPC,
        MAX_STATE_BYTES,
        ROUTING_ACTIVE_MODES,
        ROUTING_EFFORT,
        SUGGESTION_MISS_CONTEXT,
        USEFUL_HOOK_SECONDS,
    )
    from route import _current_label, _validated_pool, build_routing_questions, evaluate_routing, format_model_switch_directive
    from runtime import TypeSafeRuntime
    from skills_adapter import host_snapshot_to_verified, snapshots_match
    from suggest import build_rank_request, build_rerank_request, evaluate_suggestion, rank_shortlist
    from tool_system_one import _home_matches, _read_scoped_secret, _valid_scoped_secret


def supports_reviewed_harness(ctx: Any) -> bool:
    """Require the complete public fork API before exposing any harness callback."""

    try:
        capabilities = getattr(ctx, "capabilities", None)
        register_hook = getattr(ctx, "register_hook", None)
        snapshot_reader = getattr(ctx, "skills_snapshot", None)
    except Exception:
        return False
    if not isinstance(capabilities, (set, frozenset)) or not HARNESS_CAPABILITIES.issubset(capabilities):
        return False
    if not callable(register_hook) or not callable(snapshot_reader):
        return False
    try:
        parameters = inspect.signature(register_hook).parameters
    except (TypeError, ValueError):
        return False
    phase = parameters.get("phase")
    return phase is not None and phase.kind in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }


def register_hook_checked(ctx: Any, name: str, callback: Callable, *, phase: str = "normal") -> bool:
    """Register only through the reviewed phase-aware public hook seam."""

    if not callable(getattr(ctx, "register_hook", None)):
        return False
    try:
        ctx.register_hook(name, callback, phase=phase)
    except Exception:
        return False
    return True


def _deadline_remaining(started: float, clock: Callable[[], float]) -> float:
    elapsed = clock() - started
    return min(HOOK_TIMEOUT_SECONDS - elapsed, USEFUL_HOOK_SECONDS - elapsed)


def _read_key(read_secret: Callable[[], Any]) -> str | None:
    try:
        value = read_secret()
    except Exception:
        return None
    return value if _valid_scoped_secret(value) else None


def _harness_model(settings: Mapping[str, Any]) -> str | None:
    """Accept only the reviewed exact model label for harness requests."""

    value = settings.get("model", DEFAULT_MODEL)
    return DEFAULT_MODEL if value == DEFAULT_MODEL else None


def _eligible_routing_pool(settings: Mapping[str, Any]) -> dict[str, dict[str, Any]] | None:
    """Return a validated pool only when routing is eligible to run."""

    if settings.get("routing.enabled") is not True:
        return None
    if settings.get("routing.mode") not in ROUTING_ACTIVE_MODES:
        return None
    return _validated_pool(settings.get("routing.models", {}))


def make_combined_pre_llm_handler(
    settings: Mapping[str, Any],
    *,
    snapshot_reader: Callable[[], Any] | None = None,
    runtime: Any = None,
    secret_reader: Callable[[], Any] | None = None,
    home_identity: str | None = None,
    require_home_identity: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[..., Any]:
    """Create the single supported-host pre-LLM callback.

    Routing runs first, then suggestion. Both receive detached allowlisted state and
    share one absolute budget and one runtime admission path; no history or system
    prompt enters either request.
    """

    detached = {key: value for key, value in settings.items() if type(key) is str}
    route_pool = _eligible_routing_pool(detached)
    route_enabled = route_pool is not None
    suggestion_enabled = detached.get("suggestion.enabled") is True
    active_runtime = runtime or TypeSafeRuntime(
        settings=detached,
        home_identity=home_identity,
        require_home_identity=require_home_identity,
    )
    read_secret = secret_reader or _read_scoped_secret
    get_snapshot = snapshot_reader
    harness_model = _harness_model(detached)

    def handler(
        user_message: Any,
        is_first_turn: Any = False,
        model: Any = None,
        provider: Any = None,
    ) -> Any:
        if not route_enabled and not suggestion_enabled:
            return None
        if harness_model is None:
            return None
        if not _home_matches(home_identity, required=require_home_identity):
            return None
        key = _read_key(read_secret)
        if key is None:
            return None
        started = clock()
        calls = 0
        output: dict[str, Any] = {}

        if route_pool is not None and calls < MAX_PRE_LLM_RPC:
            mode = detached.get("routing.mode")
            eligible = type(is_first_turn) is bool and (
                is_first_turn is True
                or (mode == "cache_break_if_worth_it" and is_first_turn is False)
            )
            current_label = _current_label(route_pool, model, provider)
            remaining = _deadline_remaining(started, clock)
            if (
                eligible
                and current_label is not None
                and type(model) is str
                and type(provider) is str
                and bool(provider)
                and type(user_message) is str
                and remaining > 0
            ):
                try:
                    calls += 1
                    questions = build_routing_questions(route_pool)
                    runtime_kwargs: dict[str, Any] = {
                        "state": {"user_message": user_message, "current_label": current_label},
                        "questions": questions,
                        "model": harness_model,
                        "api_key": key,
                        "timeout": remaining,
                    }
                    if ROUTING_EFFORT in questions:
                        runtime_kwargs["optional_choice_questions"] = (ROUTING_EFFORT,)
                    route_response = active_runtime.execute_sync(**runtime_kwargs)
                    decision = evaluate_routing(
                        route_response,
                        route_pool,
                        current_model=model,
                        current_provider=provider,
                        mode=mode,
                        is_first_turn=is_first_turn,
                    )
                    if decision is not None and decision.switch_worthy:
                        output.update(
                            format_model_switch_directive(
                                decision,
                                allow_cache_break=is_first_turn is False,
                            )
                        )
                except Exception:
                    pass

        if suggestion_enabled and calls < MAX_PRE_LLM_RPC and get_snapshot is not None:
            remaining = _deadline_remaining(started, clock)
            if type(user_message) is str and remaining > 0:
                try:
                    first_host_snapshot = get_snapshot()
                    first_snapshot = host_snapshot_to_verified(first_host_snapshot)
                    if first_snapshot is not None and first_snapshot.skills:
                        rank_state, rank_questions = build_rank_request(user_message, first_snapshot)
                        calls += 1
                        rank_response = active_runtime.execute_sync(
                            state=rank_state,
                            questions=rank_questions,
                            model=harness_model,
                            api_key=key,
                            timeout=remaining,
                        )
                        shortlist = rank_shortlist(first_snapshot, rank_response)
                        if shortlist is not None:
                            rank_only = evaluate_suggestion(user_message, first_snapshot, rank_response, None)
                            if rank_only == SUGGESTION_MISS_CONTEXT:
                                output["context"] = SUGGESTION_MISS_CONTEXT
                            else:
                                latest_host_snapshot = get_snapshot()
                                latest_snapshot = host_snapshot_to_verified(latest_host_snapshot)
                                if latest_snapshot is not None and snapshots_match(first_snapshot, latest_snapshot):
                                    remaining = _deadline_remaining(started, clock)
                                    if remaining > 0 and calls < MAX_PRE_LLM_RPC:
                                        rerank_state, rerank_questions = build_rerank_request(
                                            user_message, first_snapshot, shortlist
                                        )
                                        calls += 1
                                        rerank_response = active_runtime.execute_sync(
                                            state=rerank_state,
                                            questions=rerank_questions,
                                            model=harness_model,
                                            api_key=key,
                                            timeout=remaining,
                                        )
                                        context = evaluate_suggestion(
                                            user_message,
                                            first_snapshot,
                                            rank_response,
                                            rerank_response,
                                        )
                                        if context is not None:
                                            output["context"] = context
                except Exception:
                    pass

        return output or None

    handler._typesafe_runtime = active_runtime  # type: ignore[attr-defined]
    handler._max_rpc = MAX_PRE_LLM_RPC  # type: ignore[attr-defined]
    return handler


def make_pre_tool_guard_handler(
    settings: Mapping[str, Any],
    *,
    runtime: Any = None,
    secret_reader: Callable[[], Any] | None = None,
    home_identity: str | None = None,
    require_home_identity: bool = True,
    clock: Callable[[], float] = time.monotonic,
    plugin_instance_scope: str | None = None,
) -> Callable[..., dict[str, Any] | None]:
    """Create one fail-closed native pre-tool decision callback."""

    detached = {key: value for key, value in settings.items() if type(key) is str}
    active_runtime = runtime or TypeSafeRuntime(
        settings=detached,
        home_identity=home_identity,
        require_home_identity=require_home_identity,
    )
    read_secret = secret_reader or _read_scoped_secret
    harness_model = _harness_model(detached)
    guard_enabled = detached.get("guardrails.enabled") is True
    scope = plugin_instance_scope
    if scope is None:
        try:
            from .guard import new_plugin_instance_scope
        except ImportError:  # pragma: no cover
            from guard import new_plugin_instance_scope
        try:
            scope = new_plugin_instance_scope()
        except Exception:
            scope = None

    def handler(
        tool_name: Any,
        args: Any,
        session_id: Any = None,
        tool_call_id: Any = None,
        execution_nonce: Any = None,
        registration_generation: Any = None,
    ) -> dict[str, Any] | None:
        del execution_nonce, registration_generation
        if not guard_enabled:
            return None
        if tool_name == "system_one":
            return None
        if harness_model is None:
            return {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
        try:
            request = build_tool_guard_request(tool_name, args)
        except GuardInputError as error:
            message = GUARD_STATIC_SENSITIVE_BLOCK if error.code == "sensitive_argument" else GUARD_STATIC_TOOL_BLOCK
            return {"action": "block", "message": message}
        if request is None or scope is None:
            return {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
        if not _home_matches(home_identity, required=require_home_identity):
            return {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
        key = _read_key(read_secret)
        if key is None:
            return {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
        started = clock()
        remaining = min(HOOK_TIMEOUT_SECONDS, USEFUL_HOOK_SECONDS - (clock() - started))
        if remaining <= 0:
            return {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
        try:
            state, questions = request
            results = active_runtime.execute_sync(
                state=state,
                questions=questions,
                model=harness_model,
                api_key=key,
                timeout=remaining,
            )
            assessment = evaluate_tool_arguments(
                tool_name,
                args,
                results,
                session_id=session_id,
                tool_call_id=tool_call_id,
                plugin_instance_scope=scope,
            )
        except Exception:
            return {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
        if assessment.action == "approve" and assessment.rule_key is not None:
            return {
                "action": "approve",
                "message": assessment.message,
                "rule_key": assessment.rule_key,
            }
        if assessment.action == "pass":
            return None
        return {"action": "block", "message": assessment.message or GUARD_STATIC_TOOL_BLOCK}

    handler._typesafe_runtime = active_runtime  # type: ignore[attr-defined]
    handler._max_rpc = MAX_GUARD_RPC  # type: ignore[attr-defined]
    return handler


def make_final_guard_handler(
    settings: Mapping[str, Any],
    *,
    runtime: Any = None,
    secret_reader: Callable[[], Any] | None = None,
    home_identity: str | None = None,
    require_home_identity: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[[Any], str]:
    """Create one static final-output screen; streaming is never buffered or retracted."""

    detached = {key: value for key, value in settings.items() if type(key) is str}
    active_runtime = runtime or TypeSafeRuntime(
        settings=detached,
        home_identity=home_identity,
        require_home_identity=require_home_identity,
    )
    read_secret = secret_reader or _read_scoped_secret
    harness_model = _harness_model(detached)

    def unavailable(response_text: Any) -> str:
        if type(response_text) is not str:
            return GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX
        return f"{GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX}\n{response_text}"

    def handler(response_text: Any) -> str:
        if detached.get("guardrails.enabled") is not True:
            return response_text if type(response_text) is str else ""
        try:
            _validate_and_encode(
                response_text,
                cap=MAX_STATE_BYTES,
                code="payload_too_large",
                root_kind="state",
            )
        except LimitsError:
            return unavailable(response_text)
        if not _home_matches(home_identity, required=require_home_identity):
            return represent_final_text(response_text, None).text
        if harness_model is None:
            return represent_final_text(response_text, None).text
        key = _read_key(read_secret)
        if key is None:
            return represent_final_text(response_text, None).text
        started = clock()
        remaining = min(HOOK_TIMEOUT_SECONDS, USEFUL_HOOK_SECONDS - (clock() - started))
        if remaining <= 0:
            return represent_final_text(response_text, None).text
        try:
            results = active_runtime.execute_sync(
                state=response_text,
                questions=deepcopy(FINAL_GUARD_QUESTIONS),
                model=harness_model,
                api_key=key,
                timeout=remaining,
            )
        except Exception:
            results = None
        return represent_final_text(response_text, results).text

    handler._typesafe_runtime = active_runtime  # type: ignore[attr-defined]
    handler._max_rpc = MAX_FINAL_RPC  # type: ignore[attr-defined]
    return handler


__all__ = [
    "HARNESS_CAPABILITIES",
    "GUARD_STATIC_TOOL_BLOCK",
    "make_combined_pre_llm_handler",
    "make_final_guard_handler",
    "make_pre_tool_guard_handler",
    "register_hook_checked",
    "supports_reviewed_harness",
]
