"""RED contract for the bounded lazy SDK client."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from types import SimpleNamespace

import pytest

try:
    import client
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe import client


class FakeRetryPolicy:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[object, object, dict[str, object]]] = []
        self.closed = False
        type(self).instances.append(self)

    async def system_one(self, state: object, questions: object, **kwargs: object) -> object:
        self.calls.append((state, questions, kwargs))
        return {
            "model": kwargs["model"],
            "answers": {
                "is_safe": {"type": "noul", "noul": 0.75},
                "mood": {
                    "type": "choice",
                    "choice": "calm",
                    "probabilities": {"calm": 0.75, "angry": 0.25},
                },
                "difficulty": {
                    "type": "score",
                    "score": 0.75,
                    "legend": {"0": "easy", "1": {"name": "hard"}},
                    "probabilities": {"0": 0.25, "1": 0.75},
                },
            },
            "usage": {},
        }

    async def aclose(self) -> None:
        self.closed = True


def fake_sdk() -> SimpleNamespace:
    return SimpleNamespace(AsyncTypeSafeClient=FakeAsyncClient, RetryPolicy=FakeRetryPolicy)


def mixed_questions() -> dict[str, object]:
    return {
        "is_safe": {"type": "noul", "instructions": "is this safe?"},
        "mood": {
            "type": "choice",
            "instructions": {"question": "mood"},
            "criteria": {"calm": None, "angry": {"hint": "upset"}},
        },
        "difficulty": {
            "type": "score",
            "instructions": ["difficulty"],
            "criteria": ["easy", {"name": "hard"}],
        },
    }


def test_client_uses_pinned_endpoint_model_and_zero_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_load_sdk", fake_sdk)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://ambient.invalid")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "ambient-model")
    FakeAsyncClient.instances.clear()

    async def run() -> tuple[dict[str, object], FakeAsyncClient]:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key", model="jev-1.13.0")
        result = await wrapper.system_one("text", mixed_questions())
        await wrapper.aclose()
        return result, FakeAsyncClient.instances[0]

    result, sdk_client = asyncio.run(run())

    sdk_client = FakeAsyncClient.instances[0]
    assert sdk_client.kwargs["api_key"] == "scoped-key"
    assert sdk_client.kwargs["model"] == "jev-1.13.0"
    assert sdk_client.kwargs["base_url"] == "https://api.typesafe.ai"
    assert sdk_client.kwargs["retry"].kwargs["max_retries"] == 0
    assert isinstance(sdk_client.kwargs["transport"], client._CappedAsyncTransport)
    assert result["model"] == "jev-1.13.0"
    assert result["usage"] == {"input_tokens": None, "output_tokens": None}
    assert result["answers"]["mood"]["confidence"] is None
    assert result["answers"]["difficulty"]["legend"] == {0: "easy", 1: {"name": "hard"}}
    assert sdk_client.closed is True

    state, questions, call_kwargs = sdk_client.calls[0]
    assert state == "text"
    assert questions == mixed_questions()
    assert call_kwargs == {"model": "jev-1.13.0"}


def test_client_rejects_invalid_input_before_sdk_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    class ForbiddenClient:
        def __init__(self, **_: object) -> None:
            raise AssertionError("SDK client was constructed for invalid input")

    monkeypatch.setattr(client, "_load_sdk", lambda: SimpleNamespace(AsyncTypeSafeClient=ForbiddenClient, RetryPolicy=FakeRetryPolicy))
    async def run() -> None:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one(True, mixed_questions())
        assert error.value.code == "invalid_input"

    asyncio.run(run())


def test_client_sanitizes_sdk_failures_without_body_or_header(monkeypatch: pytest.MonkeyPatch) -> None:
    class SDKError(Exception):
        status = 401
        body = {"secret": "request-body-sentinel"}
        headers = {"authorization": "header-sentinel"}

    class FailingClient(FakeAsyncClient):
        async def system_one(self, *_: object, **__: object) -> object:
            raise SDKError("raw-body-sentinel")

    monkeypatch.setattr(client, "_load_sdk", lambda: SimpleNamespace(AsyncTypeSafeClient=FailingClient, RetryPolicy=FakeRetryPolicy))
    async def run() -> client.ClientError:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        try:
            await wrapper.system_one("text", mixed_questions())
        except client.ClientError as error:
            return error
        raise AssertionError("expected sanitized client error")

    error = asyncio.run(run())
    assert error.code == "auth_failed"
    assert str(error) == "TypeSafe authentication failed."
    assert all(token not in error.to_json() for token in ("raw-body-sentinel", "request-body-sentinel", "header-sentinel"))


def test_client_can_be_called_from_an_active_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_load_sdk", fake_sdk)

    async def run() -> dict[str, object]:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        try:
            return await wrapper.system_one("text", mixed_questions())
        finally:
            await wrapper.aclose()

    result = asyncio.run(run())
    assert result["answers"]["is_safe"]["noul"] == 0.75


def test_transport_rejects_request_and_response_cap_plus_one_before_decode() -> None:
    class Inner:
        def __init__(self) -> None:
            self.called = False

        async def handle_async_request(self, request: object) -> object:
            self.called = True
            return Response()

    class Response:
        async def aread(self) -> bytes:
            return b"x" * (client.MAX_RESPONSE_BYTES + 1)

        async def aclose(self) -> None:
            return None

    async def run() -> None:
        inner = Inner()
        capped = client._CappedAsyncTransport(inner)
        with pytest.raises(client._RequestTooLarge):
            await capped.handle_async_request(type("Request", (), {"content": b"x" * (client.MAX_REQUEST_BYTES + 1)})())
        assert inner.called is False
        with pytest.raises(client._ResponseTooLarge):
            await capped.handle_async_request(type("Request", (), {"content": b""})())

    asyncio.run(run())


def test_client_rejects_response_model_with_control_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadModelClient(FakeAsyncClient):
        async def system_one(self, state: object, questions: object, **kwargs: object) -> object:
            payload = await super().system_one(state, questions, **kwargs)
            assert isinstance(payload, dict)
            payload["model"] = "jev-1.13.0\n"
            return payload

    monkeypatch.setattr(client, "_load_sdk", lambda: SimpleNamespace(AsyncTypeSafeClient=BadModelClient, RetryPolicy=FakeRetryPolicy))

    async def run() -> None:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one("text", mixed_questions())
        assert error.value.code == "invalid_response"

    asyncio.run(run())


def test_client_rejects_response_model_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    class WrongModelClient(FakeAsyncClient):
        async def system_one(self, state: object, questions: object, **kwargs: object) -> object:
            payload = await super().system_one(state, questions, **kwargs)
            assert isinstance(payload, dict)
            payload["model"] = "ambient-model"
            return payload

    monkeypatch.setattr(client, "_load_sdk", lambda: SimpleNamespace(AsyncTypeSafeClient=WrongModelClient, RetryPolicy=FakeRetryPolicy))

    async def run() -> None:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key", model="jev-1.13.0")
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one("text", mixed_questions())
        assert error.value.code == "invalid_response"

    asyncio.run(run())


def test_client_rejects_ambiguous_score_legend_level(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadScoreClient(FakeAsyncClient):
        async def system_one(self, state: object, questions: object, **kwargs: object) -> object:
            payload = await super().system_one(state, questions, **kwargs)
            assert isinstance(payload, dict)
            answers = payload["answers"]
            assert isinstance(answers, dict)
            score_answer = answers["difficulty"]
            assert isinstance(score_answer, dict)
            score_answer["legend"] = {"0": "easy", "01": "hard"}
            return payload

    monkeypatch.setattr(client, "_load_sdk", lambda: SimpleNamespace(AsyncTypeSafeClient=BadScoreClient, RetryPolicy=FakeRetryPolicy))

    async def run() -> None:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one("text", mixed_questions())
        assert error.value.code == "invalid_response"

    asyncio.run(run())


def test_client_bounds_direct_timeout_and_rejects_oversized_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class ForbiddenClient:
        def __init__(self, **_: object) -> None:
            raise AssertionError("SDK client was constructed for an oversized key")

    monkeypatch.setattr(client, "_load_sdk", lambda: SimpleNamespace(AsyncTypeSafeClient=ForbiddenClient, RetryPolicy=FakeRetryPolicy))
    wrapper = client.AsyncTypeSafeClient(api_key="k" * 4_097, timeout=999.0)
    assert wrapper.timeout == client.DEFAULT_HTTP_TIMEOUT

    async def run() -> None:
        with pytest.raises(client.ClientError) as error:
            await wrapper.system_one("text", mixed_questions())
        assert error.value.code == "unavailable"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (403, "permission_denied"),
        (422, "invalid_request"),
        (429, "rate_limited"),
        (529, "provider_unavailable"),
    ],
)
def test_client_maps_provider_statuses_to_stable_codes(
    monkeypatch: pytest.MonkeyPatch, status: int, expected_code: str
) -> None:
    class StatusError(Exception):
        def __init__(self) -> None:
            self.status = status
            self.body = {"sentinel": "provider-body"}
            self.headers = {"x-secret": "provider-header"}

    class FailingClient(FakeAsyncClient):
        async def system_one(self, *_: object, **__: object) -> object:
            raise StatusError

    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: SimpleNamespace(AsyncTypeSafeClient=FailingClient, RetryPolicy=FakeRetryPolicy),
    )

    async def run() -> client.ClientError:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        try:
            await wrapper.system_one("text", mixed_questions())
        except client.ClientError as error:
            return error
        raise AssertionError("expected sanitized provider error")

    error = asyncio.run(run())
    assert error.code == expected_code
    assert "provider-body" not in error.to_json()
    assert "provider-header" not in error.to_json()


def test_client_maps_connection_and_malformed_response_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class ConnectionClient(FakeAsyncClient):
        async def system_one(self, *_: object, **__: object) -> object:
            raise ConnectionError("connection-body-sentinel")

    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: SimpleNamespace(AsyncTypeSafeClient=ConnectionClient, RetryPolicy=FakeRetryPolicy),
    )

    async def run_connection() -> client.ClientError:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        try:
            await wrapper.system_one("text", mixed_questions())
        except client.ClientError as error:
            return error
        raise AssertionError("expected connection error")

    connection = asyncio.run(run_connection())
    assert connection.code == "connection_error"
    assert "connection-body-sentinel" not in connection.to_json()

    class ResponseValidationError(Exception):
        pass

    class MalformedClient(FakeAsyncClient):
        async def system_one(self, *_: object, **__: object) -> object:
            raise ResponseValidationError("malformed-response-sentinel")

    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: SimpleNamespace(AsyncTypeSafeClient=MalformedClient, RetryPolicy=FakeRetryPolicy),
    )

    async def run_malformed() -> client.ClientError:
        wrapper = client.AsyncTypeSafeClient(api_key="scoped-key")
        try:
            await wrapper.system_one("text", mixed_questions())
        except client.ClientError as error:
            return error
        raise AssertionError("expected malformed response error")

    malformed = asyncio.run(run_malformed())
    assert malformed.code == "invalid_response"
    assert "malformed-response-sentinel" not in malformed.to_json()


def test_sdk_logging_suppression_restores_only_after_concurrent_contexts_exit() -> None:
    sdk_logger = logging.getLogger("typesafe_sdk")
    child_logger = logging.getLogger("typesafe_sdk.test.concurrent")
    sdk_state = (sdk_logger.disabled, sdk_logger.level, sdk_logger.propagate, list(sdk_logger.handlers))
    child_state = (child_logger.disabled, child_logger.level, child_logger.propagate, list(child_logger.handlers))
    sdk_handler = logging.StreamHandler(io.StringIO())
    child_handler = logging.StreamHandler(io.StringIO())
    sdk_logger.disabled = False
    sdk_logger.level = logging.DEBUG
    sdk_logger.propagate = True
    sdk_logger.handlers = [sdk_handler]
    child_logger.disabled = False
    child_logger.level = logging.DEBUG
    child_logger.propagate = True
    child_logger.handlers = [child_handler]

    barrier = threading.Barrier(2)
    first_exited = threading.Event()
    second_active = threading.Event()
    errors: list[BaseException] = []

    def worker(first: bool) -> None:
        try:
            with client._suppress_sdk_logging():
                assert sdk_logger.disabled is True
                assert child_logger.disabled is True
                barrier.wait(timeout=1.0)
                if first:
                    assert second_active.wait(timeout=1.0)
                else:
                    second_active.set()
                    assert first_exited.wait(timeout=1.0)
                    assert sdk_logger.disabled is True
                    assert child_logger.disabled is True
            if first:
                first_exited.set()
        except BaseException as error:  # pragma: no cover - surfaced below
            errors.append(error)

    first = threading.Thread(target=worker, args=(True,))
    second = threading.Thread(target=worker, args=(False,))
    first.start()
    second.start()
    first.join(timeout=2.0)
    second.join(timeout=2.0)
    try:
        assert not errors
        assert not first.is_alive()
        assert not second.is_alive()
        assert sdk_logger.disabled is False
        assert child_logger.disabled is False
        assert sdk_logger.handlers == [sdk_handler]
        assert child_logger.handlers == [child_handler]
    finally:
        sdk_logger.disabled, sdk_logger.level, sdk_logger.propagate, handlers = sdk_state
        sdk_logger.handlers = handlers
        child_logger.disabled, child_logger.level, child_logger.propagate, handlers = child_state
        child_logger.handlers = handlers


def test_actual_sdk_debug_logging_is_suppressed_and_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import contextlib

    import httpx2
    import typesafe_sdk
    from typesafe_sdk._core import logging as sdk_logging

    marker = "typesafe-sdk-debug-body-sentinel"
    monkeypatch.setenv("TYPESAFE_LOG_LEVEL", "debug")
    sdk_logging.setup_logging()
    stream = io.StringIO()
    sdk_logger = logging.getLogger("typesafe_sdk")
    child_logger = logging.getLogger("typesafe_sdk.transport.sentinel")
    sdk_handler = logging.StreamHandler(stream)
    child_handler = logging.StreamHandler(stream)
    sdk_logger.addHandler(sdk_handler)
    child_logger.addHandler(child_handler)

    class LoggingTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: object) -> httpx2.Response:
            del request
            sdk_logger.debug("%s parent", marker)
            child_logger.debug("%s child", marker)
            raise RuntimeError(marker)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(client, "_load_sdk", lambda: typesafe_sdk)
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            async def run() -> client.ClientError:
                wrapper = client.AsyncTypeSafeClient(
                    api_key="scoped-key", transport=LoggingTransport()  # type: ignore[arg-type]
                )
                try:
                    await wrapper.system_one("text", mixed_questions())
                except client.ClientError as error:
                    return error
                raise AssertionError("expected sanitized SDK failure")

            error = asyncio.run(run())
    finally:
        sdk_logger.removeHandler(sdk_handler)
        child_logger.removeHandler(child_handler)

    captured_stdio = capsys.readouterr()
    captured = "".join((stream.getvalue(), stdout.getvalue(), stderr.getvalue(), captured_stdio.out, captured_stdio.err))
    assert error.code == "provider_unavailable"
    assert marker not in captured
    assert marker not in error.to_json()
