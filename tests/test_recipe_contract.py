"""Offline recipe schema contracts."""

from __future__ import annotations

try:
    from questions import recipe_definitions, recipe_examples, validate_recipe_definitions, validate_recipe_examples
except ModuleNotFoundError:
    from hermes_typesafe.questions import recipe_definitions, recipe_examples, validate_recipe_definitions, validate_recipe_examples


def test_bundled_recipe_definitions_and_examples_validate_offline() -> None:
    definitions = recipe_definitions()
    examples = recipe_examples()
    assert len(definitions) == 7
    assert validate_recipe_definitions(definitions)
    assert validate_recipe_examples(examples)
    assert {example["outcome"] for example in examples} >= {"uncertain", "unavailable", "needs_input"}


def test_recipe_examples_are_detached_and_tamper_rejected() -> None:
    examples = recipe_examples()
    examples[0]["state"]["action"] = "changed"
    assert recipe_examples()[0]["state"]["action"] == "bounded"
    assert not validate_recipe_examples(tuple({**example, "name": "unknown"} if index == 0 else example for index, example in enumerate(recipe_examples())))
