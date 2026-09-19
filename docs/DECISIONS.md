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

## Held capabilities

- Suggestion is `HELD_UNSUPPORTED_HOST`: no snapshot producer, roster crawl,
  cache, scanner, worker, or suggestion RPC exists in C.
- Guardrails are `HELD_UNSUPPORTED_HOST`: no `pre_tool_call` or
  `transform_llm_output` callback, approval-store call, high-block claim,
  medium-approval claim, or final-output replacement exists in C. The future
  composed-hook matrix is `DEFERRED_HOST_CAPABILITY`, not a passing test.
- Routing is default-off and not registered in C; later routing remains a hint
  only and cannot switch models or mutate cache/config.
- Future streaming, owner override, outage, and cancellation behavior must be
  proven at the host/runtime seam. A disclaimer is not a substitute for that
  proof.

## Human gates and rollback

Merge, live installation, deployment, visibility changes, release tags, and
catalog submission are separate STAG gates. This card does not perform them.
Rollback is limited to the unmerged feature branch; a human may disable the
plugin and unset the key. No force-push, history rewrite, live restart, or
core/profile/config mutation is authorized.
