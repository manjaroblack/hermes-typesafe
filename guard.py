"""Pure synthetic guardrail helpers.

This module is side-effect free: the reviewed host integration in ``harness.py``
owns callbacks, runtime admission, and native approval; these helpers only
validate bounded data and classify detached answers.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

try:  # Native source checkout and installed wheel both use this module.
    from .limits import (
        MAX_STATE_BYTES,
        MAX_STRING_BYTES,
        LimitsError,
        _validate_and_encode,
    )
    from .questions import (
        GUARD_CHECKS,
        GUARD_FINAL_WARNING_PREFIX,
        GUARD_HIGH,
        GUARD_MAX,
        GUARD_MIN,
        GUARD_MESSAGES,
        GUARD_MEDIUM,
        GUARD_OWN_TOOL_NAME,
        MAX_GUARD_IDENTIFIER_BYTES,
        MAX_GUARD_SCOPE_BYTES,
        GUARD_RULE_PREFIX,
        GUARD_RULE_VERSION,
        GUARD_QUESTIONS,
        GUARD_STATIC_SAFE_FINAL_REPLACEMENT,
        GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX,
        FINAL_GUARD_QUESTIONS,
        SENSITIVE_ARGUMENT_KEYS,
        resolve_guard_thresholds,
    )
except ImportError:  # pragma: no cover - flat source collection
    from limits import MAX_STATE_BYTES, MAX_STRING_BYTES, LimitsError, _validate_and_encode
    from questions import (
        GUARD_CHECKS,
        GUARD_FINAL_WARNING_PREFIX,
        GUARD_HIGH,
        GUARD_MAX,
        GUARD_MIN,
        GUARD_MESSAGES,
        GUARD_MEDIUM,
        GUARD_OWN_TOOL_NAME,
        MAX_GUARD_IDENTIFIER_BYTES,
        MAX_GUARD_SCOPE_BYTES,
        GUARD_RULE_PREFIX,
        GUARD_RULE_VERSION,
        GUARD_QUESTIONS,
        GUARD_STATIC_SAFE_FINAL_REPLACEMENT,
        GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX,
        FINAL_GUARD_QUESTIONS,
        SENSITIVE_ARGUMENT_KEYS,
        resolve_guard_thresholds,
    )


_SCOPE_BYTES = MAX_GUARD_SCOPE_BYTES
_ID_BYTES = MAX_GUARD_IDENTIFIER_BYTES
_OWN_TOOL = GUARD_OWN_TOOL_NAME
_RULE_VERSION = GUARD_RULE_VERSION
_RULE_PREFIX = GUARD_RULE_PREFIX

STATIC_SAFE_FINAL_REPLACEMENT = GUARD_STATIC_SAFE_FINAL_REPLACEMENT
FINAL_WARNING_PREFIX = GUARD_FINAL_WARNING_PREFIX


class GuardInputError(ValueError):
    """Sanitized helper refusal; the code never contains caller data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class GuardAssessment:
    """Detached synthetic classification with no raw args or call identity."""

    action: str
    severity: str
    check: str | None
    score: float | None
    message: str
    rule_key: str | None = None
    reason: str | None = None
    thresholds: tuple[float, float] = (GUARD_MEDIUM, GUARD_HIGH)
    diagnostic: str | None = None

    @property
    def available(self) -> bool:
        return self.action != "unavailable"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action": self.action,
            "severity": self.severity,
            "check": self.check,
            "score": self.score,
            "message": self.message,
            "rule_key": self.rule_key,
            "reason": self.reason,
            "thresholds": self.thresholds,
        }
        if self.diagnostic is not None:
            result["diagnostic"] = self.diagnostic
        return result

    def __getitem__(self, key: str) -> Any:
        """Permit dict-style inspection without storing a second mutable result."""

        return self.as_dict()[key]


@dataclass(frozen=True)
class FinalRepresentation:
    """Static final-text representation; no streaming or host hook is implied."""

    action: str
    text: str
    severity: str
    check: str | None = None
    reason: str | None = None
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action": self.action,
            "text": self.text,
            "severity": self.severity,
            "check": self.check,
            "reason": self.reason,
        }
        if self.diagnostic is not None:
            result["diagnostic"] = self.diagnostic
        return result

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


def new_plugin_instance_scope() -> str:
    """Create one 256-bit registration scope; never substitute weak entropy."""

    try:
        raw = secrets.token_bytes(_SCOPE_BYTES)
    except Exception:
        raise GuardInputError("scope_unavailable") from None
    if type(raw) is not bytes or len(raw) != _SCOPE_BYTES:
        raise GuardInputError("scope_unavailable")
    return raw.hex()


def validate_plugin_instance_scope(scope: Any) -> str:
    """Validate and canonicalize the opaque per-registration scope."""

    if type(scope) is not str or len(scope) != _SCOPE_BYTES * 2:
        raise GuardInputError("scope_invalid")
    try:
        decoded = bytes.fromhex(scope)
    except (ValueError, TypeError):
        raise GuardInputError("scope_invalid") from None
    if len(decoded) != _SCOPE_BYTES or scope.lower() != scope.casefold():
        raise GuardInputError("scope_invalid")
    return scope.lower()


def _validate_identifier(value: Any, code: str) -> str:
    if type(value) is not str or not value:
        raise GuardInputError(code)
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise GuardInputError(code) from None
    if len(encoded) > _ID_BYTES or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise GuardInputError(code)
    return value


def _validate_args(args: Any) -> bytes:
    """Return canonical bounded bytes for an exact JSON object only."""

    if not isinstance(args, Mapping):
        raise GuardInputError("args_invalid")
    try:
        return _validate_and_encode(_detach_json(args), cap=MAX_STATE_BYTES, code="payload_too_large")
    except LimitsError as error:
        del error
        raise GuardInputError("args_invalid") from None


def _detach_json(value: Any) -> Any:
    """Copy host-frozen JSON projections into the bounded native JSON types."""

    if isinstance(value, Mapping):
        return {key: _detach_json(item) for key, item in value.items()}
    if type(value) is list:
        return [_detach_json(item) for item in value]
    if type(value) is tuple:
        return [_detach_json(item) for item in value]
    return value


def contains_sensitive_argument_key(args: Any) -> bool:
    """Detect only sensitive mapping keys; arbitrary string values are not scanned."""

    if not isinstance(args, Mapping):
        return False
    try:
        for key, value in args.items():
            if type(key) is str and key.casefold() in SENSITIVE_ARGUMENT_KEYS:
                return True
            if isinstance(value, Mapping) and contains_sensitive_argument_key(value):
                return True
            if type(value) in (list, tuple) and any(contains_sensitive_argument_key(item) for item in value):
                return True
    except Exception:
        return True
    return False


def build_tool_guard_request(tool_name: Any, args: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]] | None:
    """Build the exact proposed tool I/O batch, or ``None`` for the plugin's own tool."""

    if type(tool_name) is not str or not tool_name or tool_name == _OWN_TOOL:
        return None
    _validate_identifier(tool_name, "tool_name_invalid")
    if contains_sensitive_argument_key(args):
        raise GuardInputError("sensitive_argument")
    checked_args = _detach_json(args)
    _validate_args(checked_args)
    return {"tool_name": tool_name, "args": checked_args}, deepcopy(GUARD_QUESTIONS)


def _validate_check(check: Any) -> str:
    if type(check) is not str or check not in GUARD_CHECKS:
        raise GuardInputError("check_invalid")
    return check


def make_rule_key(
    plugin_instance_scope: Any,
    check: Any,
    tool_name: Any,
    session_id: Any,
    tool_call_id: Any,
    args: Any,
) -> str:
    """Bind a medium synthetic result to exact bounded args and one call.

    The returned digest contains no raw args, session ID, or tool-call ID.  It
    is a local helper key, not a Hermes approval directive.
    """

    scope = validate_plugin_instance_scope(plugin_instance_scope)
    checked = _validate_check(check)
    tool = _validate_identifier(tool_name, "tool_name_invalid")
    session = _validate_identifier(session_id, "session_id_invalid")
    call = _validate_identifier(tool_call_id, "tool_call_id_invalid")
    canonical_args = _validate_args(args)
    args_digest = hashlib.sha256(canonical_args).hexdigest()
    payload = [
        _RULE_VERSION,
        scope,
        checked,
        tool,
        session,
        call,
        args_digest,
    ]
    try:
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, UnicodeError, ValueError):
        raise GuardInputError("rule_key_unavailable") from None
    return f"{_RULE_PREFIX}{checked}.{hashlib.sha256(canonical_payload).hexdigest()}"


def _normalise_results(results: Any) -> tuple[list[tuple[str, float]] | None, bool]:
    """Read only known answer fields and validate every known supplied score."""

    if type(results) is not dict:
        return None, False
    raw_answers: Any = results
    if "answers" in results:
        raw_answers = results["answers"]
    if type(raw_answers) is not dict:
        return None, False

    values: list[tuple[str, float]] = []
    invalid = False
    for check in GUARD_CHECKS:
        if check not in raw_answers:
            continue
        raw = raw_answers[check]
        if type(raw) is dict:
            if raw.get("type") != "noul" or "noul" not in raw:
                invalid = True
                continue
            raw = raw["noul"]
        if type(raw) not in (int, float) or type(raw) is bool:
            invalid = True
            continue
        if not math.isfinite(raw) or raw < GUARD_MIN or raw > GUARD_MAX:
            invalid = True
            continue
        values.append((check, float(raw)))
    if invalid or not values:
        return None, False
    return values, True


def _selected(values: list[tuple[str, float]], *, minimum: float) -> tuple[str, float] | None:
    candidates = [(check, score) for check, score in values if score >= minimum]
    if not candidates:
        return None
    best_score = max(score for _, score in candidates)
    for check in GUARD_CHECKS:
        for candidate_check, score in candidates:
            if candidate_check == check and score == best_score:
                return candidate_check, score
    return None


def _assessment(
    *,
    action: str,
    severity: str,
    check: str | None,
    score: float | None,
    thresholds: tuple[float, float],
    reason: str | None = None,
    diagnostic: str | None = None,
    message_key: str | None = None,
    rule_key: str | None = None,
) -> GuardAssessment:
    return GuardAssessment(
        action=action,
        severity=severity,
        check=check,
        score=score,
        message=GUARD_MESSAGES[message_key or severity],
        rule_key=rule_key,
        reason=reason,
        thresholds=thresholds,
        diagnostic=diagnostic,
    )


def classify_results(
    results: Any,
    *,
    tool_name: Any = None,
    medium: Any = GUARD_MEDIUM,
    high: Any = GUARD_HIGH,
    questions: Mapping[str, Any] = GUARD_QUESTIONS,
) -> GuardAssessment:
    """Classify explicit synthetic answers without contacting any service."""

    del tool_name, questions
    thresholds, valid_thresholds = resolve_guard_thresholds(medium=medium, high=high)
    diagnostic = None if valid_thresholds else "invalid_thresholds"
    values, valid_results = _normalise_results(results)
    if not valid_results or values is None:
        return _assessment(
            action="unavailable",
            severity="unavailable",
            check=None,
            score=None,
            thresholds=thresholds,
            reason="invalid_results",
            diagnostic=diagnostic or "invalid_results",
        )

    medium_threshold, high_threshold = thresholds
    selected = _selected(values, minimum=high_threshold)
    if selected is not None:
        return _assessment(
            action="block",
            severity="high",
            check=selected[0],
            score=selected[1],
            thresholds=thresholds,
            diagnostic=diagnostic,
        )
    selected = _selected(values, minimum=medium_threshold)
    if selected is not None:
        return _assessment(
            action="approve",
            severity="medium",
            check=selected[0],
            score=selected[1],
            thresholds=thresholds,
            diagnostic=diagnostic,
        )
    return _assessment(
        action="pass",
        severity="low",
        check=None,
        score=max(score for _, score in values),
        thresholds=thresholds,
        diagnostic=diagnostic,
    )


def evaluate_tool_arguments(
    tool_name: Any,
    args: Any,
    results: Any,
    *,
    session_id: Any = None,
    tool_call_id: Any = None,
    plugin_instance_scope: Any = None,
    medium: Any = GUARD_MEDIUM,
    high: Any = GUARD_HIGH,
) -> GuardAssessment:
    """Evaluate a synthetic tool result and bind only medium results to a key."""

    if type(tool_name) is str and tool_name == _OWN_TOOL:
        return _assessment(
            action="pass",
            severity="low",
            check=None,
            score=None,
            thresholds=(GUARD_MEDIUM, GUARD_HIGH),
            reason="own_tool",
            message_key="own_tool",
        )

    assessment = classify_results(results, tool_name=tool_name, medium=medium, high=high)
    if assessment.action != "approve":
        return assessment
    try:
        rule_key = make_rule_key(
            plugin_instance_scope,
            assessment.check,
            tool_name,
            session_id,
            tool_call_id,
            args,
        )
    except GuardInputError:
        return _assessment(
            action="block",
            severity="medium",
            check=assessment.check,
            score=assessment.score,
            thresholds=assessment.thresholds,
            reason="identity_required",
            diagnostic=assessment.diagnostic,
            message_key="identity_required",
        )
    return GuardAssessment(
        action=assessment.action,
        severity=assessment.severity,
        check=assessment.check,
        score=assessment.score,
        message=assessment.message,
        rule_key=rule_key,
        reason=assessment.reason,
        thresholds=assessment.thresholds,
        diagnostic=assessment.diagnostic,
    )


def _validate_final_text(response_text: Any) -> str:
    if type(response_text) is not str:
        raise GuardInputError("response_text_invalid")
    try:
        size = len(response_text.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise GuardInputError("response_text_invalid") from None
    if size > MAX_STRING_BYTES:
        raise GuardInputError("response_text_invalid")
    return response_text


def represent_final_text(
    response_text: Any,
    results: Any,
    *,
    medium: Any = GUARD_MEDIUM,
    high: Any = GUARD_HIGH,
) -> FinalRepresentation:
    """Return a static synthetic replacement/warning representation only."""

    try:
        text = _validate_final_text(response_text)
    except GuardInputError:
        return FinalRepresentation(
            action="unavailable",
            text=GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX,
            severity="unavailable",
            reason="invalid_response",
        )

    assessment = classify_results(results, medium=medium, high=high, questions=FINAL_GUARD_QUESTIONS)
    if assessment.action == "block":
        return FinalRepresentation(
            action="replace",
            text=STATIC_SAFE_FINAL_REPLACEMENT,
            severity=assessment.severity,
            check=assessment.check,
            diagnostic=assessment.diagnostic,
        )
    if assessment.action == "approve":
        return FinalRepresentation(
            action="warn",
            text=f"{FINAL_WARNING_PREFIX}{text}",
            severity=assessment.severity,
            check=assessment.check,
            diagnostic=assessment.diagnostic,
        )
    if assessment.action == "pass":
        return FinalRepresentation(
            action="pass",
            text=text,
            severity=assessment.severity,
            check=assessment.check,
            diagnostic=assessment.diagnostic,
        )
    return FinalRepresentation(
        action="unavailable",
        text=f"{GUARD_STATIC_UNAVAILABLE_FINAL_PREFIX}\n{text}",
        severity=assessment.severity,
        check=assessment.check,
        reason=assessment.reason,
        diagnostic=assessment.diagnostic,
    )


# Descriptive aliases keep the pure contract discoverable without introducing
# another implementation or a host-facing callback.
classify_guard_results = classify_results
screen_tool_arguments = evaluate_tool_arguments
represent_final_response = represent_final_text
build_rule_key = make_rule_key
new_scope = new_plugin_instance_scope


__all__ = [
    "FINAL_WARNING_PREFIX",
    "GUARD_QUESTIONS",
    "GuardAssessment",
    "GuardInputError",
    "FinalRepresentation",
    "STATIC_SAFE_FINAL_REPLACEMENT",
    "build_rule_key",
    "build_tool_guard_request",
    "classify_guard_results",
    "classify_results",
    "contains_sensitive_argument_key",
    "evaluate_tool_arguments",
    "make_rule_key",
    "new_plugin_instance_scope",
    "new_scope",
    "represent_final_response",
    "represent_final_text",
    "screen_tool_arguments",
    "validate_plugin_instance_scope",
]
