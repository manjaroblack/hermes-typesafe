# Decisions

## Authority

- PRD source: `/root/.hermes/kanban/boards/hermes-typesafe/attachments/t_bc83833d/hermes-typesafe-prd.md`
- PRD SHA-256: `eccf9f2256b44b66056fe7fa213205c3fd885907c5866131361208655c80b841`
- Frozen design v3: `docs/plans/t_3ea295ba-plan-v3.md`
- Design SHA-256: `9b756899689d6d31f31bb7f5d56c80696e75e3cbdd0a37e6d74d735c25020147`
- Independent security A3: `SECURITY_DESIGN_PASS_FOR_B3_REVIEW`, report SHA-256 `50acd1eb584a01e1554adaa45371838fde70b6f0444dd71aaf996302e32f1c2d`
- Independent B3: `GO`, `implementation_authorized=true`, ACMD01-06 only, bound to the exact v3 design hash.
- Public Hermes fixture: `NousResearch/hermes-agent@ee4452991d17534aa561f31ee55596d082aa94e7`; live Hermes was not edited.

## Foundation choices

1. The plugin is standalone native `plugin.yaml` plus flat-root `register(ctx)`.
   It is not a model provider and does not modify Hermes core.
2. The only C-phase registration is `system_one` in toolset `typesafe`.
   `provides_hooks` is empty because no hook is registered.
3. The SDK range is `typesafe-sdk>=0.7,<0.9`; C does not import it. The pinned
   product model is `jev-1.13.0`, with the fixed API endpoint reserved for the
   later client phase.
4. `TYPESAFE_API_KEY` is read only through Hermes' scoped secret seam at
   availability-check time. Missing, blank, unscoped, or unavailable access is
   false; there is no environment/file fallback.
5. The settings namespace is plugin-relative
   `plugins.entries.typesafe.settings`. Defaults are read without persistence:
   model `jev-1.13.0`, all feature flags false, routing mode `first_turn`, and
   empty routing models.
6. `questions.py` owns decision thresholds and built-in policy literals. The
   C tool handler is a static unavailable response and never invents answers.
7. The wheel carries one explicit root package mapping and one explicit
   `hermes_typesafe_broker` mapping. The broker package is inert in C; later
   work must prove provenance, two-home sharing, global bounds, reload, secret
   isolation, cancellation, and shutdown before claiming runtime support.
8. Generated broker identity is based only on sorted exact `__init__.py` and
   `core.py` bytes. Native copy-only installation without the matching wheel is
   documented as a later runtime prerequisite, not silently repaired.

9. H activates the reviewed suggestion, guard, final-screen, and model-switch
   callbacks only behind all three public capability markers. Unsupported hosts
   retain `HELD_UNSUPPORTED_HOST`; the plugin never downgrades a real switch to
   an advisory hint.
10. H packaging is one distribution: native plugin modules map to
    `hermes_typesafe`, broker sources map to `hermes_typesafe_broker`, and both
    generated identity files must match the same ABI and source digest.
11. H acceptance copies the installed wheel's plugin package into two fresh
    Hermes homes and uses the immutable public PluginManager. Source-checkout
    imports and direct fake registration are not evidence for the installed
    two-home contract.
12. Default CI remains keyless, socket-denied, mocked, and `live`-excluded.
    Routing may transmit only the current user message when explicitly enabled;
    no model/config/cache/provider switch occurs. Merge, live installation,
    deployment, visibility, tag, and catalog actions remain human gates.

## H cumulative integration override

The C/D/E/F/G notes above are historical phase receipts. H supersedes their
phase-limited status statements with the following cumulative boundary:

- H starts at exact G `940a579c1d879c8c5ef1ad30bb44426098e2e74b`; no intermediate
  merge or moving-base rebase is used.
- The wheel and sdist are acceptance artifacts, not live installation. The
  native clone/copy is a discovery path only and requires the same reviewed
  wheel in the Hermes interpreter.
- The public fixture is pinned to
  `ee4452991d17534aa561f31ee55596d082aa94e7`; every temporary home is isolated
  from inherited Hermes/Kanban environment overrides.
- Suggestion and guardrails activate only when the host advertises all three
  reviewed capability markers. Pure helper fixtures remain offline evidence;
  a missing marker set is still `HELD_UNSUPPORTED_HOST` and registers no
  harness callback.
- Runtime success requires canonical installed broker ownership. Missing,
  shadowed, mismatched, unsupported, or wrong-home seams fail closed without a
  per-profile broker fallback.

## Capability-gated harness

- The complete marker set is `pre_llm_call.model_switch.v1`,
  `pre_tool_call.decision.v1`, and `skills.snapshot.v1`. Registration also
  requires a current immutable snapshot reader and phase-aware hook seam.
- One combined pre-LLM callback owns routing plus two-stage suggestion; one
  decision-phase pre-tool callback owns tool screening; one final transform
  owns completed-output screening. Feature flags never create a second hook.
- Routing returns only a locally configured `{model, provider}` host directive.
  First-turn directives cannot break cache; later cache-break directives require
  every gate. Missing, malformed, stale, or unavailable inputs fail closed.
- Guard medium results use the host's native approval/binding path. Sensitive
  argument keys are blocked before upload, the plugin's own tool is skipped,
  and provider/key/broker/deadline failures block. Final unavailable results
  use a static prefix and never retract streaming output.

## Human gates and rollback

Merge, live installation, deployment, visibility changes, release tags, and
catalog submission are separate STAG gates. This card does not perform them.
Rollback is limited to the unmerged feature branch; a human may disable the
plugin and unset the key. No force-push, history rewrite, live restart, or
core/profile/config mutation is authorized.
