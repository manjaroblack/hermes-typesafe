"""Clean-build archive contract for the native plugin distribution."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

from conftest import ROOT


def _archive_names(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with ZipFile(path) as archive:
            return set(archive.namelist())
    with tarfile.open(path) as archive:
        return {member.name for member in archive.getmembers()}


def _assert_no_private_payload(names: set[str]) -> None:
    forbidden = ("/docs/", "/tests/", "/.worktrees/", "/.env", "\\docs\\", "\\tests\\")
    assert not any(any(marker in name for marker in forbidden) for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)


def test_clean_build_contains_native_and_canonical_assets_without_private_payload(tmp_path: Path) -> None:
    for generated in (ROOT / "build", ROOT / "dist", ROOT / "hermes_typesafe.egg-info"):
        if generated.is_dir():
            shutil.rmtree(generated)
    stale_bytecode = ROOT / "build" / "lib" / "hermes_typesafe" / "__pycache__" / "stale.pyc"
    stale_bytecode.parent.mkdir(parents=True)
    stale_bytecode.write_bytes(b"stale build output")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    wheel = next(tmp_path.glob("*.whl"))
    sdist = next(tmp_path.glob("*.tar.gz"))
    wheel_names = _archive_names(wheel)
    sdist_names = _archive_names(sdist)

    assert "hermes_typesafe/__init__.py" in wheel_names
    assert "hermes_typesafe/_build_identity.py" in wheel_names
    assert "hermes_typesafe/plugin.yaml" in wheel_names
    assert "hermes_typesafe/skills/typesafe-system-one/SKILL.md" in wheel_names
    assert "hermes_typesafe_broker/__init__.py" in wheel_names
    assert "hermes_typesafe_broker/core.py" in wheel_names
    assert "hermes_typesafe_broker/_build_identity.py" in wheel_names
    assert not any(name.startswith("broker_src/") for name in wheel_names)

    assert "hermes_typesafe-0.1.0/broker_src/hermes_typesafe_broker/core.py" in sdist_names
    assert "hermes_typesafe-0.1.0/skills/typesafe-system-one/SKILL.md" in sdist_names
    assert "hermes_typesafe-0.1.0/hermes_typesafe.egg-info/PKG-INFO" in sdist_names

    _assert_no_private_payload(wheel_names)
    _assert_no_private_payload(sdist_names)
