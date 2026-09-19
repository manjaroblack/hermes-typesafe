"""RED/GREEN contract for bounded runtime calls and cancellation."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest

import hermes_typesafe_broker.core as broker
try:
    from runtime import TypeSafeRuntime
    import runtime as runtime_module
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe.runtime import TypeSafeRuntime
    from hermes_typesafe import runtime as runtime_module

pytestmark = pytest.mark.skipif(
    sys.version_info[:2] not in {(3, 10), (3, 11), (3, 12)},
    reason="canonical broker supports CPython 3.10-3.12 main interpreters only",
)


QUESTIONS = {"safe": {"type": "noul", "instructions": "safe?"}}


@pytest.fixture(autouse=True)
def clean_broker() -> None:
    broker._reset_for_tests()
    yield
    broker.shutdown(time.monotonic() + 0.5)
    broker._reset_for_tests()


class FakeClient:
    calls: list[dict[str, Any]] = []
    delay = 0.0

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        type(self).calls.append(kwargs)

    async def system_one(self, state: Any, questions: Any) -> dict[str, Any]:
        await asyncio.sleep(self.delay)
        return {
            "model": self.kwargs["model"],
            "answers": {"safe": {"type": "noul", "noul": 1.0}},
            "usage": {"input_tokens": None, "output_tokens": None},
        }


def loader() -> Any:
    return broker


def test_keyless_runtime_does_not_load_broker_or_start_thread() -> None:
    called = False

    def forbidden_loader() -> Any:
        nonlocal called
        called = True
        raise AssertionError("broker loaded without a key")

    runtime = TypeSafeRuntime(broker_loader=forbidden_loader, client_factory=FakeClient)
    with pytest.raises(Exception) as error:
        runtime.execute_sync(state="text", questions=QUESTIONS, model="jev-1.13.0", api_key=" ")
    assert getattr(error.value, "code", None) == "unavailable"
    assert called is False
    assert broker.stats()["thread_count"] == 0


def test_required_empty_home_identity_is_unavailable_without_broker_load(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def forbidden_loader() -> Any:
        nonlocal called
        called = True
        raise AssertionError("broker loaded with an empty home identity")

    monkeypatch.setattr(runtime_module, "_effective_home", lambda: "")
    runtime = TypeSafeRuntime(
        broker_loader=forbidden_loader,
        client_factory=cast(Any, FakeClient),
        home_identity="",
        require_home_identity=True,
    )
    with pytest.raises(Exception) as error:
        runtime.execute_sync(
            state="text",
            questions=QUESTIONS,
            model="jev-1.13.0",
            api_key="scoped-key",
            timeout=0.1,
        )
    assert getattr(error.value, "code", None) == "unavailable"
    assert called is False


def test_oversized_runtime_key_does_not_load_broker() -> None:
    called = False

    def forbidden_loader() -> Any:
        nonlocal called
        called = True
        raise AssertionError("broker loaded with an oversized key")

    runtime = TypeSafeRuntime(broker_loader=forbidden_loader, client_factory=cast(Any, FakeClient))
    with pytest.raises(Exception) as error:
        runtime.execute_sync(
            state="text",
            questions=QUESTIONS,
            model="jev-1.13.0",
            api_key="k" * 4_097,
            timeout=0.1,
        )
    assert getattr(error.value, "code", None) == "unavailable"
    assert called is False


def test_runtime_reports_timeout_when_admission_finishes_after_deadline() -> None:
    def slow_loader() -> Any:
        time.sleep(0.03)
        return broker

    runtime = TypeSafeRuntime(broker_loader=slow_loader, client_factory=cast(Any, FakeClient))
    with pytest.raises(Exception) as error:
        runtime.execute_sync(
            state="text",
            questions=QUESTIONS,
            model="jev-1.13.0",
            api_key="scoped-key",
            timeout=0.005,
        )
    assert getattr(error.value, "code", None) == "timeout"


def test_runtime_rejects_nonfinite_or_unrepresentable_timeout() -> None:
    runtime = TypeSafeRuntime(broker_loader=loader, client_factory=cast(Any, FakeClient))
    for timeout in (float("nan"), float("inf"), 10**1_000):
        with pytest.raises(Exception) as error:
            runtime.execute_sync(
                state="text",
                questions=QUESTIONS,
                model="jev-1.13.0",
                api_key="scoped-key",
                timeout=timeout,
            )
        assert getattr(error.value, "code", None) == "invalid_input"


def test_runtime_status_does_not_advertise_unsupported_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module.sys, "version_info", (3, 13, 0))
    assert runtime_module.runtime_status()["status"] == "runtime_unavailable"


def test_missing_home_value_is_not_coerced_into_a_valid_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    class Constants:
        @staticmethod
        def get_hermes_home() -> None:
            return None

    monkeypatch.setattr(runtime_module.importlib, "import_module", lambda _: Constants)
    assert runtime_module._effective_home() is None


def test_home_lookup_falls_back_to_agent_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class Agent:
        @staticmethod
        def get_hermes_home() -> str:
            return "agent-home"

    def import_module(name: str) -> Any:
        if name == "hermes_constants":
            raise ImportError("fixture omits constants module")
        return Agent

    monkeypatch.setattr(runtime_module.importlib, "import_module", import_module)
    assert runtime_module._effective_home() == "agent-home"


def test_runtime_uses_one_bounded_operation_and_profile_key_is_not_in_result() -> None:
    FakeClient.calls.clear()
    runtime = TypeSafeRuntime(broker_loader=loader, client_factory=FakeClient)
    result = runtime.execute_sync(
        state={"text": "hello"},
        questions=QUESTIONS,
        model="jev-1.13.0",
        api_key="scoped-key",
        timeout=2.0,
    )
    assert result["answers"]["safe"]["noul"] == 1.0
    assert FakeClient.calls[0]["api_key"] == "scoped-key"
    assert broker.stats()["active_operations"] == 0
    runtime.close()


def test_active_async_loop_uses_broker_without_asyncio_run_or_per_call_thread() -> None:
    async def run() -> dict[str, Any]:
        runtime = TypeSafeRuntime(broker_loader=loader, client_factory=FakeClient)
        try:
            return await runtime.execute_async(
                state="text",
                questions=QUESTIONS,
                model="jev-1.13.0",
                api_key="scoped-key",
                timeout=2.0,
            )
        finally:
            runtime.close()

    result = asyncio.run(run())
    assert result["answers"]["safe"]["noul"] == 1.0
    assert broker.stats()["thread_count"] <= 1


def test_timeout_cancels_without_early_slot_release() -> None:
    cancellation_started = threading.Event()
    cleanup_release = threading.Event()
    cleanup_finished = threading.Event()

    class SlowClient(FakeClient):
        async def system_one(self, state: Any, questions: Any) -> dict[str, Any]:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancellation_started.set()
                while not cleanup_release.is_set():
                    try:
                        await asyncio.sleep(0.01)
                    except asyncio.CancelledError:
                        continue
                cleanup_finished.set()
                raise
            return {}

    runtime = TypeSafeRuntime(broker_loader=loader, client_factory=SlowClient)
    try:
        with pytest.raises(Exception) as error:
            runtime.execute_sync(
                state="text",
                questions=QUESTIONS,
                model="jev-1.13.0",
                api_key="scoped-key",
                timeout=0.05,
            )
        assert getattr(error.value, "code", None) == "timeout"
        assert cancellation_started.wait(timeout=1.0)
        assert broker.stats()["active_operations"] == 1

        lease = runtime._lease
        assert lease is not None

        async def blocked() -> None:
            await asyncio.sleep(30)

        extra_operations = [
            broker.try_submit(lease, time.monotonic() + 5.0, blocked)
            for _ in range(3)
        ]
        assert all(operation is not None for operation in extra_operations)
        assert broker.stats()["active_operations"] == 4

        def fifth_work() -> None:
            raise AssertionError("fifth work was invoked before admission")

        assert broker.try_submit(lease, time.monotonic() + 5.0, fifth_work) is None
        assert broker.stats()["active_operations"] == 4
        assert cleanup_finished.is_set() is False
    finally:
        runtime.close()
        time.sleep(0.05)
        cleanup_release.set()
        assert cleanup_finished.wait(timeout=1.0)
        deadline = time.monotonic() + 1.0
        while broker.stats()["active_operations"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert broker.stats()["active_operations"] == 0


def test_shadow_broker_origin_is_not_owned_by_distribution_record(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    shadow = tmp_path / "shadow" / "hermes_typesafe_broker"
    installed = tmp_path / "installed" / "hermes_typesafe_broker"
    shadow.mkdir(parents=True)
    installed.mkdir(parents=True)

    class Distribution:
        files = tuple(Path("hermes_typesafe_broker") / name for name in ("__init__.py", "core.py", "_build_identity.py"))

        def locate_file(self, name: str) -> Path:
            return tmp_path / "installed" / name

    monkeypatch.setattr(runtime_module.importlib.metadata, "distribution", lambda _: Distribution())
    assert runtime_module._distribution_owns(shadow) is False


def test_build_identity_reader_rejects_executable_or_duplicate_assignments(tmp_path: Path) -> None:
    identity = tmp_path / "_build_identity.py"
    identity.write_text(
        '"""generated"""\nimport os\nABI = "typesafe-broker-v1"\nBUILD_SHA256 = "' + "0" * 64 + '"\n',
        encoding="utf-8",
    )
    with pytest.raises(runtime_module.RuntimeUnavailable):
        runtime_module._identity_literals(identity)
