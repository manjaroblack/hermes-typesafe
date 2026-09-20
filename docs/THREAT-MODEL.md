# Threat model

## Scope

The cumulative H candidate is native Python plugin code loaded in-process by
Hermes. It registers one key-gated typed-decision tool and, only on the
reviewed fork capability set, one combined pre-LLM hook, one decision-phase
pre-tool hook, and one final-output transform. No live profile or Hermes core
is edited by this repository.

## Assets

- `TYPESAFE_API_KEY` and Hermes profile-scoped secret boundaries.
- Current tool state and future question payloads, which may contain user or
  business data.
- Host approval/configuration, plugin registries, and other profiles' state.
- Honest capability reporting: a missing marker set must not look enabled.

## Trust boundaries

1. Hermes loads `plugin.yaml` and `register(ctx)` inside the host process.
2. The host's scoped secret accessor supplies a key only during an accepted
   operation; C never falls back to environment or files.
3. The H client crosses the provider boundary only for an explicitly accepted
   operation. Default tests use mocks and denied sockets; provider failures are
   sanitized and fail closed.
4. The wheel/native-copy boundary requires a matching canonical broker package
   before runtime admission; H reports unavailable instead of repairing a
   missing or shadowed dependency.

## Mitigations in C-H

- Import-light modules use only the standard library and do not import
  `typesafe_sdk`.
- Registration reads only plugin-relative settings, does not call `set_config`,
  and registers no unsupported hooks. A missing capability marker makes all
  three harness callback families inert.
- Tool availability is false for absent, blank, unscoped, or failing secret
  access. The static response contains no key, request, exception, or fake
  answer.
- The schema is self-contained and names no foreign toolset or provider tool.
- Explicit pytest socket/thread poison probes and isolated temporary-home
  PluginManager tests cover the registration boundary.
- Explicit setuptools mappings and source-byte build identity prevent accidental
  duplicate broker packages in the distribution.
- `.env`, worktrees, tests, build outputs, and editor state are excluded from
  committed artifacts as appropriate.

## H integration controls

- Native and canonical broker generated identities carry one ABI and source
  digest. Build and runtime checks reject drift before broker admission.
- Runtime imports only the installed `hermes_typesafe_broker.core` owned by the
  same distribution. Missing wheel, shadowed origin, wrong ABI/build, wrong
  interpreter, wrong Hermes home, fork, subinterpreter, or lifecycle seams
  fail closed without a duplicate per-profile owner.
- The immutable public Hermes fixture is loaded in isolated temporary homes
  from copies of the installed wheel package. The two-home lane verifies one
  canonical broker owner, global four-operation admission, per-operation
  credentials/models, unload/reload revocation, late-result rejection, and
  bounded cancellation/shutdown.
- Default CI clears inherited Hermes/Kanban variables, does not use an ambient
  key, mocks provider transport, and excludes the explicit live marker.
- The combined pre-LLM callback projects only current-message text, local
  routing labels, and verified snapshot descriptors. Routing emits only a
  local-pool `{model, provider}` directive for the host turn owner; it never
  accepts a provider-proposed SKU or writes config/cache/session state.
- Tool guard state is exactly `{tool_name,args}`. Sensitive argument keys are
  blocked before upload; medium results rely on the host nonce/generation
  binding and native approval path; provider/key/broker/deadline errors block.
  Final screening uses a separate rubric and static unavailable prefix; it does
  not buffer or retract streaming output.
- SDK errors, request/response bodies, headers, and secret markers are
  sanitized before logs or error JSON.
- Wheel/sdist archive tests assert plugin/skill/identity assets and reject
  private docs, tests, worktrees, bytecode, and environment files.

## Held or deferred risks

- Hosts without all three reviewed markers remain `HELD_UNSUPPORTED_HOST`; no
  callback workaround attempts private registries or filesystem discovery.
- The reviewed fork owns final-argument ordering and approval binding; the
  plugin still fails closed if those callbacks or identity fields are absent.
- The snapshot adapter rejects stale generations, unsafe descriptors, and
  incomplete metadata rather than publishing a partial roster.
- A future canonical broker must prove one process owner/thread, global four
  admissions, bounded leases/tasks, two-home isolation, unload/reload,
  cancellation, fork/subinterpreter checks, and provenance before runtime
  support is claimed.
- Provider request/response body logging, decoded-response caps, owner
  overrides, and outage semantics remain bounded by the client/runtime tests;
  missing or malformed results are unavailable rather than permissions.
- Trusted same-process Python can tamper with imports or memory; this plugin is
  not a sandbox. Process restart remains the boundary for broker replacement.

## Operational boundary

Default tests and CI are offline. An explicit future live smoke may use an
already-scoped key under a separate gate, with model `jev-1.13.0`, retry zero,
bounded one-attempt behavior, and redacted evidence. Missing key is skipped;
a provider auth error fails closed. This foundation never runs live smoke.
