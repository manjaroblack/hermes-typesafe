"""Contract tests for inert suggestion helpers and synthetic ranking."""

from __future__ import annotations

from typing import Any

import pytest

try:
    from skills_adapter import make_verified_snapshot, skill_descriptor
    from suggest import (
        MISS_CONTEXT,
        HIT_CONTEXT_PREFIX,
        build_rank_questions,
        build_rank_request,
        build_rerank_request,
        evaluate_suggestion,
        rank_shortlist,
        rerank_winner,
    )
except ModuleNotFoundError:  # installed-wheel test environment
    from hermes_typesafe.skills_adapter import make_verified_snapshot, skill_descriptor
    from hermes_typesafe.suggest import (
        MISS_CONTEXT,
        HIT_CONTEXT_PREFIX,
        build_rank_questions,
        build_rank_request,
        build_rerank_request,
        evaluate_suggestion,
        rank_shortlist,
        rerank_winner,
    )


def snapshot() -> Any:
    return make_verified_snapshot(
        [
            skill_descriptor("alpha", "Alpha procedure", "alpha excerpt"),
            skill_descriptor("beta", "Beta procedure", "beta excerpt"),
            skill_descriptor("typesafe:system-one", "Typed decisions", "system excerpt"),
            skill_descriptor("gamma", "Gamma procedure", "gamma excerpt"),
        ],
        generation="fixture-generation-1",
    )


def rank_response(*, gate: float = 0.8, probabilities: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "answers": {
            "skill": {
                "type": "choice",
                "choice": "beta",
                "probabilities": probabilities
                or {
                    "alpha": 0.5,
                    "beta": 0.7,
                    "typesafe:system-one": 0.7,
                    "gamma": 0.2,
                },
            },
            "acts_on_user_system": {"type": "noul", "noul": gate},
            "would_follow_documented_procedure": {"type": "noul", "noul": gate},
            "prose_suffices": {"type": "noul", "noul": 0.0},
        }
    }


def test_rank_request_uses_only_current_message_and_verified_descriptor_content() -> None:
    state, questions = build_rank_request("current user message", snapshot())

    assert state == "current user message"
    assert set(questions) == {
        "skill",
        "acts_on_user_system",
        "would_follow_documented_procedure",
        "prose_suffices",
    }
    assert questions["skill"]["criteria"]["alpha"] == {
        "description": "Alpha procedure",
        "excerpt": "alpha excerpt",
    }


def test_rank_shortlist_orders_probability_then_name_and_limits_to_three() -> None:
    shortlisted = rank_shortlist(snapshot(), rank_response())

    assert [entry.name for entry in shortlisted] == [
        "beta",
        "typesafe:system-one",
        "alpha",
    ]


def test_gate_rejection_is_an_evaluated_miss_at_the_exact_boundary() -> None:
    assert rank_shortlist(snapshot(), rank_response(gate=0.30))
    rejected = rank_response(gate=0.0)
    rejected["answers"]["prose_suffices"]["noul"] = 1.0
    assert evaluate_suggestion(
        "message",
        snapshot(),
        rejected,
        None,
    ) == MISS_CONTEXT


def test_rerank_winner_is_second_choice_not_highest_fit() -> None:
    shortlist = rank_shortlist(snapshot(), rank_response())
    _, questions = build_rerank_request("message", snapshot(), shortlist)
    assert list(questions["skill"]["criteria"]) == [entry.name for entry in shortlist]

    response = {
        "answers": {
            "skill": {"type": "choice", "choice": "beta"},
            "fits_0": {"type": "noul", "noul": 0.95},
            "fits_1": {"type": "noul", "noul": 0.8},
            "fits_2": {"type": "noul", "noul": 0.8},
        }
    }
    assert rerank_winner(snapshot(), shortlist, response) == "beta"
    assert evaluate_suggestion("message", snapshot(), rank_response(), response) == (
        f"{HIT_CONTEXT_PREFIX} beta. Ignore this if it does not fit what the user actually asked for."
    )


def test_invalid_or_stale_names_fail_closed_without_a_miss_claim() -> None:
    stale = rank_response(probabilities={"not-in-roster": 1.0})
    assert rank_shortlist(snapshot(), stale) is None
    assert evaluate_suggestion("message", snapshot(), stale, None) is None

    shortlist = rank_shortlist(snapshot(), rank_response())
    stale_rerank = {
        "answers": {
            "skill": {"type": "choice", "choice": "not-in-shortlist"},
            "fits_0": {"type": "noul", "noul": 0.9},
            "fits_1": {"type": "noul", "noul": 0.9},
            "fits_2": {"type": "noul", "noul": 0.9},
        }
    }
    assert rerank_winner(snapshot(), shortlist, stale_rerank) is None


@pytest.mark.parametrize("response", [None, {}, {"answers": {}}])
def test_provider_failure_or_malformed_response_is_unavailable(response: Any) -> None:
    assert evaluate_suggestion("message", snapshot(), response, None) is None


def test_empty_snapshot_is_unavailable_not_an_evaluated_miss() -> None:
    empty = make_verified_snapshot([], generation="empty")
    assert evaluate_suggestion("message", empty, rank_response(), None) is None


def test_rank_criteria_aggregate_cap_is_checked_before_request_build() -> None:
    descriptors = [skill_descriptor(f"skill-{index}", "d" * 512, "e" * 700) for index in range(128)]
    bounded = make_verified_snapshot(descriptors, generation="g")
    assert bounded is not None
    with pytest.raises(ValueError):
        build_rank_questions(bounded)
