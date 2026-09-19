"""RED contract for canonical broker ownership and global admission."""

from __future__ import annotations

import asyncio
import secrets
import sys
import time

import pytest

import hermes_typesafe_broker.core as broker

pytestmark = pytest.mark.skipif(
    sys.version_info[:2] not in {(3, 10), (3, 11), (3, 12)},
    reason="canonical broker supports CPython 3.10-3.12 main interpreters only",
)


@pytest.fixture(autouse=True)
def clean_broker() -> None:
    broker._reset_for_tests()
    yield
    broker.shutdown(time.monotonic() + 0.5)
    broker._reset_for_tests()


def acquire() -> object:
    lease = broker.acquire(broker.ABI, broker.BUILD_SHA256, secrets.token_bytes(32))
    assert lease is not None
    return lease


def test_import_is_inert_and_one_canonical_owner_is_shared() -> None:
    stats = broker.stats()
    assert stats["state"] == "NEW"
    assert stats["thread_count"] == 0
    assert broker.owner_identity()["module"] == "hermes_typesafe_broker.core"


def test_global_four_admissions_and_no_waiting_queue() -> None:
    lease = acquire()
    started = asyncio.Event()

    async def blocked() -> str:
        started.set()
        await asyncio.sleep(30)
        return "late"

    operations = [
        broker.try_submit(lease, time.monotonic() + 2.0, blocked)
        for _ in range(4)
    ]
    assert all(operation is not None for operation in operations)
    fifth = broker.try_submit(lease, time.monotonic() + 2.0, blocked)
    assert fifth is None
    stats = broker.stats()
    assert stats["active_operations"] == 4
    assert stats["waiting_queue"] == 0
    assert stats["thread_count"] == 1

    for operation in operations:
        assert operation is not None
        operation.cancel()
    assert broker.shutdown(time.monotonic() + 0.5) in {"closed", "broken"}


def test_revoke_drops_late_result_and_release_is_idempotent() -> None:
    lease = acquire()
    gate = asyncio.Event()

    async def late() -> dict[str, str]:
        await gate.wait()
        return {"sentinel": "must-not-escape"}

    operation = broker.try_submit(lease, time.monotonic() + 2.0, late)
    assert operation is not None
    broker.release(lease)
    broker.release(lease)
    gate.set()
    with pytest.raises(broker.OperationUnavailable):
        operation.result(timeout=0.5)
    assert broker.stats()["active_leases"] == 0


def test_absolute_deadline_rejects_synchronous_work_that_finishes_late() -> None:
    lease = acquire()

    def late_sync() -> str:
        time.sleep(0.05)
        return "must-not-escape"

    operation = broker.try_submit(lease, time.monotonic() + 0.01, late_sync)
    assert operation is not None
    with pytest.raises(broker.OperationUnavailable):
        operation.result(timeout=0.5)


def test_broker_rejects_nonfinite_deadlines_before_admission() -> None:
    lease = acquire()
    assert broker.try_submit(lease, float("nan"), lambda: "unused") is None
