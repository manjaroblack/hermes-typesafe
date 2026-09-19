"""Contract tests for the bundled TypeSafe skill."""

from __future__ import annotations

from conftest import ROOT


SKILL_PATH = ROOT / "skills" / "typesafe-system-one" / "SKILL.md"


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines and lines[0] == "---"
    end = lines.index("---", 1)
    values: dict[str, str] = {}
    for line in lines[1:end]:
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def test_bundled_skill_has_compact_authoring_contract() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    description = frontmatter["description"]

    assert len(description) <= 57
    assert description.endswith(".")
    assert frontmatter["name"] == "typesafe-system-one"
    for section in ("When to Use", "Prerequisites", "Procedure", "Pitfalls", "Verification"):
        assert f"## {section}" in text


def test_bundled_skill_documents_held_scope_and_pinned_contract() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")

    for marker in (
        "noul",
        "choice",
        "score",
        "jev-1.13.0",
        "TYPESAFE_API_KEY",
        "retry",
        "2 seconds",
        "HELD_UNSUPPORTED_HOST",
        "not catalog-eligible",
        "hermes-typesafe",
    ):
        assert marker in text


def test_bundled_skill_is_packaged_as_plugin_data() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "skills/typesafe-system-one/SKILL.md" in pyproject
