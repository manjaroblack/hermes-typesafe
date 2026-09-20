---
name: typesafe-system-one
description: Use when TypeSafe typed decisions need a bounded skill.
version: 0.2.0
author: Hermes TypeSafe maintainers
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [TypeSafe, typed-decisions, bounded-runtime, reviewed-harness]
---

# TypeSafe System One

Use the native `typesafe` plugin's `system_one` tool for bounded typed
questions. On a host advertising all three reviewed capability markers, the
plugin also exposes one combined pre-LLM callback (routing plus suggestion),
one native pre-tool decision callback, and one final-output transform. Without
the complete marker set every harness callback is inert.

## When to Use

- Use for a bounded decision over explicit current state and named questions.
- Prefer this skill when the request needs typed `noul`, `choice`, or `score`
  answers rather than prose generation.
- Treat returned answers, routing directives, and skill hints as advisory; the
  user's actual request, native approval gate, and host lifecycle remain in
  control of the final action.

## Prerequisites

- Install the reviewed `hermes-typesafe` wheel and `typesafe-sdk>=0.7,<0.9`
  into the same interpreter that runs Hermes; the plugin never auto-installs.
- Provide `TYPESAFE_API_KEY` through Hermes' scoped secret mechanism. The plugin
  does not read `.env`, auth files, or ambient environment fallbacks.
- The pinned harness model is exactly `jev-1.13.0` and the endpoint is
  `https://api.typesafe.ai/v1/systemone`.
- A live harness requires these immutable host markers:
  `pre_llm_call.model_switch.v1`, `pre_tool_call.decision.v1`, and
  `skills.snapshot.v1`. The host must also publish a current immutable snapshot
  and accept phase-aware hook registration.
- Every harness hook has a 2 seconds absolute budget; on a host without the
  complete capability set the fallback status is `HELD_UNSUPPORTED_HOST`.

## Procedure

1. Pass only the minimum current state needed for the decision.
2. Name each question and choose one supported type. A mixed batch remains one
   bounded request:

   ```yaml
   state: "current request facts"
   questions:
     safe:
       type: noul
       instructions: "Is this safe to continue?"
     route:
       type: choice
       instructions: "Which documented route fits?"
       criteria: {direct: null, staged: null}
     effort:
       type: score
       instructions: "How much effort is needed?"
       criteria: [low, medium, high]
   ```

3. Check answer names and types before acting; do not treat missing or invalid
   answers as permission.
4. Keep the tool's bounded error response and retry policy intact. Harness hooks
   have a two-second absolute budget and no more than three pre-LLM RPCs; each
   guard and final hook has one RPC. `system_one` has a 120-second budget.

## Safety and hook contracts

- The pre-LLM callback uploads only the current user message, a local routing
  label, or the verified snapshot's bounded descriptors. It never uploads
  history, the system prompt, tool results, raw host context, or credentials.
- Routing resolves configured `{model, provider}` identities locally. A valid
  result returns a host-applied `model_switch` directive; no provider-proposed
  model is accepted. First-turn switches cannot break cache; later
  `cache_break_if_worth_it` switches may do so only after every confidence,
  mismatch, worth, and current-identity gate passes.
- Suggestion ranking uses two requests: a gate/rank batch and a shortlist
  rerank. The roster is rechecked between them; a generation change discards
  the result. An evaluated miss is the only case that emits the static miss
  line; invalid or unavailable responses fail closed without claiming a miss.
- Tool guardrails validate exact bounded `{tool_name, args}` state before one
  RPC. The plugin's own `system_one` call is skipped. Sensitive argument keys
  (`authorization`, `api_key`, `token`, `password`, `secret`, `cookie`) are
  blocked locally and never uploaded. High risk blocks; medium risk requests
  native approval with a fresh execution binding; low risk passes.
- Final screening uses a separate final-output rubric. High risk replaces the
  output with a static safe response, medium risk adds a static warning, and
  unavailable/error/deadline paths prepend the static unavailable marker to the
  original output. Streaming is never buffered or retracted.

## Offline recipes

The bundled recipe schemas are offline policy examples only. They do not
schedule work, discover tools, authorize actions, or write memory. Each recipe
must preserve an explicit uncertain/unavailable outcome:

1. `intent-before-expensive-tools` — inspect the current intent before an
   expensive action; uncertain means do not run it.
2. `rerank` — rank bounded candidate IDs and excerpts; unavailable is not an
   evaluated miss.
3. `citation check` (`citation-check`) — compare one claim with one cited
   source excerpt; uncertain remains unverified.
4. `spawn-or-not` — decide direct work versus delegation; uncertainty stays
   direct.
5. `cron-worth-it` — classify a sanitized event summary; uncertain does not
   wake a worker.
6. `kanban class` (`kanban-class`) — classify a sanitized card; `needs_input`
   stops rather than guesses.
7. `memory-worthiness` — assess one candidate durable fact; uncertainty does
   not save memory.

## Pitfalls

- Do not send history, system prompts, tool results, credentials, or unrelated
  host context as state.
- Do not expose a key in prompts, logs, examples, or error messages.
- Do not infer a roster from filesystem paths or private host registries. A
  missing capability, stale generation, malformed descriptor, invalid model,
  or failed broker is unavailable and must fail closed.
- Do not treat a provider failure as an evaluated miss or a safety approval.
- Do not add a second callback for routing, suggestion, guard, or final output;
  the registration shape is part of the reviewed contract.

## Verification

- Confirm the plugin is enabled in the intended Hermes profile and that the
  scoped key check succeeds without reading files or mutating configuration.
- Verify a mixed `noul`/`choice`/`score` batch against sanitized answer names and
  stable error codes before using it.
- Exercise the offline recipe schema validator and its uncertain outcomes; no
  recipe example may contact the network or scheduler, and the offline fixture
  set is not catalog-eligible by itself.
- Keep outbound data limited to the explicitly requested bounded state and
  questions. Disable the plugin and unset the scoped key for rollback.
