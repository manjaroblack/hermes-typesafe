"""Validate the generated canonical broker identity during packaging."""

from __future__ import annotations

import ast
import hashlib
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


_ROOT = Path(__file__).resolve().parent
_BROKER = _ROOT / "broker_src" / "hermes_typesafe_broker"
_EXPECTED_IDENTITIES = (
    _ROOT / "_build_identity.py",
    _BROKER / "_build_identity.py",
)
_BROKER_ABI = "typesafe-broker-v1"


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


def _read_identity(path: Path) -> dict[str, str]:
    """Read generated ABI/hash literals without executing a source file."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as error:
        raise RuntimeError(f"cannot read generated build identity {path}") from error
    values: dict[str, str] = {}
    for index, node in enumerate(tree.body):
        is_docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is str
        )
        if is_docstring:
            continue
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise RuntimeError(f"invalid generated build identity {path}")
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"ABI", "BUILD_SHA256"}:
            raise RuntimeError(f"invalid generated build identity {path}")
        if target.id in values or not isinstance(node.value, ast.Constant) or type(node.value.value) is not str:
            raise RuntimeError(f"invalid generated build identity {path}")
        values[target.id] = node.value.value
    if set(values) != {"ABI", "BUILD_SHA256"}:
        raise RuntimeError(f"invalid generated build identity {path}")
    return values


def _verify_identity() -> None:
    digest = _digest()
    identities = [_read_identity(path) for path in _EXPECTED_IDENTITIES]
    if any(identity["ABI"] != _BROKER_ABI for identity in identities):
        raise RuntimeError(f"canonical broker ABI mismatch; expected {_BROKER_ABI}")
    if any(identity["BUILD_SHA256"] != digest for identity in identities):
        raise RuntimeError(
            "canonical broker build identity mismatch; regenerate "
            f"{_EXPECTED_IDENTITIES[0]} and {_EXPECTED_IDENTITIES[1]} with {digest}"
        )
    if identities[0] != identities[1]:
        raise RuntimeError("native and canonical broker build identities differ")


class VerifiedBuildPy(_build_py):
    def run(self) -> None:
        _verify_identity()
        build_lib = Path(self.build_lib)
        if build_lib.is_dir():
            shutil.rmtree(build_lib)
        super().run()


class VerifiedSdist(_sdist):
    def run(self) -> None:
        _verify_identity()
        super().run()


setup(cmdclass={"build_py": VerifiedBuildPy, "sdist": VerifiedSdist})
