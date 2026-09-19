"""Held production skill adapter and bounded verified-snapshot fixtures.

The inspected Hermes hosts do not expose a safe immutable skill snapshot seam.
This module therefore never discovers skills in production.  The descriptor and
snapshot helpers are explicit, side-effect-free fixtures for a future reviewed
host capability and for the bundled skill's contract tests.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

try:
    from .questions import SUGGESTION_EXCERPT_CHARS
except ImportError:  # pragma: no cover - flat plugin import
    from questions import SUGGESTION_EXCERPT_CHARS

HELD_UNSUPPORTED_HOST = "HELD_UNSUPPORTED_HOST"
MAX_SKILL_NAME_BYTES = 128
MAX_DESCRIPTION_BYTES = 512
MAX_EXCERPT_CHARS = SUGGESTION_EXCERPT_CHARS
MAX_EXCERPT_BYTES = 2_800
MAX_RAW_SKILL_BYTES = 32_768
MAX_SNAPSHOT_RAW_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_METADATA_BYTES = 262_144
MAX_SNAPSHOT_ENTRIES = 128
MAX_SNAPSHOT_PATH_ENTRIES = 2_048
MAX_SNAPSHOT_PATH_DEPTH = 16
MAX_SNAPSHOT_PATH_BYTES = 4_096

_NAME_PART = re.compile(r"^[A-Za-z0-9_-]+$")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_UNSET = object()


class SnapshotUnavailable(ValueError):
    """A descriptor or immutable snapshot cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """Verified name and text derived from one bounded regular SKILL.md."""

    name: str
    description: str
    excerpt: str = ""

    def __post_init__(self) -> None:
        normalized_name = _validated_skill_name(self.name)
        normalized_description = _validated_description(self.description)
        normalized_excerpt = _validated_excerpt(self.excerpt)
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "description", normalized_description)
        object.__setattr__(self, "excerpt", normalized_excerpt)


@dataclass(frozen=True, slots=True)
class VerifiedSkillSnapshot:
    """Immutable, generation-bound visible skill descriptors."""

    generation: str
    skills: tuple[SkillDescriptor, ...]
    profile_generation: str
    registry_generation: str
    roots_generation: str
    quarantine_generation: str

    def __post_init__(self) -> None:
        _validated_generation(self.generation)
        for value in (
            self.profile_generation,
            self.registry_generation,
            self.roots_generation,
            self.quarantine_generation,
        ):
            _validated_generation(value)
        if type(self.skills) is not tuple or len(self.skills) > MAX_SNAPSHOT_ENTRIES:
            raise SnapshotUnavailable("snapshot entry cap or container type rejected")
        names: set[str] = set()
        for descriptor in self.skills:
            if not isinstance(descriptor, SkillDescriptor) or descriptor.name in names:
                raise SnapshotUnavailable("duplicate or unverified descriptor")
            names.add(descriptor.name)


# Short aliases make the fixture contract pleasant to use without exposing a
# production discovery API.
SkillSnapshot = VerifiedSkillSnapshot


def is_snapshot_current(snapshot: Any, generation: Any) -> bool:
    """Check the immutable generation before consuming a future snapshot."""

    return (
        isinstance(snapshot, VerifiedSkillSnapshot)
        and type(generation) is str
        and snapshot.generation == generation
        and snapshot.profile_generation == generation
        and snapshot.registry_generation == generation
        and snapshot.roots_generation == generation
        and snapshot.quarantine_generation == generation
    )


def _validated_generation(value: Any) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8", errors="strict")) > MAX_DESCRIPTION_BYTES:
        raise SnapshotUnavailable("snapshot generation is missing or oversized")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise SnapshotUnavailable("snapshot generation contains control data")
    return value


def _validated_skill_name(value: Any) -> str:
    if type(value) is not str or not value:
        raise SnapshotUnavailable("skill name is not a string")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise SnapshotUnavailable("skill name must be ASCII") from None
    if len(encoded) > MAX_SKILL_NAME_BYTES or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise SnapshotUnavailable("skill name is oversized or contains control data")
    if "/" in value or "\\" in value or ".." in value:
        raise SnapshotUnavailable("skill name contains traversal data")
    parts = value.split(":")
    if len(parts) > 2 or any(not _NAME_PART.fullmatch(part) for part in parts):
        raise SnapshotUnavailable("skill name is not a qualified or bare name")
    return value


def validate_skill_name(value: Any) -> bool:
    """Return whether a bare or one-namespace skill name is safe to emit."""

    try:
        _validated_skill_name(value)
    except Exception:
        return False
    return True


def _validated_description(value: Any) -> str:
    if type(value) is not str:
        raise SnapshotUnavailable("skill description is not a string")
    normalized = " ".join(value.split())
    if len(normalized.encode("utf-8", errors="strict")) > MAX_DESCRIPTION_BYTES:
        raise SnapshotUnavailable("skill description is oversized")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in normalized):
        raise SnapshotUnavailable("skill description contains control data")
    return normalized


def _validated_excerpt(value: Any) -> str:
    if type(value) is not str:
        raise SnapshotUnavailable("skill excerpt is not a string")
    if len(value) > MAX_EXCERPT_CHARS or len(value.encode("utf-8", errors="strict")) > MAX_EXCERPT_BYTES:
        raise SnapshotUnavailable("skill excerpt is oversized")
    if "\x00" in value or "\x7f" in value:
        raise SnapshotUnavailable("skill excerpt contains unsafe control data")
    return value


def _bounded_excerpt(value: str) -> str:
    excerpt = value[:MAX_EXCERPT_CHARS]
    while len(excerpt.encode("utf-8", errors="strict")) > MAX_EXCERPT_BYTES:
        excerpt = excerpt[:-1]
    return excerpt


def skill_descriptor(
    name: str,
    description: str,
    excerpt: str = "",
    *,
    namespace: str | None = None,
) -> SkillDescriptor:
    """Create one detached verified fixture descriptor.

    ``namespace`` is only a fixture convenience.  Production code cannot use
    it to discover or qualify a host skill.
    """

    if namespace is not None:
        if type(namespace) is not str or not _NAME_PART.fullmatch(namespace):
            raise SnapshotUnavailable("invalid plugin namespace")
        if ":" in name:
            raise SnapshotUnavailable("descriptor already has a namespace")
        name = f"{namespace}:{name}"
    return SkillDescriptor(name=name, description=description, excerpt=excerpt)


def make_verified_snapshot(
    descriptors: Iterable[SkillDescriptor | Mapping[str, Any]],
    *,
    generation: str | None,
    profile_generation: str | None | object = _UNSET,
    registry_generation: str | None | object = _UNSET,
    roots_generation: str | None | object = _UNSET,
    quarantine_generation: str | None | object = _UNSET,
    enabled: bool = True,
    platform_ok: bool = True,
    environment_ok: bool = True,
    project_trust: bool = True,
    active_org: bool = True,
    quarantined: Iterable[str] = (),
) -> VerifiedSkillSnapshot | None:
    """Build a bounded synthetic snapshot, or ``None`` on any uncertainty."""

    if any(type(flag) is not bool or flag is False for flag in (enabled, platform_ok, environment_ok, project_trust, active_org)):
        return None
    try:
        generation_value = _validated_generation(generation)
        metadata = tuple(
            generation_value if value is _UNSET else _validated_generation(value)
            for value in (profile_generation, registry_generation, roots_generation, quarantine_generation)
        )
        if len(metadata) != 4:
            return None
        quarantine_values = _bounded_strings(quarantined, MAX_SNAPSHOT_ENTRIES)
        if quarantine_values is None or quarantine_values:
            return None
        collected = _bounded_descriptors(descriptors)
        if collected is None:
            return None
        names = {descriptor.name for descriptor in collected}
        if len(names) != len(collected):
            return None
        metadata_payload = {
            "generation": generation_value,
            "profile": metadata[0],
            "registry": metadata[1],
            "roots": metadata[2],
            "quarantine": metadata[3],
            "skills": [
                {"name": descriptor.name, "description": descriptor.description, "excerpt": descriptor.excerpt}
                for descriptor in collected
            ],
        }
        encoded = json.dumps(metadata_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        if len(encoded) > MAX_SNAPSHOT_METADATA_BYTES:
            return None
        return VerifiedSkillSnapshot(
            generation=generation_value,
            skills=tuple(sorted(collected, key=lambda descriptor: descriptor.name)),
            profile_generation=metadata[0],
            registry_generation=metadata[1],
            roots_generation=metadata[2],
            quarantine_generation=metadata[3],
        )
    except (SnapshotUnavailable, TypeError, ValueError, UnicodeError):
        return None


def _bounded_descriptors(
    descriptors: Iterable[SkillDescriptor | Mapping[str, Any]],
) -> list[SkillDescriptor] | None:
    if type(descriptors) in (str, bytes, bytearray) or descriptors is None:
        return None
    collected: list[SkillDescriptor] = []
    try:
        iterator = iter(descriptors)
        for _ in range(MAX_SNAPSHOT_ENTRIES + 1):
            try:
                item = next(iterator)
            except StopIteration:
                break
            if isinstance(item, SkillDescriptor):
                collected.append(item)
                continue
            if type(item) is not dict or set(item) - {"name", "description", "excerpt"}:
                return None
            collected.append(skill_descriptor(item.get("name"), item.get("description"), item.get("excerpt", "")))
        else:
            return None
    except Exception:
        return None
    return collected


def _bounded_strings(values: Iterable[str], cap: int) -> set[str] | None:
    if type(values) in (str, bytes, bytearray) or values is None:
        return None
    output: set[str] = set()
    try:
        for index, value in enumerate(values):
            if index >= cap:
                return None
            output.add(_validated_skill_name(value))
    except Exception:
        return None
    return output


class HeldSkillsAdapter:
    """Current-host adapter: no roster, filesystem, provider, or hook access."""

    status = HELD_UNSUPPORTED_HOST

    def __init__(self, *, provider: Any = None) -> None:
        # Accept a fixture poison object but do not retain or inspect it.
        del provider

    def snapshot(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    def get_snapshot(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    def suggestion_context(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    def suggest(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    def register_hook(self, *args: Any, **kwargs: Any) -> bool:
        del args, kwargs
        return False


ProductionSkillsAdapter = HeldSkillsAdapter


def production_snapshot(*args: Any, **kwargs: Any) -> None:
    """Return no snapshot on the inspected hosts; never probe private seams."""

    del args, kwargs
    return None


def _path_component_safe(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and "\\" not in value and "\x00" not in value and not any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    )


def _absolute_components(root: Any) -> list[str] | None:
    try:
        raw = os.fspath(root)
    except TypeError:
        return None
    if type(raw) is not str or not raw.startswith(os.sep) or "\x00" in raw:
        return None
    if len(raw.encode("utf-8", errors="strict")) > MAX_SNAPSHOT_PATH_BYTES:
        return None
    pieces = [piece for piece in raw.split(os.sep) if piece]
    if len(pieces) > MAX_SNAPSHOT_PATH_DEPTH or any(not _path_component_safe(piece) for piece in pieces):
        return None
    return pieces


def _relative_components(path: Any) -> list[str] | None:
    try:
        raw = os.fspath(path)
    except TypeError:
        return None
    if type(raw) is not str or not raw or raw.startswith(os.sep) or "\\" in raw or "\x00" in raw:
        return None
    if len(raw.encode("utf-8", errors="strict")) > MAX_SNAPSHOT_PATH_BYTES:
        return None
    pieces = raw.split("/")
    if len(pieces) > MAX_SNAPSHOT_PATH_DEPTH or any(not _path_component_safe(piece) for piece in pieces):
        return None
    return pieces


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    if not getattr(os, "O_NOFOLLOW", 0):
        raise SnapshotUnavailable("platform lacks O_NOFOLLOW")
    return flags | os.O_NOFOLLOW


def _open_absolute_directory(root: Any) -> int:
    components = _absolute_components(root)
    if components is None:
        raise SnapshotUnavailable("root must be an absolute no-dot path")
    directory_flags = _directory_flags()
    fd = os.open(os.sep, directory_flags)
    try:
        for component in components:
            next_fd = os.open(component, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_target(root: Any, relative_path: Any) -> tuple[int, int]:
    components = _relative_components(relative_path)
    if components is None:
        raise SnapshotUnavailable("relative skill path rejected")
    root_fd = _open_absolute_directory(root)
    current_fd = root_fd
    directory_flags = _directory_flags()
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | os.O_NOFOLLOW
    try:
        for component in components[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(components[-1], file_flags, dir_fd=current_fd)
        if current_fd != root_fd:
            os.close(current_fd)
        return root_fd, file_fd
    except Exception:
        if current_fd != root_fd:
            try:
                os.close(current_fd)
            except OSError:
                pass
        try:
            os.close(root_fd)
        except OSError:
            pass
        raise


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_bounded(fd: int, cap: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(8_192, cap + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > cap:
            raise SnapshotUnavailable("raw skill exceeds cap")
    return b"".join(chunks)


def _read_verified_bytes(root: Any, relative_path: Any) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    components = _relative_components(relative_path)
    if components is None or components[-1] != "SKILL.md":
        raise SnapshotUnavailable("only SKILL.md is a descriptor source")
    root_fd, file_fd = _open_target(root, relative_path)
    try:
        root_before = _file_identity(os.fstat(root_fd))
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_RAW_SKILL_BYTES:
            raise SnapshotUnavailable("skill is not one bounded regular file")
        identity = _file_identity(before)
        data = _read_bounded(file_fd, MAX_RAW_SKILL_BYTES)
        after = os.fstat(file_fd)
        if _file_identity(after) != identity:
            raise SnapshotUnavailable("skill changed during bounded read")
    finally:
        try:
            os.close(file_fd)
        finally:
            os.close(root_fd)

    second_root_fd, second_file_fd = _open_target(root, relative_path)
    try:
        if _file_identity(os.fstat(second_root_fd)) != root_before:
            raise SnapshotUnavailable("declared root changed")
        second = os.fstat(second_file_fd)
        if not stat.S_ISREG(second.st_mode) or second.st_nlink != 1 or _file_identity(second) != identity:
            raise SnapshotUnavailable("skill identity changed after read")
    finally:
        try:
            os.close(second_file_fd)
        finally:
            os.close(second_root_fd)
    return data, identity


def _parse_frontmatter(data: bytes, expected_name: str) -> SkillDescriptor:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SnapshotUnavailable("skill is not UTF-8") from None
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise SnapshotUnavailable("skill frontmatter is missing")
    values: dict[str, str] = {}
    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.rstrip("\r\n")
        if stripped == "---":
            end_index = index
            break
        if not stripped or stripped.startswith((" ", "\t")) or ":" not in stripped:
            raise SnapshotUnavailable("skill frontmatter is not flat scalar data")
        key, raw_value = stripped.split(":", 1)
        if not _KEY.fullmatch(key) or key in values:
            raise SnapshotUnavailable("skill frontmatter has invalid or duplicate keys")
        value = raw_value.strip()
        if not value or value.startswith(("!", "&", "*", "{", "[")):
            raise SnapshotUnavailable("skill frontmatter uses unsupported YAML features")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise SnapshotUnavailable("skill frontmatter has an unterminated scalar")
            value = value[1:-1]
        values[key] = value
    if end_index is None or type(values.get("name")) is not str or type(values.get("description")) is not str:
        raise SnapshotUnavailable("skill frontmatter lacks name or description")
    requested = _validated_skill_name(expected_name)
    raw_name = _validated_skill_name(values["name"])
    if raw_name != requested and not (":" in requested and raw_name == requested.split(":", 1)[1]):
        raise SnapshotUnavailable("frontmatter name is not the visible host identity")
    body = "".join(lines[end_index + 1 :])
    return skill_descriptor(requested, values["description"], _bounded_excerpt(body))


def _read_verified_descriptor_with_identity(
    root: Any,
    relative_path: Any,
    *,
    expected_name: str,
) -> tuple[SkillDescriptor, tuple[int, int, int, int, int, int], int] | None:
    try:
        requested = _validated_skill_name(expected_name)
        data, identity = _read_verified_bytes(root, relative_path)
        descriptor = _parse_frontmatter(data, requested)
        return descriptor, identity, len(data)
    except (OSError, SnapshotUnavailable, UnicodeError, ValueError):
        return None


def read_verified_descriptor(
    root: str | os.PathLike[str],
    relative_path: str | os.PathLike[str],
    *,
    expected_name: str,
) -> SkillDescriptor | None:
    """Read one anchored, bounded, regular SKILL.md without following links."""

    result = _read_verified_descriptor_with_identity(root, relative_path, expected_name=expected_name)
    return result[0] if result is not None else None


def build_verified_snapshot_from_files(
    root: str | os.PathLike[str],
    entries: Iterable[Mapping[str, Any]],
    *,
    generation: str | None,
    **snapshot_kwargs: Any,
) -> VerifiedSkillSnapshot | None:
    """Build a fixture snapshot from explicit lexical paths and trust priority.

    ``priority=0`` is the most trusted root.  A broken or quarantined winner
    never falls back to a lower-priority shadow.  This helper is not called by
    the held production adapter.
    """

    if type(entries) in (str, bytes, bytearray) or entries is None:
        return None
    collected: list[tuple[str, str, int, int]] = []
    try:
        iterator = iter(entries)
        for index in range(MAX_SNAPSHOT_PATH_ENTRIES + 1):
            try:
                entry = next(iterator)
            except StopIteration:
                break
            if type(entry) is not dict or set(entry) - {"name", "relative_path", "priority"}:
                return None
            name = _validated_skill_name(entry.get("name"))
            relative_path = entry.get("relative_path")
            if _relative_components(relative_path) is None:
                return None
            priority = entry.get("priority", 2)
            if type(priority) is not int or priority < 0 or priority > 2:
                return None
            collected.append((name, os.fspath(relative_path), priority, index))
        else:
            return None
    except Exception:
        return None

    selected: dict[str, tuple[str, int, int]] = {}
    for name, relative_path, priority, index in collected:
        previous = selected.get(name)
        if previous is not None:
            if previous[1] == priority:
                return None
            if priority < previous[1]:
                selected[name] = (relative_path, priority, index)
        else:
            selected[name] = (relative_path, priority, index)

    descriptors: list[SkillDescriptor] = []
    identities: set[tuple[int, int, int, int, int, int]] = set()
    total_bytes = 0
    for name in sorted(selected):
        relative_path, _, _ = selected[name]
        result = _read_verified_descriptor_with_identity(root, relative_path, expected_name=name)
        if result is None:
            return None
        descriptor, identity, raw_size = result
        if identity in identities:
            return None
        identities.add(identity)
        total_bytes += raw_size
        if total_bytes > MAX_SNAPSHOT_RAW_BYTES:
            return None
        descriptors.append(descriptor)
    return make_verified_snapshot(descriptors, generation=generation, **snapshot_kwargs)


__all__ = [
    "HELD_UNSUPPORTED_HOST",
    "HeldSkillsAdapter",
    "MAX_EXCERPT_CHARS",
    "MAX_RAW_SKILL_BYTES",
    "MAX_SNAPSHOT_PATH_BYTES",
    "ProductionSkillsAdapter",
    "SkillDescriptor",
    "SkillSnapshot",
    "SnapshotUnavailable",
    "VerifiedSkillSnapshot",
    "build_verified_snapshot_from_files",
    "is_snapshot_current",
    "make_verified_snapshot",
    "production_snapshot",
    "read_verified_descriptor",
    "skill_descriptor",
    "validate_skill_name",
]
