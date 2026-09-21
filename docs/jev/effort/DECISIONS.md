# Jev effort routing decisions

role: plugin implementation record
scope: closed-pool reasoning effort + scoped optional-answer seam + reviewed-fork fixture
base: main@b3fe987015793feb9496ee2e16631646afa7348a
reviewed_host: manjaroblack/hermes-agent@db69f924fd2b899ba2e34804633ea16c851d3ebb
¬: live config|install|merge|restart|paid inference|Nous PR

## Locked behavior

- Identity remains `{model, provider}`; accepted labels remain `cheap`, `coding`, `reasoning`, `long-context`.
- Unknown entry keys are ignored. Duplicate identities, malformed identities, unknown labels, and bounds violations invalidate the pool.
- Recognized effort settings are per-label: `reasoning_allowed` must be a distinct nonempty list of exact `low|medium|high` tokens; `reasoning_default` must be an exact member. Invalid optional settings disable effort for that label while retaining its model identity.
- Normalization is shared by `__init__._bounded_routing_models` and `route._validated_pool`; returned maps/lists are detached from config input.
- Routing adds one `reasoning_effort` Choice only when the deterministic union of valid label lists is nonempty. Empty union omits the question.
- Selected effort must belong to the selected label. Missing, malformed, or out-of-label answers fall back to the selected label default; disabled labels emit no effort.
- Effort never changes model slugs and never writes host agent fields. The directive carries optional `reasoning_effort`; the reviewed host owns canonical destination validation and application.
- First-turn routing is eligible in both active modes and emits `allow_cache_break: false`. Later routing is eligible only in `cache_break_if_worth_it` and emits `true` after existing worth/mismatch/confidence gates. Same-identity effort candidates are switch-worthy.

## Scoped answer policy

- Optional-answer allowance is an explicit immutable tuple threaded through runtime submit and client normalization.
- Only routing passes `(reasoning_effort,)` when that Choice exists. Ordinary `system_one`, guard, suggestion, and final calls retain exact answer requirements.
- Envelope, model, usage, size/depth, core-answer, and extra-answer checks remain strict. Invalid optional Choice answers are omitted so routing can apply the selected default; invalid envelopes still fail closed.
- Empty optional tuple avoids the new keyword when calling fake/ordinary clients; broker ABI and tool schema remain unchanged.

## Reviewed fixture

- CI and `tests/test_registration.py` / `tests/test_reviewed_harness_integration.py` pin the immutable reviewed host head above.
- The reviewed composition lane uses a candidate wheel, real PluginManager, actual hook dispatch, host approval boundary, finalizer, temporary homes, and a synthetic SDK at the network edge.
- Public fixture remains the unsupported-host/two-home lane. No live inference or host checkout mutation is part of this repository.

## Verification record

- RED: new effort tests initially failed before pool, routing, client, runtime, and harness implementation.
- GREEN CPython 3.12.3: focused effort/routing/client/runtime set `74 passed`; reviewed fixture installed-wheel lane `1 passed`; two-home lane `1 passed`; full suite `179 passed, 1 deselected`.
- GREEN CPython 3.10.20: full offline suite `175 passed, 4 skipped, 1 deselected`.
- Build/quality: `uv build --wheel --sdist`, `ruff==0.15.10 check .`, `python -m compileall -q .`, and `git diff --check` pass.
