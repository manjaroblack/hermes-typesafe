"""Bounded, deterministic skill-ranking helpers for the TypeSafe harness.

No function here discovers skills, reads the host filesystem, starts a worker,
or calls TypeSafe. Callers provide an immutable host-published snapshot and
already-normalized provider answers from the reviewed callback seam.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

try:
    from .questions import (
        SUGGESTION_EXCERPT_CHARS,
        RANK_CHOICE_INSTRUCTIONS,
        RANK_GATE_INSTRUCTIONS,
        RERANK_CHOICE_INSTRUCTIONS,
        RERANK_FIT_INSTRUCTION_TEMPLATE,
        SUGGESTION_FITS,
        SUGGESTION_GATE,
        SUGGESTION_HIT_CONTEXT_PREFIX,
        SUGGESTION_HIT_CONTEXT_SUFFIX,
        SUGGESTION_MISS_CONTEXT,
        SUGGESTION_RANK_CHOICE,
        SUGGESTION_RANK_GATE_QUESTIONS,
        SUGGESTION_SHORT_DESCRIPTION_CHARS,
        SUGGESTION_SHORTLIST,
        MAX_SUGGESTION_RANK_CRITERIA_BYTES,
    )
    from .limits import MAX_STRING_BYTES
    from .skills_adapter import SkillDescriptor, VerifiedSkillSnapshot, validate_skill_name
except ImportError:  # pragma: no cover - flat plugin import
    from questions import (
        SUGGESTION_EXCERPT_CHARS,
        RANK_CHOICE_INSTRUCTIONS,
        RANK_GATE_INSTRUCTIONS,
        RERANK_CHOICE_INSTRUCTIONS,
        RERANK_FIT_INSTRUCTION_TEMPLATE,
        SUGGESTION_FITS,
        SUGGESTION_GATE,
        SUGGESTION_HIT_CONTEXT_PREFIX,
        SUGGESTION_HIT_CONTEXT_SUFFIX,
        SUGGESTION_MISS_CONTEXT,
        SUGGESTION_RANK_CHOICE,
        SUGGESTION_RANK_GATE_QUESTIONS,
        SUGGESTION_SHORT_DESCRIPTION_CHARS,
        SUGGESTION_SHORTLIST,
        MAX_SUGGESTION_RANK_CRITERIA_BYTES,
    )
    from limits import MAX_STRING_BYTES
    from skills_adapter import SkillDescriptor, VerifiedSkillSnapshot, validate_skill_name

RANK_CHOICE = SUGGESTION_RANK_CHOICE
RANK_GATE_QUESTIONS = SUGGESTION_RANK_GATE_QUESTIONS
MISS_CONTEXT = SUGGESTION_MISS_CONTEXT
HIT_CONTEXT_PREFIX = SUGGESTION_HIT_CONTEXT_PREFIX
HIT_CONTEXT_SUFFIX = SUGGESTION_HIT_CONTEXT_SUFFIX
MAX_RANK_CRITERIA_BYTES = MAX_SUGGESTION_RANK_CRITERIA_BYTES


@dataclass(frozen=True, slots=True)
class _RankOutcome:
    valid: bool
    evaluated_miss: bool
    shortlist: tuple[SkillDescriptor, ...]


@dataclass(frozen=True, slots=True)
class _RerankOutcome:
    valid: bool
    evaluated_miss: bool
    winner: str | None


def _valid_snapshot(snapshot: Any) -> bool:
    return isinstance(snapshot, VerifiedSkillSnapshot)


def _answers(response: Any) -> dict[str, Any] | None:
    if type(response) is not dict:
        return None
    value = response.get("answers", response)
    return value if type(value) is dict else None


def _typed_answer(answers: Mapping[str, Any] | None, name: str, kind: str) -> dict[str, Any] | None:
    if answers is None:
        return None
    value = answers.get(name)
    if type(value) is not dict or value.get("type") != kind:
        return None
    return value


def _probability(value: Any) -> float | None:
    if type(value) not in (int, float) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        return None
    return number


def _question_descriptor(descriptor: SkillDescriptor, *, include_excerpt: bool) -> dict[str, str]:
    result = {"description": descriptor.description[:SUGGESTION_SHORT_DESCRIPTION_CHARS]}
    if include_excerpt:
        result["description"] = descriptor.description
        result["excerpt"] = descriptor.excerpt[:SUGGESTION_EXCERPT_CHARS]
    return result


def _snapshot_names(snapshot: VerifiedSkillSnapshot) -> set[str]:
    return {descriptor.name for descriptor in snapshot.skills}


def _valid_user_message(value: Any) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= MAX_STRING_BYTES


def build_rank_questions(snapshot: VerifiedSkillSnapshot) -> dict[str, dict[str, Any]]:
    """Create the cookbook-shaped first batch from verified bytes only."""

    if not _valid_snapshot(snapshot) or len(snapshot.skills) == 0:
        raise ValueError("a non-empty verified snapshot is required")
    criteria = {
        descriptor.name: _question_descriptor(descriptor, include_excerpt=False)
        for descriptor in snapshot.skills
    }
    criteria_bytes = json.dumps(criteria, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(criteria_bytes) > MAX_RANK_CRITERIA_BYTES:
        raise ValueError("rank criteria exceeds its bounded cap")
    return {
        RANK_CHOICE: {
            "type": "choice",
            "instructions": RANK_CHOICE_INSTRUCTIONS,
            "criteria": criteria,
        },
        "acts_on_user_system": {
            "type": "noul",
            "instructions": RANK_GATE_INSTRUCTIONS["acts_on_user_system"],
        },
        "would_follow_documented_procedure": {
            "type": "noul",
            "instructions": RANK_GATE_INSTRUCTIONS["would_follow_documented_procedure"],
        },
        "prose_suffices": {
            "type": "noul",
            "instructions": RANK_GATE_INSTRUCTIONS["prose_suffices"],
        },
    }


def build_rank_request(user_message: str, snapshot: VerifiedSkillSnapshot) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return the only state and questions a future rank RPC may receive."""

    if not _valid_user_message(user_message) or not _valid_snapshot(snapshot) or not snapshot.skills:
        raise ValueError("current message and non-empty verified snapshot are required")
    return user_message, build_rank_questions(snapshot)


def build_rerank_questions(
    snapshot: VerifiedSkillSnapshot,
    shortlist: Sequence[SkillDescriptor],
) -> dict[str, dict[str, Any]]:
    """Create the second Choice-plus-fit batch for one verified shortlist."""

    candidates = _validated_shortlist(snapshot, shortlist)
    if not candidates:
        raise ValueError("a non-empty shortlist is required")
    questions: dict[str, dict[str, Any]] = {
        RANK_CHOICE: {
            "type": "choice",
            "instructions": RERANK_CHOICE_INSTRUCTIONS,
            "criteria": {
                descriptor.name: _question_descriptor(descriptor, include_excerpt=True)
                for descriptor in candidates
            },
        }
    }
    for index, descriptor in enumerate(candidates):
        questions[f"fits_{index}"] = {
            "type": "noul",
            "instructions": RERANK_FIT_INSTRUCTION_TEMPLATE.format(skill_name=descriptor.name),
        }
    return questions


def build_rerank_request(
    user_message: str,
    snapshot: VerifiedSkillSnapshot,
    shortlist: Sequence[SkillDescriptor],
) -> tuple[str, dict[str, dict[str, Any]]]:
    if not _valid_user_message(user_message):
        raise ValueError("current message must be a bounded string")
    return user_message, build_rerank_questions(snapshot, shortlist)


def _validated_shortlist(
    snapshot: VerifiedSkillSnapshot,
    shortlist: Sequence[SkillDescriptor],
) -> tuple[SkillDescriptor, ...]:
    if not _valid_snapshot(snapshot) or type(shortlist) in (str, bytes, bytearray):
        return ()
    try:
        candidates = tuple(shortlist)
    except TypeError:
        return ()
    if not candidates or len(candidates) > SUGGESTION_SHORTLIST:
        return ()
    roster = _snapshot_names(snapshot)
    names: set[str] = set()
    for descriptor in candidates:
        if not isinstance(descriptor, SkillDescriptor) or descriptor.name not in roster or descriptor.name in names:
            return ()
        names.add(descriptor.name)
    return candidates


def _rank_outcome(snapshot: VerifiedSkillSnapshot, response: Any) -> _RankOutcome:
    if not _valid_snapshot(snapshot) or not snapshot.skills:
        return _RankOutcome(False, False, ())
    answers = _answers(response)
    if answers is None or set(answers) != {RANK_CHOICE, *RANK_GATE_QUESTIONS}:
        return _RankOutcome(False, False, ())
    choice = _typed_answer(answers, RANK_CHOICE, "choice")
    if choice is None or type(choice.get("choice")) is not str:
        return _RankOutcome(False, False, ())
    roster = _snapshot_names(snapshot)
    selected = choice["choice"]
    if selected not in roster:
        return _RankOutcome(False, False, ())
    probabilities = choice.get("probabilities")
    if type(probabilities) is not dict or not probabilities:
        return _RankOutcome(False, False, ())
    scores: dict[str, float] = {}
    for name, value in probabilities.items():
        if type(name) is not str or name not in roster:
            return _RankOutcome(False, False, ())
        number = _probability(value)
        if number is None:
            return _RankOutcome(False, False, ())
        scores[name] = number
    if selected not in scores or set(scores) != roster:
        return _RankOutcome(False, False, ())
    ordered = sorted(snapshot.skills, key=lambda descriptor: (-scores.get(descriptor.name, 0.0), descriptor.name))
    shortlist = tuple(ordered[: min(SUGGESTION_SHORTLIST, len(ordered))])
    gate_values: list[float] = []
    for name in RANK_GATE_QUESTIONS:
        answer = _typed_answer(answers, name, "noul")
        if answer is None:
            return _RankOutcome(False, False, ())
        value = _probability(answer.get("noul"))
        if value is None:
            return _RankOutcome(False, False, ())
        gate_values.append(1.0 - value if name == "prose_suffices" else value)
    evaluated_miss = sum(gate_values) / len(gate_values) < SUGGESTION_GATE
    return _RankOutcome(True, evaluated_miss, shortlist)


def rank_shortlist(snapshot: VerifiedSkillSnapshot, response: Any) -> tuple[SkillDescriptor, ...] | None:
    """Return a deterministic top-three shortlist, or ``None`` for invalid data."""

    outcome = _rank_outcome(snapshot, response)
    return outcome.shortlist if outcome.valid else None


def _rerank_outcome(
    snapshot: VerifiedSkillSnapshot,
    shortlist: Sequence[SkillDescriptor],
    response: Any,
) -> _RerankOutcome:
    candidates = _validated_shortlist(snapshot, shortlist)
    if not candidates:
        return _RerankOutcome(False, False, None)
    answers = _answers(response)
    choice = _typed_answer(answers, RANK_CHOICE, "choice")
    if choice is None or type(choice.get("choice")) is not str:
        return _RerankOutcome(False, False, None)
    winner = choice["choice"]
    names = {descriptor.name for descriptor in candidates}
    if winner not in names or answers is None:
        return _RerankOutcome(False, False, None)
    expected = {RANK_CHOICE, *(f"fits_{index}" for index in range(len(candidates)))}
    if set(answers) != expected:
        return _RerankOutcome(False, False, None)
    fits: list[float] = []
    for index in range(len(candidates)):
        answer = _typed_answer(answers, f"fits_{index}", "noul")
        if answer is None:
            return _RerankOutcome(False, False, None)
        value = _probability(answer.get("noul"))
        if value is None:
            return _RerankOutcome(False, False, None)
        fits.append(value)
    winner_index = next(index for index, descriptor in enumerate(candidates) if descriptor.name == winner)
    winner_fit = fits[winner_index]
    return _RerankOutcome(True, winner_fit < SUGGESTION_FITS, None if winner_fit < SUGGESTION_FITS else winner)


def rerank_winner(
    snapshot: VerifiedSkillSnapshot,
    shortlist: Sequence[SkillDescriptor],
    response: Any,
) -> str | None:
    """Return the second Choice winner, never the highest-fit candidate."""

    outcome = _rerank_outcome(snapshot, shortlist, response)
    return outcome.winner if outcome.valid else None


def format_hit(name: str) -> str:
    """Format one already roster-validated name into the exact ephemeral suffix."""

    if not validate_skill_name(name):
        raise ValueError("skill name is invalid")
    return f"{HIT_CONTEXT_PREFIX} {name}. {HIT_CONTEXT_SUFFIX}"


def evaluate_suggestion(
    user_message: str,
    snapshot: VerifiedSkillSnapshot,
    rank_response: Any,
    rerank_response: Any,
) -> str | None:
    """Evaluate two supplied responses without making a provider or host call."""

    if not _valid_user_message(user_message) or not _valid_snapshot(snapshot) or not snapshot.skills:
        return None
    rank = _rank_outcome(snapshot, rank_response)
    if not rank.valid:
        return None
    if rank.evaluated_miss:
        return MISS_CONTEXT
    rerank = _rerank_outcome(snapshot, rank.shortlist, rerank_response)
    if not rerank.valid:
        return None
    if rerank.evaluated_miss:
        return MISS_CONTEXT
    return format_hit(rerank.winner) if rerank.winner is not None else None


# Descriptive aliases used by fixture callers and future integration work.
rank_candidates = rank_shortlist
rerank_candidates = rerank_winner


__all__ = [
    "HIT_CONTEXT_PREFIX",
    "HIT_CONTEXT_SUFFIX",
    "MISS_CONTEXT",
    "RANK_CHOICE",
    "RANK_GATE_QUESTIONS",
    "build_rank_questions",
    "build_rank_request",
    "build_rerank_questions",
    "build_rerank_request",
    "evaluate_suggestion",
    "format_hit",
    "rank_candidates",
    "rank_shortlist",
    "rerank_candidates",
    "rerank_winner",
]
