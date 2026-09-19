"""Validate the generated canonical broker identity during packaging."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


_ROOT = Path(__file__).resolve().parent
_BROKER = _ROOT / "broker_src" / "hermes_typesafe_broker"
_EXPECTED_IDENTITY = _BROKER / "_build_identity.py"


def _digest() -> str:
    payload = bytearray()
    for relative in ("__init__.py", "core.py"):
        data = (_BROKER / relative).read_bytes()
        payload.extend(relative.encode("utf-8"))
        payload.extend(b"\0")
        payload.extend(str(len(data)).encode("ascii"))
        payload.extend(b"\0")
        payload.extend(data)
    return hashlib.sha256(payload).hexdigest()


def _verify_identity() -> None:
    text = _EXPECTED_IDENTITY.read_text(encoding="utf-8")
    match = re.search(r'^BUILD_SHA256 = "([0-9a-f]{64})"$', text, re.MULTILINE)
    digest = _digest()
    if match is None or match.group(1) != digest:
        raise RuntimeError(
            "canonical broker build identity mismatch; regenerate "
            f"{_EXPECTED_IDENTITY} with {digest}"
        )


class VerifiedBuildPy(_build_py):
    def run(self) -> None:
        _verify_identity()
        super().run()


class VerifiedSdist(_sdist):
    def run(self) -> None:
        _verify_identity()
        super().run()


setup(cmdclass={"build_py": VerifiedBuildPy, "sdist": VerifiedSdist})
