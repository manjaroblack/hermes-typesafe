"""Bounded, exact-JSON preflight for TypeSafe tool requests and responses."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

try:
    from .questions import (
        MAX_CONTAINER_DEPTH as _MAX_CONTAINER_DEPTH,
        MAX_CONTAINER_ITEMS as _MAX_CONTAINER_ITEMS,
        MAX_JSON_NODES as _MAX_JSON_NODES,
        MAX_MODEL_BYTES as _MAX_MODEL_BYTES,
        MAX_OPTION_NAME_BYTES as _MAX_OPTION_NAME_BYTES,
        MAX_OPTIONS as _MAX_OPTIONS,
        MAX_QUESTIONS as _MAX_QUESTIONS,
        MAX_QUESTION_NAME_BYTES as _MAX_QUESTION_NAME_BYTES,
        MAX_REQUEST_BYTES as _MAX_REQUEST_BYTES,
        MAX_RESPONSE_BYTES as _MAX_RESPONSE_BYTES,
        MAX_SCORE_LEVELS as _MAX_SCORE_LEVELS,
        MAX_STATE_BYTES as _MAX_STATE_BYTES,
        MAX_STRING_BYTES as _MAX_STRING_BYTES,
    )
except ImportError:  # pragma: no cover - flat plugin import
    from questions import (
        MAX_CONTAINER_DEPTH as _MAX_CONTAINER_DEPTH,
        MAX_CONTAINER_ITEMS as _MAX_CONTAINER_ITEMS,
        MAX_JSON_NODES as _MAX_JSON_NODES,
        MAX_MODEL_BYTES as _MAX_MODEL_BYTES,
        MAX_OPTION_NAME_BYTES as _MAX_OPTION_NAME_BYTES,
        MAX_OPTIONS as _MAX_OPTIONS,
        MAX_QUESTIONS as _MAX_QUESTIONS,
        MAX_QUESTION_NAME_BYTES as _MAX_QUESTION_NAME_BYTES,
        MAX_REQUEST_BYTES as _MAX_REQUEST_BYTES,
        MAX_RESPONSE_BYTES as _MAX_RESPONSE_BYTES,
        MAX_SCORE_LEVELS as _MAX_SCORE_LEVELS,
        MAX_STATE_BYTES as _MAX_STATE_BYTES,
        MAX_STRING_BYTES as _MAX_STRING_BYTES,
    )

MAX_STATE_BYTES = _MAX_STATE_BYTES
MAX_REQUEST_BYTES = _MAX_REQUEST_BYTES
MAX_RESPONSE_BYTES = _MAX_RESPONSE_BYTES
MAX_CONTAINER_DEPTH = _MAX_CONTAINER_DEPTH
MAX_JSON_NODES = _MAX_JSON_NODES
MAX_CONTAINER_ITEMS = _MAX_CONTAINER_ITEMS
MAX_QUESTIONS = _MAX_QUESTIONS
MAX_OPTIONS = _MAX_OPTIONS
MAX_SCORE_LEVELS = _MAX_SCORE_LEVELS
MAX_STRING_BYTES = _MAX_STRING_BYTES
MAX_MODEL_BYTES = _MAX_MODEL_BYTES
MAX_QUESTION_NAME_BYTES = _MAX_QUESTION_NAME_BYTES
MAX_OPTION_NAME_BYTES = _MAX_OPTION_NAME_BYTES
MAX_INT = 9_007_199_254_740_991
MIN_INT = -MAX_INT

_SAFE_NAME = re.compile(r"^[^\x00-\x1f\x7f]+$")
_JSON_SCALARS = (str, int, float, bool, type(None))


def _safe_name(value: str) -> bool:
    return _SAFE_NAME.fullmatch(value) is not None


class LimitsError(ValueError):
    """Stable preflight failure that never contains caller data."""

    def __init__(self, code: str, message: str) -> None:
        if code not in {"invalid_input", "payload_too_large", "invalid_response", "response_too_large"}:
            raise ValueError("unknown limits error code")
        self.code = code
        self.message = message
        super().__init__(message)

    def as_error(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ValidatedRequest:
    """Detached primitive request data ready for a bounded operation."""

    state: str | dict[str, Any] | list[Any]
    questions: dict[str, dict[str, Any]]
    model: str
    canonical_bytes: bytes
    state_bytes: bytes

    @property
    def request_bytes(self) -> bytes:
        return self.canonical_bytes


@dataclass
class _Walk:
    nodes: int = 0


def _fail(code: str, message: str) -> LimitsError:
    return LimitsError(code, message)


def _utf8_size(value: str, *, cap: int, code: str = "invalid_input", field: str = "string") -> int:
    if type(value) is not str:
        raise _fail("invalid_input", f"{field} must be a JSON string.")
    if len(value) > cap:
        raise _fail("payload_too_large", f"{field} exceeds its size limit.")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as error:
        del error
        raise _fail(code, f"{field} contains invalid Unicode.") from None
    if size > cap:
        raise _fail("payload_too_large", f"{field} exceeds its size limit.")
    if field.endswith("name") and not _safe_name(value):
        raise _fail("invalid_input", f"{field} contains a control character.")
    return size


def _check_string(value: str, *, cap: int = MAX_STRING_BYTES, field: str = "string") -> None:
    _utf8_size(value, cap=cap, field=field)


def _check_scalar(value: Any) -> None:
    kind = type(value)
    if kind is str:
        _check_string(value)
    elif kind is int:
        if value < MIN_INT or value > MAX_INT:
            raise _fail("payload_too_large", "integer exceeds its safe JSON range.")
    elif kind is float:
        if not math.isfinite(value):
            raise _fail("invalid_input", "JSON numbers must be finite.")
    elif kind is bool or value is None:
        return
    else:
        raise _fail("invalid_input", "value must use exact built-in JSON types.")


def _walk_json(
    value: Any,
    *,
    depth: int,
    walk: _Walk,
    active: set[int],
    max_depth: int = MAX_CONTAINER_DEPTH,
    max_nodes: int = MAX_JSON_NODES,
    max_items: int = MAX_CONTAINER_ITEMS,
) -> None:
    kind = type(value)
    walk.nodes += 1
    if walk.nodes > max_nodes:
        raise _fail("payload_too_large", "JSON value count exceeds its limit.")
    if kind in _JSON_SCALARS:
        _check_scalar(value)
        return
    if kind not in (dict, list):
        raise _fail("invalid_input", "value must use exact built-in JSON types.")
    if depth > max_depth:
        raise _fail("payload_too_large", "JSON nesting exceeds its limit.")
    if len(value) > max_items:
        raise _fail("payload_too_large", "JSON container exceeds its item limit.")
    identity = id(value)
    if identity in active:
        raise _fail("invalid_input", "cyclic JSON values are not supported.")
    active.add(identity)
    try:
        if kind is list:
            for item in value:
                _walk_json(
                    item,
                    depth=depth + 1,
                    walk=walk,
                    active=active,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    max_items=max_items,
                )
        else:
            for key, item in value.items():
                if type(key) is not str:
                    raise _fail("invalid_input", "JSON object keys must be strings.")
                walk.nodes += 1
                if walk.nodes > max_nodes:
                    raise _fail("payload_too_large", "JSON value count exceeds its limit.")
                _check_string(key, field="object key")
                _walk_json(
                    item,
                    depth=depth + 1,
                    walk=walk,
                    active=active,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    max_items=max_items,
                )
    finally:
        active.remove(identity)


def _clone_json(value: Any) -> Any:
    """Copy already-validated exact JSON primitives without invoking user code."""

    kind = type(value)
    if kind is dict:
        return {key: _clone_json(item) for key, item in value.items()}
    if kind is list:
        return [_clone_json(item) for item in value]
    return value


def _canonical(value: Any, *, cap: int, code: str) -> bytes:
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded = bytearray()
        for chunk in encoder.iterencode(value):
            encoded_chunk = chunk.encode("ascii")
            if len(encoded) + len(encoded_chunk) > cap:
                raise _fail(code, "encoded JSON exceeds its size limit.")
            encoded.extend(encoded_chunk)
    except LimitsError:
        raise
    except (TypeError, ValueError, UnicodeError) as error:
        del error
        raise _fail("invalid_input" if code == "invalid_response" else code, "value cannot be encoded as bounded JSON.") from None
    return bytes(encoded)


def _validate_and_encode(value: Any, *, cap: int, code: str, root_kind: str | None = None) -> bytes:
    if root_kind == "state" and type(value) not in (str, dict, list):
        raise _fail("invalid_input", "state must be a string, object, or array.")
    _walk_json(value, depth=0, walk=_Walk(), active=set())
    return _canonical(value, cap=cap, code=code)


def preflight_state(state: Any) -> str | dict[str, Any] | list[Any]:
    """Validate a tool state before serialization, SDK construction, or admission."""

    _validate_and_encode(state, cap=MAX_STATE_BYTES, code="payload_too_large", root_kind="state")
    return _clone_json(state)


def _content(value: Any, *, field: str, allow_none: bool = False) -> None:
    if allow_none and value is None:
        return
    if type(value) not in (str, dict, list):
        raise _fail("invalid_input", f"{field} must be text, an object, or an array.")
    _walk_json(value, depth=0, walk=_Walk(), active=set())


def _question_name(value: Any, *, option: bool = False) -> str:
    if type(value) is not str or not value:
        raise _fail("invalid_input", "question names must be non-empty strings.")
    cap = MAX_OPTION_NAME_BYTES if option else MAX_QUESTION_NAME_BYTES
    _utf8_size(value, cap=cap, field="option name" if option else "question name")
    if not _safe_name(value):
        raise _fail("invalid_input", "question names must not contain control characters.")
    return value


def _questions(value: Any) -> dict[str, dict[str, Any]]:
    if type(value) is not dict or not value:
        raise _fail("invalid_input", "questions must be a non-empty object.")
    if len(value) > MAX_QUESTIONS:
        raise _fail("payload_too_large", "question count exceeds its limit.")
    output: dict[str, dict[str, Any]] = {}
    for raw_name, raw_question in value.items():
        name = _question_name(raw_name)
        if type(raw_question) is not dict:
            raise _fail("invalid_input", "each question must be an object.")
        allowed = {"type", "instructions", "criteria"}
        if set(raw_question) - allowed:
            raise _fail("invalid_input", "question contains an unsupported field.")
        kind = raw_question.get("type")
        if type(kind) is not str or kind not in {"noul", "choice", "score"}:
            raise _fail("invalid_input", "question type is unsupported.")
        if "instructions" not in raw_question:
            raise _fail("invalid_input", "question instructions are required.")
        _content(raw_question["instructions"], field="instructions")
        if kind == "noul":
            criteria = raw_question.get("criteria")
            if criteria is not None:
                if type(criteria) is not dict or set(criteria) - {"true", "false"}:
                    raise _fail("invalid_input", "noul criteria must contain only true or false.")
                for criterion in criteria.values():
                    _content(criterion, field="noul criterion", allow_none=True)
        elif kind == "choice":
            criteria = raw_question.get("criteria")
            if type(criteria) is not dict or not criteria:
                raise _fail("invalid_input", "choice criteria must be a non-empty object.")
            if len(criteria) > MAX_OPTIONS:
                raise _fail("payload_too_large", "choice option count exceeds its limit.")
            for option, description in criteria.items():
                _question_name(option, option=True)
                _content(description, field="choice criterion", allow_none=True)
        else:
            criteria = raw_question.get("criteria")
            if type(criteria) is not list or len(criteria) < 2:
                raise _fail("invalid_input", "score criteria must contain at least two levels.")
            if len(criteria) > MAX_SCORE_LEVELS:
                raise _fail("payload_too_large", "score level count exceeds its limit.")
            for description in criteria:
                _content(description, field="score criterion")
        output[name] = _clone_json(raw_question)
    return output


def preflight_request(*, state: Any, questions: Any, model: Any) -> ValidatedRequest:
    """Validate every request field and return detached, bounded wire data."""

    state_bytes = _validate_and_encode(state, cap=MAX_STATE_BYTES, code="payload_too_large", root_kind="state")
    checked_state = _clone_json(state)
    checked_questions = _questions(questions)
    if type(model) is not str or not model.strip():
        raise _fail("invalid_input", "model must be a non-empty string.")
    _utf8_size(model, cap=MAX_MODEL_BYTES, field="model")
    if not _safe_name(model):
        raise _fail("invalid_input", "model must not contain control characters.")
    envelope = {"state": checked_state, "questions": checked_questions, "model": model}
    _walk_json(envelope, depth=0, walk=_Walk(), active=set())
    canonical = _canonical(envelope, cap=MAX_REQUEST_BYTES, code="payload_too_large")
    return ValidatedRequest(
        state=checked_state,
        questions=checked_questions,
        model=model,
        canonical_bytes=canonical,
        state_bytes=state_bytes,
    )


def bound_response_bytes(raw: bytes | bytearray | memoryview) -> bytes:
    """Reject an oversized raw response before JSON decoding."""

    if type(raw) not in (bytes, bytearray, memoryview):
        raise _fail("invalid_response", "response body is not bytes.")
    data = bytes(raw)
    if len(data) > MAX_RESPONSE_BYTES:
        raise _fail("response_too_large", "response body exceeds its size limit.")
    return data


def validate_response_payload(payload: Any) -> Any:
    """Apply the same bounded exact-JSON checks to a decoded response envelope."""

    if type(payload) is not dict:
        raise _fail("invalid_response", "response body must be an object.")
    _walk_json(payload, depth=0, walk=_Walk(), active=set())
    _canonical(payload, cap=MAX_RESPONSE_BYTES, code="response_too_large")
    return payload
