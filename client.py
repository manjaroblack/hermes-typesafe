"""Pinned, sanitized asynchronous TypeSafe SDK boundary."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import json
import logging
import math
import threading
from collections.abc import Mapping
from types import ModuleType
from typing import Any, cast

if __package__:
    from .limits import MAX_MODEL_BYTES, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, LimitsError, ValidatedRequest, preflight_request, validate_response_payload
    from .questions import DEFAULT_MODEL
else:  # pragma: no cover - flat plugin smoke import
    from limits import MAX_MODEL_BYTES, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, LimitsError, ValidatedRequest, preflight_request, validate_response_payload
    from questions import DEFAULT_MODEL

API_BASE_URL = "https://api.typesafe.ai"
DEFAULT_HTTP_TIMEOUT = 119.0

_SDK_LOGGING_LOCK = threading.RLock()
_SDK_LOGGING_DEPTH = 0
_SDK_LOGGING_STATES: dict[str, tuple[bool, int, bool, list[logging.Handler]]] = {}


def _valid_api_key(value: Any) -> bool:
    if type(value) is not str or not value.strip() or len(value) > 4_096:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


class _RequestTooLarge(Exception):
    pass


class _ResponseTooLarge(Exception):
    pass


class _UnavailableTransport:
    async def handle_async_request(self, request: Any) -> Any:
        del request
        raise ClientError("sdk_unavailable")

    async def aclose(self) -> None:
        return None


class _CappedAsyncTransport:
    """Bound request and response bytes at the last SDK transport seam."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def handle_async_request(self, request: Any) -> Any:
        try:
            content = request.content
        except Exception:
            content = b""
        if type(content) is bytes and len(content) > MAX_REQUEST_BYTES:
            raise _RequestTooLarge
        response = await self._inner.handle_async_request(request)
        try:
            body = await response.aread()
        except Exception:
            body = getattr(response, "content", b"")
        if type(body) is bytes and len(body) > MAX_RESPONSE_BYTES:
            try:
                await response.aclose()
            except Exception:
                pass
            raise _ResponseTooLarge
        return response

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


class ClientError(Exception):
    """Stable error returned to the native tool without provider details."""

    MESSAGES = {
        "unavailable": "TypeSafe runtime is unavailable.",
        "invalid_input": "TypeSafe input is invalid.",
        "payload_too_large": "TypeSafe input is too large.",
        "auth_failed": "TypeSafe authentication failed.",
        "permission_denied": "TypeSafe permission denied.",
        "invalid_request": "TypeSafe request was rejected.",
        "rate_limited": "TypeSafe rate limit reached.",
        "provider_unavailable": "TypeSafe provider unavailable.",
        "connection_error": "TypeSafe connection failed.",
        "timeout": "TypeSafe request timed out.",
        "invalid_response": "TypeSafe response was invalid.",
        "response_too_large": "TypeSafe response is too large.",
        "sdk_unavailable": "TypeSafe SDK is unavailable.",
    }

    def __init__(self, code: str, message: str | None = None) -> None:
        if code not in self.MESSAGES:
            code = "provider_unavailable"
        self.code = code
        self.message = message if message is not None else self.MESSAGES[code]
        super().__init__(self.message)

    def as_error(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}

    def to_json(self) -> str:
        return json.dumps({"error": self.as_error()}, sort_keys=True)


def _load_sdk() -> ModuleType:
    """Load the SDK only after bounded input validation and log suppression."""

    try:
        return importlib.import_module("typesafe_sdk")
    except Exception as error:
        del error
        raise ClientError("sdk_unavailable") from None


def _capped_transport(transport: Any) -> _CappedAsyncTransport:
    if transport is None:
        try:
            httpx2 = importlib.import_module("httpx2")
            transport = httpx2.AsyncHTTPTransport()
        except Exception as error:
            del error
            transport = _UnavailableTransport()
    return _CappedAsyncTransport(transport)


@contextlib.contextmanager
def _suppress_sdk_logging() -> Any:
    """Suppress SDK body-bearing records without touching root logger policy."""

    global _SDK_LOGGING_DEPTH
    with _SDK_LOGGING_LOCK:
        with logging._lock:  # type: ignore[attr-defined]
            sdk_logger = logging.getLogger("typesafe_sdk")
            candidates = [("typesafe_sdk", sdk_logger)]
            candidates.extend(
                (name, candidate)
                for name, candidate in logging.Logger.manager.loggerDict.items()
                if name.startswith("typesafe_sdk") and isinstance(candidate, logging.Logger)
            )
            for name, candidate in candidates:
                if name not in _SDK_LOGGING_STATES:
                    _SDK_LOGGING_STATES[name] = (
                        candidate.disabled,
                        candidate.level,
                        candidate.propagate,
                        list(candidate.handlers),
                    )
                candidate.disabled = True
                candidate.handlers = [logging.NullHandler()] if name == "typesafe_sdk" else []
                candidate.propagate = False
            _SDK_LOGGING_DEPTH += 1
    try:
        yield
    finally:
        with _SDK_LOGGING_LOCK:
            _SDK_LOGGING_DEPTH -= 1
            if _SDK_LOGGING_DEPTH == 0:
                with logging._lock:  # type: ignore[attr-defined]
                    for name, state in _SDK_LOGGING_STATES.items():
                        candidate = logging.getLogger(name)
                        candidate.disabled, candidate.level, candidate.propagate, handlers = state
                        candidate.handlers = handlers
                    _SDK_LOGGING_STATES.clear()


def _error_from_exception(error: BaseException) -> ClientError:
    """Map SDK failures by status/type while dropping body, headers, and repr."""

    status = getattr(error, "status", None)
    if isinstance(error, _RequestTooLarge):
        return ClientError("payload_too_large")
    if isinstance(error, _ResponseTooLarge):
        return ClientError("response_too_large")
    if type(status) is int:
        if status == 401:
            return ClientError("auth_failed")
        if status == 403:
            return ClientError("permission_denied")
        if status in {400, 422}:
            return ClientError("invalid_request")
        if status == 429:
            return ClientError("rate_limited")
        if status == 529 or status >= 500:
            return ClientError("provider_unavailable")
    name = type(error).__name__.lower()
    if "responsevalidation" in name or "validation" in name:
        return ClientError("invalid_response")
    if "timeout" in name:
        return ClientError("timeout")
    if "connection" in name or isinstance(error, ConnectionError):
        return ClientError("connection_error")
    if isinstance(error, (LimitsError, TypeError, ValueError)):
        return ClientError("invalid_input")
    return ClientError("provider_unavailable")


def _dump_response(value: Any) -> Any:
    if type(value) is dict:
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except Exception as error:
            del error
            raise ClientError("invalid_response") from None
        return dumped
    if isinstance(value, Mapping):
        return dict(value)
    raise ClientError("invalid_response")


def _finite_probability(value: Any) -> float | None:
    if type(value) is not float and type(value) is not int:
        return None
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _token_count(usage: Any, name: str) -> int | None:
    value = usage.get(name) if type(usage) is dict else None
    return value if type(value) is int and value >= 0 else None


def _valid_response_model(value: Any) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        if len(value.encode("utf-8", errors="strict")) > MAX_MODEL_BYTES:
            return False
    except UnicodeEncodeError:
        return False
    return all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)


def _int_key(value: Any) -> int | str:
    if type(value) is int:
        return value
    if type(value) is str and (value == "0" or (value.isdigit() and not value.startswith("0"))):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _validated_optional_choice_questions(
    questions: Mapping[str, Any], optional_choice_questions: Any
) -> tuple[str, ...]:
    if type(optional_choice_questions) is not tuple or len(optional_choice_questions) > 4:
        raise ClientError("invalid_input")
    seen: set[str] = set()
    for name in optional_choice_questions:
        if type(name) is not str or not name or name in seen:
            raise ClientError("invalid_input")
        try:
            if len(name.encode("utf-8", errors="strict")) > 64:
                raise ClientError("invalid_input")
        except UnicodeEncodeError:
            raise ClientError("invalid_input") from None
        question = questions.get(name)
        if type(question) is not dict or question.get("type") != "choice":
            raise ClientError("invalid_input")
        seen.add(name)
    return optional_choice_questions


def _normalize_choice_answer(answer: Any, question: Mapping[str, Any]) -> dict[str, Any] | None:
    if type(answer) is not dict or answer.get("type") != "choice":
        return None
    choice = answer.get("choice")
    criteria = question.get("criteria")
    if type(choice) is not str or type(criteria) is not dict or choice not in criteria:
        return None
    probabilities = answer.get("probabilities")
    normalized_probabilities: dict[str, float] | None = None
    if probabilities is not None:
        if type(probabilities) is not dict:
            return None
        normalized_probabilities = {}
        for option, probability in probabilities.items():
            if type(option) is not str or option not in criteria:
                return None
            checked_probability = _finite_probability(probability)
            if checked_probability is None:
                return None
            normalized_probabilities[option] = checked_probability
    confidence = answer.get("confidence")
    checked_confidence = None if confidence is None else _finite_probability(confidence)
    if confidence is not None and checked_confidence is None:
        return None
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": normalized_probabilities,
        "confidence": checked_confidence,
    }


def _normalize_response(
    raw: Any,
    checked: ValidatedRequest,
    *,
    optional_choice_questions: tuple[str, ...] = (),
) -> dict[str, Any]:
    optional_names = set(_validated_optional_choice_questions(checked.questions, optional_choice_questions))
    payload = _dump_response(raw)
    try:
        validate_response_payload(payload)
    except LimitsError as error:
        if error.code == "response_too_large":
            raise ClientError("response_too_large") from None
        raise ClientError("invalid_response") from None
    if type(payload) is not dict:
        raise ClientError("invalid_response")
    if set(payload) != {"model", "answers", "usage"}:
        raise ClientError("invalid_response")
    if not _valid_response_model(payload.get("model")) or payload["model"] != checked.model:
        raise ClientError("invalid_response")
    answers = payload.get("answers")
    usage = payload.get("usage")
    if type(answers) is not dict or type(usage) is not dict:
        raise ClientError("invalid_response")
    expected = set(checked.questions)
    answer_names = set(answers)
    if not answer_names <= expected or not (expected - optional_names) <= answer_names:
        raise ClientError("invalid_response")
    if any(name not in expected for name in answers):
        raise ClientError("invalid_response")
    if any(name not in {"input_tokens", "output_tokens"} for name in usage):
        raise ClientError("invalid_response")
    for token_name in ("input_tokens", "output_tokens"):
        token_value = usage.get(token_name)
        if token_value is not None and (type(token_value) is not int or token_value < 0):
            raise ClientError("invalid_response")
    normalized: dict[str, Any] = {"model": payload["model"], "answers": {}, "usage": {}}
    for name, question in checked.questions.items():
        if name not in answers:
            if name in optional_names:
                continue
            raise ClientError("invalid_response")
        answer = answers.get(name)
        if type(answer) is not dict or answer.get("type") != question.get("type"):
            if name in optional_names:
                continue
            raise ClientError("invalid_response")
        kind = question["type"]
        if kind == "noul":
            number = answer.get("noul")
            if type(number) not in (int, float):
                raise ClientError("invalid_response")
            number_value = float(cast(int | float, number))
            if not math.isfinite(number_value) or not 0 <= number_value <= 1:
                raise ClientError("invalid_response")
            normalized["answers"][name] = {"type": "noul", "noul": number_value}
        elif kind == "choice":
            normalized_choice = _normalize_choice_answer(answer, question)
            if normalized_choice is None:
                if name in optional_names:
                    continue
                raise ClientError("invalid_response")
            normalized["answers"][name] = normalized_choice
        else:
            score = answer.get("score")
            criteria = question.get("criteria")
            if type(criteria) is not list or type(score) not in (int, float):
                raise ClientError("invalid_response")
            score_value = float(cast(int | float, score))
            if not math.isfinite(score_value):
                raise ClientError("invalid_response")
            if not 0 <= score_value <= len(criteria) - 1:
                raise ClientError("invalid_response")
            legend = answer.get("legend")
            if type(legend) is not dict:
                raise ClientError("invalid_response")
            normalized_legend: dict[int | str, Any] = {}
            for key, value in legend.items():
                normalized_key = _int_key(key)
                if normalized_key in normalized_legend:
                    raise ClientError("invalid_response")
                normalized_legend[normalized_key] = value
            expected_levels = set(range(len(criteria)))
            if set(normalized_legend) != expected_levels:
                raise ClientError("invalid_response")
            probabilities = answer.get("probabilities")
            normalized_probabilities_score: dict[int | str, float] | None = None
            if probabilities is not None:
                if type(probabilities) is not dict:
                    raise ClientError("invalid_response")
                normalized_probabilities_score = {}
                for level, probability in probabilities.items():
                    normalized_level = _int_key(level)
                    if normalized_level not in expected_levels:
                        raise ClientError("invalid_response")
                    if normalized_level in normalized_probabilities_score:
                        raise ClientError("invalid_response")
                    checked_probability = _finite_probability(probability)
                    if checked_probability is None:
                        raise ClientError("invalid_response")
                    normalized_probabilities_score[normalized_level] = checked_probability
            confidence = answer.get("confidence")
            checked_confidence = None if confidence is None else _finite_probability(confidence)
            if confidence is not None and checked_confidence is None:
                raise ClientError("invalid_response")
            normalized["answers"][name] = {
                "type": "score",
                "score": score_value,
                "legend": normalized_legend,
                "probabilities": normalized_probabilities_score,
                "confidence": checked_confidence,
            }
    normalized["usage"] = {
        "input_tokens": _token_count(usage, "input_tokens"),
        "output_tokens": _token_count(usage, "output_tokens"),
    }
    return normalized


class AsyncTypeSafeClient:
    """Per-operation wrapper around the pinned SDK client."""

    def __init__(self, *, api_key: str | None, model: str = DEFAULT_MODEL, timeout: float = DEFAULT_HTTP_TIMEOUT, transport: Any = None) -> None:
        self.api_key = api_key
        self.model = model
        bounded_timeout = timeout if type(timeout) in (int, float) and math.isfinite(float(timeout)) else DEFAULT_HTTP_TIMEOUT
        self.timeout = max(0.001, min(float(bounded_timeout), DEFAULT_HTTP_TIMEOUT))
        self.transport = transport
        self._active: set[Any] = set()

    async def system_one(
        self,
        state: Any,
        questions: Any,
        *,
        optional_choice_questions: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        try:
            checked = preflight_request(state=state, questions=questions, model=self.model)
        except LimitsError as error:
            code = "payload_too_large" if error.code == "payload_too_large" else "invalid_input"
            raise ClientError(code) from None
        optional_choice_questions = _validated_optional_choice_questions(checked.questions, optional_choice_questions)
        if not _valid_api_key(self.api_key):
            raise ClientError("unavailable")
        sdk_client: Any = None
        try:
            with _suppress_sdk_logging():
                sdk = _load_sdk()
                retry = sdk.RetryPolicy(max_retries=0)
                kwargs: dict[str, Any] = {
                    "api_key": self.api_key,
                    "model": checked.model,
                    "base_url": API_BASE_URL,
                    "retry": retry,
                    "timeout": self.timeout,
                }
                kwargs["transport"] = _capped_transport(self.transport)
                sdk_client = sdk.AsyncTypeSafeClient(**kwargs)
                self._active.add(sdk_client)
                raw = await sdk_client.system_one(checked.state, checked.questions, model=checked.model)
            return _normalize_response(
                raw,
                checked,
                optional_choice_questions=optional_choice_questions,
            )
        except ClientError:
            raise
        except LimitsError as error:
            code = "response_too_large" if error.code == "response_too_large" else "invalid_response"
            raise ClientError(code) from None
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _error_from_exception(error) from None
        finally:
            if sdk_client is not None:
                self._active.discard(sdk_client)
                close = getattr(sdk_client, "aclose", None)
                if callable(close):
                    try:
                        with _suppress_sdk_logging():
                            await close()
                    except Exception:
                        pass

    async def aclose(self) -> None:
        for sdk_client in tuple(self._active):
            close = getattr(sdk_client, "aclose", None)
            if not callable(close):
                continue
            try:
                with _suppress_sdk_logging():
                    await close()
            except Exception:
                pass
        self._active.clear()


__all__ = ["API_BASE_URL", "AsyncTypeSafeClient", "ClientError"]
