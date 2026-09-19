"""No-op canonical broker boundary reserved for the reviewed runtime phase."""

from __future__ import annotations

from typing import Any

from ._build_identity import ABI, BUILD_SHA256


RUNTIME_STATUS = "foundation_unavailable"


def acquire(*_: Any, **__: Any) -> None:
    """Return no lease until the canonical broker runtime is implemented."""

    return None


def release(*_: Any, **__: Any) -> None:
    """Idempotent foundation release boundary."""

    return None


def try_submit(*_: Any, **__: Any) -> None:
    """Reject work without creating a task, thread, client, or network request."""

    return None


def shutdown(*_: Any, **__: Any) -> dict[str, str]:
    """Report the static unavailable state without mutating process state."""

    return {"status": "runtime_unavailable", "abi": ABI, "build_sha256": BUILD_SHA256}
