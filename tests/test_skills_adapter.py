"""Contract tests for the held production adapter and verified fixtures."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

try:
    from skills_adapter import (
        HELD_UNSUPPORTED_HOST,
        HeldSkillsAdapter,
        build_verified_snapshot_from_files,
        is_snapshot_current,
        make_verified_snapshot,
        read_verified_descriptor,
        skill_descriptor,
    )
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe.skills_adapter import (
        HELD_UNSUPPORTED_HOST,
        HeldSkillsAdapter,
        build_verified_snapshot_from_files,
        is_snapshot_current,
        make_verified_snapshot,
        read_verified_descriptor,
        skill_descriptor,
    )


def test_current_host_adapter_is_inert_even_when_opted_in() -> None:
    calls: list[str] = []

    class ForbiddenProvider:
        def __getattr__(self, name: str) -> Any:
            calls.append(name)
            raise AssertionError(f"held adapter accessed provider seam: {name}")

    adapter = HeldSkillsAdapter(provider=ForbiddenProvider())
    assert adapter.status == HELD_UNSUPPORTED_HOST
    assert adapter.suggestion_context(user_message=object(), enabled=True, api_key=object()) is None
    assert adapter.snapshot(user_message=object(), enabled=True) is None
    assert adapter.register_hook(object()) is False
    assert calls == []


def test_verified_descriptor_reads_raw_skill_body_without_following_links(tmp_path: Path) -> None:
    root = tmp_path / "root"
    skill_dir = root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo procedure.\n---\n\n# Demo\n\nBody excerpt.",
        encoding="utf-8",
    )

    descriptor = read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo")
    assert descriptor is not None
    assert descriptor.name == "demo"
    assert descriptor.description == "Demo procedure."
    assert "Body excerpt." in descriptor.excerpt


def test_path_traversal_symlinks_nonregular_and_oversize_are_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "root"
    skill_dir = root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("---\nname: demo\ndescription: outside.\n---\noutside", encoding="utf-8")
    (skill_dir / "SKILL.md").symlink_to(outside)

    assert read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo") is None
    assert read_verified_descriptor(root, "../outside.md", expected_name="demo") is None

    regular = skill_dir / "regular.md"
    regular.write_text("---\nname: demo\ndescription: demo.\n---\nbody", encoding="utf-8")
    assert read_verified_descriptor(root, "skills/demo/regular.md", expected_name="demo") is None

    (skill_dir / "SKILL.md").unlink()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo.\n---\n" + "x" * 32_769,
        encoding="utf-8",
    )
    assert read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo") is None


def test_frontmatter_rejects_duplicate_keys_and_inline_execution(tmp_path: Path) -> None:
    root = tmp_path / "root"
    skill_dir = root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    marker = tmp_path / "executed"
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\nname: !!python/object/apply:os.system ['touch %s']\n"
        "description: demo.\n---\nbody" % marker,
        encoding="utf-8",
    )

    assert read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo") is None
    assert marker.exists() is False

    (skill_dir / "SKILL.md").write_text(
        '---\nname: demo\ndescription: "unterminated\n---\nbody',
        encoding="utf-8",
    )
    assert read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo") is None


def test_snapshot_requires_verified_unique_entries_and_never_falls_back_from_quarantine() -> None:
    descriptor = skill_descriptor("demo", "Demo.", "body")
    assert make_verified_snapshot([descriptor, descriptor], generation="g") is None
    assert make_verified_snapshot([descriptor], generation="g", quarantined={"demo"}) is None
    assert make_verified_snapshot([descriptor], generation=None) is None


def test_snapshot_generation_must_match_before_future_consumption() -> None:
    snapshot = make_verified_snapshot([skill_descriptor("demo", "Demo.", "body")], generation="g1")
    assert is_snapshot_current(snapshot, "g1") is True
    assert is_snapshot_current(snapshot, "g2") is False
    assert is_snapshot_current(None, "g1") is False


def test_snapshot_file_precedence_refuses_same_priority_collision(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for directory, text in (
        ("project", "Project."),
        ("profile", "Profile."),
    ):
        directory_path = root / directory
        directory_path.mkdir(parents=True)
        (directory_path / "SKILL.md").write_text(
            f"---\nname: demo\ndescription: {text}\n---\nbody",
            encoding="utf-8",
        )

    snapshot = build_verified_snapshot_from_files(
        root,
        [
            {"name": "demo", "relative_path": "project/SKILL.md", "priority": 0},
            {"name": "demo", "relative_path": "profile/SKILL.md", "priority": 0},
        ],
        generation="g",
    )
    assert snapshot is None


def test_snapshot_file_precedence_uses_project_winner(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for directory, text in (
        ("project", "Project."),
        ("profile", "Profile."),
    ):
        directory_path = root / directory
        directory_path.mkdir(parents=True)
        (directory_path / "SKILL.md").write_text(
            f"---\nname: demo\ndescription: {text}\n---\nbody",
            encoding="utf-8",
        )

    snapshot = build_verified_snapshot_from_files(
        root,
        [
            {"name": "demo", "relative_path": "project/SKILL.md", "priority": 0},
            {"name": "demo", "relative_path": "profile/SKILL.md", "priority": 1},
        ],
        generation="g",
    )
    assert snapshot is not None
    assert snapshot.skills[0].description == "Project."


def test_root_symlink_hardlink_and_fifo_are_not_descriptor_sources(tmp_path: Path) -> None:
    target_root = tmp_path / "target-root"
    skill_dir = target_root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    content = "---\nname: demo\ndescription: demo.\n---\nbody"
    source = tmp_path / "source.md"
    source.write_text(content, encoding="utf-8")

    root_link = tmp_path / "root-link"
    root_link.symlink_to(target_root, target_is_directory=True)
    assert read_verified_descriptor(root_link, "skills/demo/SKILL.md", expected_name="demo") is None

    hardlink = skill_dir / "SKILL.md"
    hardlink.hardlink_to(source)
    assert read_verified_descriptor(target_root, "skills/demo/SKILL.md", expected_name="demo") is None
    hardlink.unlink()

    fifo = skill_dir / "SKILL.md"
    os.mkfifo(fifo)
    assert read_verified_descriptor(target_root, "skills/demo/SKILL.md", expected_name="demo") is None


def test_path_swap_after_open_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    skill_dir = root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    target = skill_dir / "SKILL.md"
    target.write_text("---\nname: demo\ndescription: demo.\n---\nbody", encoding="utf-8")
    replacement = skill_dir / "replacement.md"
    replacement.write_text("---\nname: demo\ndescription: changed.\n---\nbody", encoding="utf-8")

    try:
        import skills_adapter
    except ModuleNotFoundError:  # installed-wheel test environment
        from hermes_typesafe import skills_adapter

    original_read = skills_adapter.os.read
    swapped = False

    def swap_after_first_read(fd: int, size: int) -> bytes:
        nonlocal swapped
        data = original_read(fd, size)
        if data and not swapped:
            swapped = True
            os.replace(replacement, target)
        return data

    monkeypatch.setattr(skills_adapter.os, "read", swap_after_first_read)
    assert read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo") is None


def test_descriptor_text_and_snapshot_caps_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    skill_dir = root / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: " + "x" * 513 + "\n---\nbody",
        encoding="utf-8",
    )
    assert read_verified_descriptor(root, "skills/demo/SKILL.md", expected_name="demo") is None

    descriptors = [skill_descriptor(f"skill-{index}", "x" * 512, "x" * 700) for index in range(128)]
    assert make_verified_snapshot(descriptors, generation="g") is not None
    assert make_verified_snapshot(descriptors + [skill_descriptor("overflow", "d")], generation="g") is None


def test_custom_descriptor_iterables_fail_closed_without_second_chance() -> None:
    class Poison:
        def __iter__(self) -> Any:
            raise AssertionError("untrusted iterable was inspected")

    assert make_verified_snapshot(Poison(), generation="g") is None
