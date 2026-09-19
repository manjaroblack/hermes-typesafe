"""C-phase runtime boundary: unavailable until the reviewed broker is implemented."""

from __future__ import annotations


RUNTIME_STATUS = "foundation_unavailable"


def runtime_status() -> dict[str, str]:
    """Describe the static foundation boundary without importing SDK/runtime code."""

    return {
        "status": "runtime_unavailable",
        "reason": "canonical TypeSafe broker runtime is deferred to a later phase",
    }
