"""Canonical process broker for the TypeSafe native plugin.

This module is intentionally stdlib-only. It owns one process broker, one lazy
main-interpreter event-loop thread, and bounded cross-home admission. SDK
clients, credentials, settings, and host context never enter this module.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import math
import os
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, TypeAlias

if __name__ != "hermes_typesafe_broker.core":
    raise ImportError("canonical broker must be imported as hermes_typesafe_broker.core")

from ._build_identity import ABI, BUILD_SHA256

MAX_ACTIVE_LEASES = 128
MAX_ADMITTED_OPERATIONS = 4
MAX_TASKS = 8
CLEANUP_WAIT_SECONDS = 0.2


class OperationUnavailable(RuntimeError):
    """The lease was revoked, broker closed, or operation was cancelled."""


LeaseToken: TypeAlias = "Lease"
Work: TypeAlias = Callable[[], Any]


@dataclass
class Lease:
    nonce: bytes
    generation: int
    revoked: bool = False
    operations: set["Operation"] = field(default_factory=set)


class Operation:
    """Sanitized future handle whose slot remains charged until task exit."""

    def __init__(self, owner: "_Broker", lease: Lease, deadline: float) -> None:
        self._owner = owner
        self.lease = lease
        self.deadline = deadline
        self.future: Future[Any] = Future()
        self.task: asyncio.Task[Any] | None = None
        self.task_slot_charged = False
        self.cancel_requested = False
        self._lock = threading.Lock()

    def cancel(self) -> bool:
        with self._lock:
            self.cancel_requested = True
        self._owner._request_cancel(self)
        return True

    def result(self, timeout: float | None = None) -> Any:
        try:
            return self.future.result(timeout=timeout)
        except FutureTimeout:
            raise
        except OperationUnavailable:
            raise
        except Exception as error:
            if isinstance(error, OperationUnavailable):
                raise
            raise OperationUnavailable from None

    def _set_result(self, value: Any) -> None:
        if not self.future.done():
            self.future.set_result(value)

    def _set_unavailable(self) -> None:
        if not self.future.done():
            self.future.set_exception(OperationUnavailable())


class _Broker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._startup_lock = threading.Lock()
        self._state = "NEW"
        self._owner_pid = os.getpid()
        self._generation = 0
        self._leases: dict[bytes, Lease] = {}
        self._operations: set[Operation] = set()
        self._active_operations = 0
        self._task_count = 0
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._startup_owner: int | None = None

    def _runtime_supported(self) -> bool:
        if sys.implementation.name != "cpython" or sys.version_info[:2] not in {(3, 10), (3, 11), (3, 12)}:
            return False
        try:
            import _xxsubinterpreters

            return _xxsubinterpreters.get_current() == _xxsubinterpreters.get_main()
        except Exception:
            return False

    def _pid_ok(self) -> bool:
        return self._owner_pid == os.getpid()

    def acquire(self, abi: str, build_id: str, nonce: bytes) -> Lease | None:
        valid_identity = (
            type(abi) is str
            and type(build_id) is str
            and abi == ABI
            and build_id == BUILD_SHA256
            and type(nonce) is bytes
            and len(nonce) == 32
        )
        if not valid_identity:
            return None
        if not self._runtime_supported():
            return None
        with self._lock:
            if not self._pid_ok() or self._state in {"BROKEN", "CLOSING", "CLOSED"}:
                if not self._pid_ok():
                    self._state = "BROKEN"
                return None
            if len(self._leases) >= MAX_ACTIVE_LEASES or nonce in self._leases:
                return None
            self._generation += 1
            lease = Lease(nonce=nonce, generation=self._generation)
            self._leases[nonce] = lease
            return lease

    def release(self, lease: Lease | None) -> None:
        if lease is None:
            return
        with self._lock:
            if lease.revoked:
                return
            lease.revoked = True
            for operation in tuple(lease.operations):
                operation.cancel_requested = True
                self._schedule_cancel(operation)
            self._leases.pop(lease.nonce, None)
            self._condition.notify_all()

    def _start_loop(self) -> bool:
        with self._startup_lock:
            with self._lock:
                if self._state == "RUNNING":
                    return True
                if self._state != "NEW":
                    return False
                self._state = "STARTING"
                self._startup_owner = threading.get_ident()
                self._ready.clear()
                thread = threading.Thread(target=self._thread_main, name="typesafe-broker", daemon=True)
                self._thread = thread
                try:
                    thread.start()
                except Exception:
                    self._state = "BROKEN"
                    self._thread = None
                    self._condition.notify_all()
                    return False
            if not self._ready.wait(CLEANUP_WAIT_SECONDS):
                with self._lock:
                    self._state = "BROKEN"
                    self._condition.notify_all()
                return False
            with self._lock:
                return self._state == "RUNNING" and self._loop is not None

    def _thread_main(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self._lock:
                if self._state != "STARTING":
                    loop.close()
                    return
                self._loop = loop
                self._state = "RUNNING"
                self._ready.set()
                self._condition.notify_all()
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
        except Exception:
            with self._lock:
                self._state = "BROKEN"
                self._ready.set()
                self._condition.notify_all()
        finally:
            with self._lock:
                if self._state == "RUNNING":
                    self._state = "CLOSED"
                self._loop = None
                self._condition.notify_all()

    def try_submit(self, lease: Lease | None, deadline: float, work: Work) -> Operation | None:
        if not callable(work) or type(deadline) not in (float, int):
            return None
        try:
            deadline_value = float(deadline)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(deadline_value) or time.monotonic() >= deadline_value:
            return None
        with self._lock:
            if not self._pid_ok() or self._state in {"BROKEN", "CLOSING", "CLOSED"}:
                return None
            if lease is None or lease.revoked or self._leases.get(lease.nonce) is not lease:
                return None
            if self._active_operations >= MAX_ADMITTED_OPERATIONS or self._task_count >= MAX_TASKS:
                return None
            operation = Operation(self, lease, deadline_value)
            self._active_operations += 1
            self._operations.add(operation)
            lease.operations.add(operation)
            start_needed = self._state in {"NEW", "STARTING"}
        if start_needed and not self._start_loop():
            self._finish(operation, unavailable=True)
            return None
        with self._lock:
            loop = self._loop
            if self._state != "RUNNING" or loop is None:
                self._finish(operation, unavailable=True)
                return None
            self._task_count += 1
            operation.task_slot_charged = True
        empty = contextvars.Context()

        def schedule() -> None:
            def create() -> None:
                if operation.cancel_requested or operation.lease.revoked:
                    self._finish(operation, unavailable=True)
                    return
                try:
                    task = loop.create_task(self._runner(operation, work))
                except Exception:
                    self._finish(operation, unavailable=True)
                    return
                operation.task = task

            empty.run(create)

        try:
            loop.call_soon_threadsafe(schedule)
        except Exception:
            self._finish(operation, unavailable=True)
            return None
        return operation

    async def _runner(self, operation: Operation, work: Work) -> None:
        try:
            if operation.cancel_requested or operation.lease.revoked:
                raise OperationUnavailable
            remaining = operation.deadline - time.monotonic()
            if remaining <= 0:
                raise OperationUnavailable
            produced = work()
            remaining = operation.deadline - time.monotonic()
            if remaining <= 0:
                if inspect.iscoroutine(produced):
                    produced.close()
                raise OperationUnavailable
            result = await asyncio.wait_for(produced, timeout=remaining) if inspect.isawaitable(produced) else produced
            with self._lock:
                valid = not operation.cancel_requested and not operation.lease.revoked and self._state not in {"CLOSING", "CLOSED"}
            if valid:
                operation._set_result(result)
            else:
                operation._set_unavailable()
        except asyncio.CancelledError:
            operation._set_unavailable()
        except OperationUnavailable:
            operation._set_unavailable()
        except asyncio.TimeoutError:
            operation._set_unavailable()
        except Exception:
            operation._set_unavailable()
        finally:
            self._finish(operation)

    def _request_cancel(self, operation: Operation) -> None:
        self._schedule_cancel(operation)

    def _schedule_cancel(self, operation: Operation) -> None:
        with self._lock:
            loop = self._loop
            task = operation.task
        if loop is None or task is None or task.done():
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except Exception:
            return

    def _finish(self, operation: Operation, *, unavailable: bool = False) -> None:
        if unavailable:
            operation._set_unavailable()
        with self._lock:
            if operation not in self._operations:
                return
            self._operations.discard(operation)
            operation.lease.operations.discard(operation)
            self._active_operations = max(0, self._active_operations - 1)
            if operation.task_slot_charged:
                self._task_count = max(0, self._task_count - 1)
            self._condition.notify_all()

    def shutdown(self, deadline: float) -> str:
        with self._lock:
            if self._state == "NEW":
                self._state = "CLOSED"
                return "closed"
            if self._state in {"CLOSED", "BROKEN"}:
                return self._state.lower()
            self._state = "CLOSING"
            leases = tuple(self._leases.values())
        for lease in leases:
            self.release(lease)
        end = min(float(deadline), time.monotonic() + CLEANUP_WAIT_SECONDS)
        with self._condition:
            while self._active_operations and time.monotonic() < end:
                self._condition.wait(max(0.0, end - time.monotonic()))
            loop = self._loop
            thread = self._thread
            if self._active_operations:
                self._state = "BROKEN"
                return "broken"
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                with self._lock:
                    self._state = "BROKEN"
                return "broken"
        if thread is not None:
            thread.join(max(0.0, end - time.monotonic()))
        with self._lock:
            if thread is not None and thread.is_alive():
                self._state = "BROKEN"
                return "broken"
            self._state = "CLOSED"
            return "closed"

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "owner_pid": self._owner_pid,
                "active_leases": len(self._leases),
                "active_operations": self._active_operations,
                "task_count": self._task_count,
                "waiting_queue": 0,
                "thread_count": int(self._thread is not None and self._thread.is_alive()),
                "loop_alive": int(self._loop is not None),
            }

    def owner_identity(self) -> dict[str, Any]:
        return {"module": __name__, "pid": self._owner_pid}

    def reset_for_tests(self) -> None:
        """Best-effort fixture reset; never used by production paths."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                loop = self._loop
                if loop is not None:
                    loop.call_soon_threadsafe(loop.stop)
            self._state = "NEW"
            self._owner_pid = os.getpid()
            self._generation = 0
            self._leases.clear()
            self._operations.clear()
            self._active_operations = 0
            self._task_count = 0
            self._thread = None
            self._loop = None
            self._ready.clear()
            self._condition.notify_all()


_BROKER = _Broker()


def acquire(abi: str, build_id: str, opaque_nonce: bytes) -> Lease | None:
    return _BROKER.acquire(abi, build_id, opaque_nonce)


def release(lease: Lease | None) -> None:
    _BROKER.release(lease)


def try_submit(lease: Lease | None, deadline: float, work: Work) -> Operation | None:
    return _BROKER.try_submit(lease, deadline, work)


def shutdown(deadline: float) -> str:
    return _BROKER.shutdown(deadline)


def stats() -> dict[str, Any]:
    return _BROKER.stats()


def owner_identity() -> dict[str, Any]:
    return _BROKER.owner_identity()


def _reset_for_tests() -> None:
    _BROKER.reset_for_tests()


__all__ = [
    "ABI",
    "BUILD_SHA256",
    "Lease",
    "Operation",
    "OperationUnavailable",
    "acquire",
    "owner_identity",
    "release",
    "shutdown",
    "stats",
    "try_submit",
]
