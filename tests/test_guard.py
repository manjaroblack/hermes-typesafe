"""Pure synthetic guard helper contracts; live guard capability stays held."""

from __future__ import annotations

import math
from typing import Any

import pytest

try:
    import guard
    from questions import GUARD_CHECKS, GUARD_HIGH, GUARD_MEDIUM, GUARD_QUESTIONS
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe import guard
    from hermes_typesafe.questions import GUARD_CHECKS, GUARD_HIGH, GUARD_MEDIUM, GUARD_QUESTIONS


def answers(**scores: float) -> dict[str, Any]:
    return {
        "answers": {
            check: {"type": "noul", "noul": score}
            for check, score in scores.items()
        }
    }


def all_scores(value: float = 0.0) -> dict[str, Any]:
    return answers(**{check: value for check in GUARD_CHECKS})


def test_questions_are_the_single_guard_policy_home() -> None:
    assert GUARD_CHECKS == (
        "jailbreak_injection",
        "credential_exfiltration",
        "destructive_action",
    )
    assert GUARD_HIGH == 0.80
    assert GUARD_MEDIUM == 0.50
    assert tuple(GUARD_QUESTIONS) == GUARD_CHECKS
    assert all(set(GUARD_QUESTIONS[check]) == {"type", "instructions", "criteria"} for check in GUARD_CHECKS)


def test_highest_severity_wins_with_fixed_check_tie_order_and_static_message() -> None:
    sentinel = "tool-secret-sentinel"
    result = guard.classify_results(
        answers(
            destructive_action=0.99,
            credential_exfiltration=0.99,
            jailbreak_injection=0.99,
        ),
        tool_name="delete-record",
    )

    assert result.action == "block"
    assert result.severity == "high"
    assert result.check == "jailbreak_injection"
    assert result.rule_key is None
    assert sentinel not in result.message


def test_medium_boundary_is_approve_and_low_is_pass() -> None:
    medium = guard.classify_results(answers(credential_exfiltration=GUARD_MEDIUM), tool_name="send")
    low = guard.classify_results(all_scores(math.nextafter(GUARD_MEDIUM, 0.0)), tool_name="send")

    assert medium.action == "approve"
    assert medium.severity == "medium"
    assert medium.check == "credential_exfiltration"
    assert medium.rule_key is None
    assert low.action == "pass"
    assert low.severity == "low"


def test_valid_custom_thresholds_apply_without_moving_policy_home() -> None:
    medium = guard.classify_results(
        answers(credential_exfiltration=0.6),
        tool_name="send",
        medium=0.6,
        high=0.9,
    )
    high = guard.classify_results(
        answers(credential_exfiltration=0.9),
        tool_name="send",
        medium=0.6,
        high=0.9,
    )

    assert medium.action == "approve"
    assert medium.thresholds == (0.6, 0.9)
    assert high.action == "block"
    assert high.thresholds == (0.6, 0.9)


def test_invalid_thresholds_fall_back_to_central_defaults_without_raw_diagnostic() -> None:
    result = guard.classify_results(
        answers(jailbreak_injection=0.75),
        tool_name="send",
        medium=float("nan"),
        high=0.5,
    )

    assert result.action == "approve"
    assert result.thresholds == (GUARD_MEDIUM, GUARD_HIGH)
    assert result.diagnostic == "invalid_thresholds"
    assert "nan" not in result.message.lower()


@pytest.mark.parametrize("bad", [None, {}, {"answers": {}}, answers(jailbreak_injection=math.nan), answers(jailbreak_injection=1.1)])
def test_malformed_or_nonfinite_results_are_unavailable(bad: Any) -> None:
    result = guard.classify_results(bad, tool_name="send")

    assert result.action == "unavailable"
    assert result.severity == "unavailable"
    assert result.rule_key is None


def test_own_system_one_is_skipped_before_args_or_answer_validation() -> None:
    result = guard.evaluate_tool_arguments(
        tool_name="system_one",
        args=object(),
        results=object(),
        session_id=object(),
        tool_call_id=object(),
        plugin_instance_scope=object(),
    )

    assert result.action == "pass"
    assert result.reason == "own_tool"
    assert result.check is None


def test_medium_missing_identity_refuses_without_stable_rule_key_or_echo() -> None:
    sentinel = "credential-sentinel"
    result = guard.evaluate_tool_arguments(
        tool_name="send",
        args={"credential": sentinel},
        results=answers(credential_exfiltration=0.5),
        session_id=None,
        tool_call_id=None,
        plugin_instance_scope=guard.new_plugin_instance_scope(),
    )

    assert result.action == "block"
    assert result.reason == "identity_required"
    assert result.rule_key is None
    assert sentinel not in result.message


def test_rule_key_uses_canonical_validated_args_and_opaque_instance_scope() -> None:
    scope = "01" * 32
    first = guard.make_rule_key(
        scope,
        check="credential_exfiltration",
        tool_name="send",
        session_id="session-1",
        tool_call_id="call-1",
        args={"b": 2, "a": [True, "x"]},
    )
    reordered = guard.make_rule_key(
        scope,
        check="credential_exfiltration",
        tool_name="send",
        session_id="session-1",
        tool_call_id="call-1",
        args={"a": [True, "x"], "b": 2},
    )
    changed_call = guard.make_rule_key(
        scope,
        check="credential_exfiltration",
        tool_name="send",
        session_id="session-1",
        tool_call_id="call-2",
        args={"b": 2, "a": [True, "x"]},
    )

    assert first == reordered
    assert first.startswith("typesafe.guardrails.v3.credential_exfiltration.")
    assert len(first.rsplit(".", 1)[1]) == 64
    assert changed_call != first
    assert "session-1" not in first
    assert "call-1" not in first


def test_medium_tool_result_binds_rule_key_only_after_full_identity_validation() -> None:
    result = guard.evaluate_tool_arguments(
        tool_name="send",
        args={"recipient": "example"},
        results=answers(credential_exfiltration=0.5),
        session_id="session-1",
        tool_call_id="call-1",
        plugin_instance_scope="02" * 32,
    )

    assert result.action == "approve"
    assert result.rule_key is not None
    assert result.rule_key.startswith("typesafe.guardrails.v3.credential_exfiltration.")


def test_final_representation_is_static_for_high_warning_for_medium_and_unchanged_for_low() -> None:
    original = "assistant response with sentinel"
    high = guard.represent_final_text(original, all_scores(0.8))
    medium = guard.represent_final_text(original, answers(destructive_action=0.5))
    low = guard.represent_final_text(original, all_scores(0.1))

    assert high.action == "replace"
    assert high.text != original
    assert high.text == guard.STATIC_SAFE_FINAL_REPLACEMENT
    assert "sentinel" not in high.text
    assert medium.action == "warn"
    assert medium.text.startswith(guard.FINAL_WARNING_PREFIX)
    assert medium.text.endswith(original)
    assert low.action == "pass"
    assert low.text == original


def test_final_invalid_result_does_not_claim_a_safe_or_blocking_verdict() -> None:
    result = guard.represent_final_text("unchanged", answers(jailbreak_injection=math.inf))

    assert result.action == "unavailable"
    assert result.text == "Safety screen unavailable; response not verified.\nunchanged"


def test_plugin_instance_scope_is_32_random_bytes_encoded_as_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard.secrets, "token_bytes", lambda size: b"q" * size)

    scope = guard.new_plugin_instance_scope()

    assert scope == (b"q" * 32).hex()
    assert len(scope) == 64
    assert set(scope) <= set("0123456789abcdef")
