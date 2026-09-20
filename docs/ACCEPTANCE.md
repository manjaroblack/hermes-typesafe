# Acceptance

Scope: reviewed TypeSafe harness activation on the approved fork capability seam.
Unsupported hosts remain inert; keyless/default CI never claims provider success.

| ID | Contract | Evidence |
| --- | --- | --- |
| AC01 | Missing/blank scoped `TYPESAFE_API_KEY` is unavailable; ambient environment keys are ignored; `system_one` remains one bounded mixed batch. | `tests/test_registration.py`, `tests/test_system_one.py` |
| AC02 | Complete fork markers activate one combined `pre_llm_call`, one decision-phase `pre_tool_call`, and one `transform_llm_output`; missing markers activate zero harness callbacks. | `tests/test_harness_integration.py`, core composed proof |
| AC03 | All flags default off (`routing.mode=off`, empty pool); unsupported and all-off paths do not create harness requests. | `tests/test_harness_integration.py`, `tests/test_plugin_integration.py` |
| AC04 | Snapshot ranking uses only the current user and immutable current generation; first criteria omit excerpts, rerank uses bounded excerpts, stale/oversized/malformed input fails open. | `tests/test_suggest.py`, `tests/test_harness_callbacks.py`, `tests/test_skills_adapter.py` |
| AC05 | Tool guard sends exact `{tool_name,args}` only; own-tool and sensitive-key paths never upload; low passes, medium returns native approval, high/unavailable blocks. | `tests/test_guard.py`, `tests/test_harness_callbacks.py`, composed policy proof |
| AC06 | Final screen uses final-specific rubrics and `response_text` only; high replaces, medium warns, low preserves, unavailable prefixes the original; no streaming retraction. | `tests/test_guard.py`, `tests/test_harness_callbacks.py`, core transform proof |
| AC07 | Routing resolves local `{model,provider}` identities and returns a host-applied model-switch directive only after closed-pool gates; off/failure/ambiguity leaves the route unchanged. | `tests/test_route.py`, `tests/test_harness_callbacks.py` |
| AC08 | Bundled skill documents seven explicit recipes with canonical offline schemas/examples: intent-before-expensive-tools, rerank, citation check, spawn-or-not, cron-worth-it, kanban class, memory-worthiness. | `questions.py`, `skills/typesafe-system-one/SKILL.md`, `tests/test_recipe_contract.py` |
| AC09 | `questions.py` is the production policy home for questions, rubrics, thresholds, deadlines, and harness limits; feature modules import those values. | `tests/test_registration.py`, `tests/test_limits.py` |
| AC10 | Wheel/sdist include the plugin, harness, bundled skill, and canonical broker assets; no Hermes core files are changed. | `tests/test_packaging.py`, `uv build --wheel --sdist`, Git diff |

## Verification matrix

```text
uv sync --locked --extra test
uv run --no-sync pytest -q
uv run --no-sync ruff check .
python -m compileall -q .
uv build --wheel --sdist
```

The isolated core proof uses the exact approved fork worktree head
`b38c2858107e9d63f98c1d3a86bd00933fbd0661`; it registers the three hooks with
`pre_tool_call` phase `decision`, then verifies keyless final and tool paths
fail closed. No paid inference, live install, merge, deploy, or core edit is
part of this task.

## Safety boundary

- Scoped secret only; no ambient environment fallback or raw body logging.
- Hook state is detached and allowlisted; history, system prompts, traces, tool
  registries, and host context variables never enter TypeSafe request state.
- Timeouts, RPC counts, snapshots, roster criteria, JSON depth/nodes, and request
  sizes are centralized and fail closed at exact bounds.
- Unsupported capability sets retain the `HELD_UNSUPPORTED_HOST` fallback and do
  not present advisory output as a real model switch or loaded skill.
