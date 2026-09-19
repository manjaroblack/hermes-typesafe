"""Canonical broker package placeholder for the C foundation wheel.

The package is intentionally stdlib-only and inert. D/H implement the reviewed
process broker; C only proves that the distribution owns a canonical import.
"""

from ._build_identity import ABI, BUILD_SHA256

__all__ = ["ABI", "BUILD_SHA256"]
