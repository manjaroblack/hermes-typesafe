"""Typed TypeSafe System One tool and native registration boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable

if __package__:
    from .client import ClientError, _error_from_exception
    from .limits import preflight_request
    from .questions import DEFAULT_MODEL
    from .runtime import TOOL_TIMEOUT_SECONDS, TypeSafeRuntime, _effective_home
else:  # pragma: no cover - flat plugin smoke import
    from client import ClientError, _error_from_exception
    from limits import preflight_request
    from questions import DEFAULT_MODEL
    from runtime import TOOL_TIMEOUT_SECONDS, TypeSafeRuntime, _effective_home

API_KEY_ENV = "TYPESAFE_API_KEY"
TOOL_NAME = "system_one"
_INTERNAL_KWARGS = frozenset({"_runtime", "_settings", "_home_identity", "_require_home_identity"})

_JSON_CONTENT = {
    "oneOf": [
        {"type": "string"},
        {"type": "object"},
        {"type": "array"},
    ]
}
_NOUl = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "noul"},
        "instructions": _JSON_CONTENT,
        "criteria": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "true": {"oneOf": [_JSON_CONTENT, {"type": "null"}]},
                "false": {"oneOf": [_JSON_CONTENT, {"type": "null"}]},
            },
        },
    },
    "required": ["type", "instructions"],
}
_CHOICE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "choice"},
        "instructions": _JSON_CONTENT,
        "criteria": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"oneOf": [_JSON_CONTENT, {"type": "null"}]},
        },
    },
    "required": ["type", "instructions", "criteria"],
}
_SCORE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "score"},
        "instructions": _JSON_CONTENT,
        "criteria": {"type": "array", "minItems": 2, "items": _JSON_CONTENT},
    },
    "required": ["type", "instructions", "criteria"],
}
QUESTION_SCHEMA = {"oneOf": [_NOUl, _CHOICE, _SCORE]}

SYSTEM_ONE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "state": {
            "oneOf": [
                {"type": "string"},
                {"type": "object"},
                {"type": "array"},
            ],
        },
        "questions": {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 16,
            "additionalProperties": QUESTION_SCHEMA,
        },
        "model": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["state", "questions"],
}


def _read_scoped_secret() -> str | None:
    """Read only the caller-scoped TypeSafe secret; never use environment fallback."""

    try:
        from agent.secret_scope import get_secret
    except Exception:
        return None
    try:
        value = get_secret(API_KEY_ENV, None)
    except Exception:
        return None
    return value if type(value) is str else None


def _home_matches(home_identity: str | None, *, required: bool) -> bool:
    if not required:
        return True
    return type(home_identity) is str and bool(home_identity) and _effective_home() == home_identity


def _valid_scoped_secret(value: Any) -> bool:
    if type(value) is not str or not value.strip() or len(value) > 4_096:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def has_api_key(*, home_identity: str | None = None, require_home_identity: bool = False) -> bool:
    """Return whether a non-blank caller-scoped key exists."""

    if not _home_matches(home_identity, required=require_home_identity):
        return False
    value = _read_scoped_secret()
    return _valid_scoped_secret(value)


def _error_result(error: BaseException) -> dict[str, Any]:
    if isinstance(error, ClientError):
        return {"error": error.as_error()}
    code = getattr(error, "code", None)
    if type(code) is str and code in ClientError.MESSAGES:
        return {"error": ClientError(code).as_error()}
    sanitized = _error_from_exception(error)
    return {"error": sanitized.as_error()}


def _execute_request(
    state: Any,
    questions: Any,
    model: Any,
    *,
    api_key: Any,
    settings: Mapping[str, Any],
    runtime: TypeSafeRuntime | None = None,
) -> dict[str, Any]:
    own_runtime = runtime is None
    active_runtime = runtime or TypeSafeRuntime(settings=settings)
    try:
        return active_runtime.execute_sync(
            state=state,
            questions=questions,
            model=model,
            api_key=api_key,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
    finally:
        if own_runtime:
            active_runtime.close()


def _project_arguments(arguments: Any, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    if arguments is None:
        if type(kwargs) is not dict:
            raise ClientError("invalid_input")
        projected = dict(kwargs)
    else:
        if type(arguments) is not dict:
            raise ClientError("invalid_input")
        projected = dict(arguments)
        if kwargs:
            if type(kwargs) is not dict or set(projected) & set(kwargs):
                raise ClientError("invalid_input")
            projected.update(kwargs)
    if set(projected) - {"state", "questions", "model"}:
        raise ClientError("invalid_input")
    return projected


def system_one(arguments: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Run one bounded mixed typed decision batch and return JSON-safe output."""

    runtime = kwargs.pop("_runtime", None)
    settings = kwargs.pop("_settings", {})
    home_identity = kwargs.pop("_home_identity", None)
    require_home_identity = kwargs.pop("_require_home_identity", False)
    try:
        projected = _project_arguments(arguments, kwargs)
        model = projected.get("model", settings.get("model", DEFAULT_MODEL) if isinstance(settings, Mapping) else DEFAULT_MODEL)
        checked = preflight_request(
            state=projected.get("state"),
            questions=projected.get("questions"),
            model=model,
        )
        if not _home_matches(home_identity, required=require_home_identity):
            return {"error": ClientError("unavailable").as_error()}
        key = _read_scoped_secret()
        if not _valid_scoped_secret(key):
            return {"error": ClientError("unavailable").as_error()}
        execute_kwargs: dict[str, Any] = {
            "api_key": key,
            "settings": settings if isinstance(settings, Mapping) else {},
        }
        if isinstance(runtime, TypeSafeRuntime):
            execute_kwargs["runtime"] = runtime
        return _execute_request(checked.state, checked.questions, checked.model, **execute_kwargs)
    except Exception as error:
        return _error_result(error)


def _capture_home_identity() -> str | None:
    try:
        try:
            from hermes_constants import get_hermes_home
        except Exception:
            from agent import get_hermes_home

        value = get_hermes_home()
        if value is None:
            return None
        return value if type(value) is str else str(value)
    except Exception:
        return None


def make_system_one_handler(
    settings: Mapping[str, Any], *, home_identity: str | None = None
) -> Callable[..., str]:
    """Create a registration-lifetime handler without retaining host context."""

    detached_settings = {key: value for key, value in settings.items() if type(key) is str}
    captured_home = home_identity if home_identity is not None else _capture_home_identity()
    runtime = TypeSafeRuntime(
        settings=detached_settings,
        home_identity=captured_home,
        require_home_identity=True,
    )

    def handler(arguments: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
        if set(kwargs) & _INTERNAL_KWARGS:
            payload = _error_result(ClientError("invalid_input"))
        else:
            payload = system_one(
                arguments,
                _runtime=runtime,
                _settings=detached_settings,
                _home_identity=captured_home,
                _require_home_identity=True,
                **kwargs,
            )
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)

    handler._typesafe_runtime = runtime  # type: ignore[attr-defined]
    return handler


__all__ = [
    "API_KEY_ENV",
    "QUESTION_SCHEMA",
    "SYSTEM_ONE_SCHEMA",
    "TOOL_NAME",
    "has_api_key",
    "make_system_one_handler",
    "system_one",
]
