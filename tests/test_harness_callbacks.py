"""Live callback contracts exercised with deterministic local runtimes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

try:
    from harness import (
        GUARD_STATIC_TOOL_BLOCK,
        make_combined_pre_llm_handler,
        make_final_guard_handler,
        make_pre_tool_guard_handler,
    )
    from questions import HARNESS_CAPABILITIES
    from skills_adapter import host_snapshot_to_verified
except ModuleNotFoundError:
    from hermes_typesafe.harness import (
        GUARD_STATIC_TOOL_BLOCK,
        make_combined_pre_llm_handler,
        make_final_guard_handler,
        make_pre_tool_guard_handler,
    )
    from hermes_typesafe.questions import HARNESS_CAPABILITIES
    from hermes_typesafe.skills_adapter import host_snapshot_to_verified


POOL = {
    "cheap": {"model": "jev-cheap", "provider": "typesafe"},
    "coding": {"model": "jev-coding", "provider": "typesafe"},
}


def route_result() -> dict[str, Any]:
    return {
        "answers": {
            "target_model": {"type": "choice", "choice": "coding", "confidence": 0.9},
            "current_model_mismatch": {"type": "noul", "noul": 0.9},
            "worth_breaking_cache": {"type": "noul", "noul": 0.9},
            "difficulty": {
                "type": "score",
                "score": 2.0,
                "legend": {0: "routine", 1: "moderate", 2: "difficult", 3: "expert"},
            },
        }
    }


def rank_result() -> dict[str, Any]:
    return {
        "answers": {
            "skill": {
                "type": "choice",
                "choice": "beta",
                "probabilities": {"alpha": 0.5, "beta": 0.8, "gamma": 0.2},
            },
            "acts_on_user_system": {"type": "noul", "noul": 0.8},
            "would_follow_documented_procedure": {"type": "noul", "noul": 0.8},
            "prose_suffices": {"type": "noul", "noul": 0.0},
        }
    }


def rerank_result() -> dict[str, Any]:
    return {
        "answers": {
            "skill": {"type": "choice", "choice": "beta"},
            "fits_0": {"type": "noul", "noul": 0.9},
            "fits_1": {"type": "noul", "noul": 0.8},
            "fits_2": {"type": "noul", "noul": 0.8},
        }
    }


def host_snapshot(generation: str = "g-1") -> Any:
    return SimpleNamespace(
        generation=generation,
        entries=(
            SimpleNamespace(name="alpha", description="Alpha", excerpt="Alpha excerpt"),
            SimpleNamespace(name="beta", description="Beta", excerpt="Beta excerpt"),
            SimpleNamespace(name="gamma", description="Gamma", excerpt="Gamma excerpt"),
        ),
    )


class FakeRuntime:
    def __init__(self, *results: Any, error: BaseException | None = None) -> None:
        self.results = list(results)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def execute_sync(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.results.pop(0)


def enabled_settings(**overrides: Any) -> dict[str, Any]:
    settings = {
        "model": "jev-1.13.0",
        "routing.enabled": True,
        "routing.mode": "first_turn",
        "routing.models": POOL,
        "suggestion.enabled": True,
        "guardrails.enabled": True,
    }
    settings.update(overrides)
    return settings


def test_combined_pre_llm_callback_is_bounded_and_returns_host_directive_and_context() -> None:
    runtime = FakeRuntime(route_result(), rank_result(), rerank_result())
    handler = make_combined_pre_llm_handler(
        enabled_settings(),
        runtime=runtime,
        snapshot_reader=host_snapshot,
        secret_reader=lambda: "scoped-key",
        require_home_identity=False,
    )

    result = handler(
        user_message="Use the documented beta procedure",
        is_first_turn=True,
        model="jev-cheap",
        provider="typesafe",
    )

    assert result == {
        "model_switch": {
            "model": "jev-coding",
            "provider": "typesafe",
            "allow_cache_break": False,
        },
        "context": "Relevant to the current request: beta. Ignore this if it does not fit what the user actually asked for.",
    }
    assert len(runtime.calls) == 3
    assert runtime.calls[0]["state"] == {
        "user_message": "Use the documented beta procedure",
        "current_label": "cheap",
    }
    assert runtime.calls[1]["state"] == "Use the documented beta procedure"
    assert runtime.calls[2]["state"] == "Use the documented beta procedure"
    assert all(call["model"] == "jev-1.13.0" for call in runtime.calls)
    assert all(call["timeout"] <= 1.8 for call in runtime.calls)
    assert "history" not in runtime.calls[0]["state"]


def test_generation_change_between_rank_and_rerank_discards_context() -> None:
    runtime = FakeRuntime(rank_result(), rerank_result())
    snapshots = iter((host_snapshot("g-1"), host_snapshot("g-2")))
    handler = make_combined_pre_llm_handler(
        enabled_settings(**{"routing.enabled": False}),
        runtime=runtime,
        snapshot_reader=lambda: next(snapshots),
        secret_reader=lambda: "scoped-key",
        require_home_identity=False,
    )

    assert handler(user_message="request", is_first_turn=True, model="jev-1.13.0", provider="typesafe") is None
    assert len(runtime.calls) == 1


def test_guard_blocks_sensitive_keys_before_runtime_and_skips_own_tool() -> None:
    runtime = FakeRuntime({})
    handler = make_pre_tool_guard_handler(
        enabled_settings(),
        runtime=runtime,
        secret_reader=lambda: "scoped-key",
        require_home_identity=False,
        plugin_instance_scope="01" * 32,
    )

    sensitive = handler(
        tool_name="send",
        args={"PaSsWoRd": "do-not-upload"},
        session_id="session",
        tool_call_id="call",
    )
    assert sensitive is not None and sensitive["action"] == "block"
    assert runtime.calls == []
    assert sensitive is not None and "do-not-upload" not in sensitive["message"]
    assert handler(tool_name="system_one", args=object()) is None
    assert runtime.calls == []


def test_guard_failure_blocks_and_final_failure_marks_original_unavailable() -> None:
    failing = FakeRuntime(error=RuntimeError("provider failure"))
    guard_handler = make_pre_tool_guard_handler(
        enabled_settings(),
        runtime=failing,
        secret_reader=lambda: "scoped-key",
        require_home_identity=False,
        plugin_instance_scope="02" * 32,
    )
    blocked = guard_handler(
        tool_name="send",
        args={"recipient": "example"},
        session_id="session",
        tool_call_id="call",
    )
    assert blocked == {"action": "block", "message": GUARD_STATIC_TOOL_BLOCK}
    assert len(failing.calls) == 1

    final = make_final_guard_handler(
        enabled_settings(),
        runtime=FakeRuntime(error=RuntimeError("provider failure")),
        secret_reader=lambda: "scoped-key",
        require_home_identity=False,
    )
    assert final("original response") == "Safety screen unavailable; response not verified.\noriginal response"


def test_host_snapshot_conversion_rejects_non_tuple_entries_and_preserves_capability_markers() -> None:
    assert HARNESS_CAPABILITIES == {
        "pre_llm_call.model_switch.v1",
        "pre_tool_call.decision.v1",
        "skills.snapshot.v1",
    }
    assert host_snapshot_to_verified(host_snapshot()) is not None
    assert host_snapshot_to_verified(SimpleNamespace(generation="g", entries=[])) is None


def test_host_snapshot_rejects_metadata_generation_skew() -> None:
    entry = SimpleNamespace(name="skill", description="d", excerpt="e")
    snapshot = SimpleNamespace(
        generation="g1",
        profile_generation="g1",
        registry_generation="g2",
        roots_generation="g1",
        quarantine_generation="g1",
        entries=(entry,),
    )
    assert host_snapshot_to_verified(snapshot) is None
