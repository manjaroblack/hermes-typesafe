"""Reproducible identity calculation for the canonical broker source inputs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


BROKER_ABI = "typesafe-broker-v1"
_BROKER_INPUTS = ("__init__.py", "core.py")


def broker_source_dir(root: Path | None = None) -> Path:
    """Locate the source broker directory in a checkout."""

    base = root or Path(__file__).resolve().parent
    return base / "broker_src" / "hermes_typesafe_broker"


def broker_source_digest(source_dir: Path | None = None) -> str:
    """Hash exact, sorted broker source records using the v3 framing contract."""

    directory = source_dir or broker_source_dir()
    payload = bytearray()
    for relative in sorted(_BROKER_INPUTS):
        path = directory / relative
        data = path.read_bytes()
        name = relative.encode("utf-8")
        payload.extend(name)
        payload.extend(b"\0")
        payload.extend(str(len(data)).encode("ascii"))
        payload.extend(b"\0")
        payload.extend(data)
    return hashlib.sha256(payload).hexdigest()


def _read_generated_identity(path: Path) -> dict[str, str]:
    """Read generated identity literals without executing the file."""

    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"ABI", "BUILD_SHA256"}:
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            values[target.id] = node.value.value
    return values


def build_identity() -> dict[str, Any]:
    """Return computed and generated broker identity facts for diagnostics/tests."""

    source_dir = broker_source_dir()
    computed = broker_source_digest(source_dir) if source_dir.is_dir() else None
    generated_path = source_dir / "_build_identity.py"
    generated = _read_generated_identity(generated_path) if generated_path.is_file() else {}
    if not generated:
        try:
            from hermes_typesafe_broker import ABI, BUILD_SHA256
        except Exception:
            ABI, BUILD_SHA256 = BROKER_ABI, ""
        generated = {"ABI": ABI, "BUILD_SHA256": BUILD_SHA256}
    return {
        "abi": generated.get("ABI", BROKER_ABI),
        "build_sha256": computed or generated.get("BUILD_SHA256", ""),
        "generated_build_sha256": generated.get("BUILD_SHA256", ""),
    }
