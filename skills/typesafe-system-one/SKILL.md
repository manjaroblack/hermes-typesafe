---
name: typesafe-system-one
description: Use when TypeSafe typed decisions need a bounded skill.
version: 0.1.0
author: Hermes TypeSafe maintainers
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [TypeSafe, typed-decisions, bounded-runtime]
---

# TypeSafe System One

Use the native `typesafe` plugin's `system_one` tool for bounded typed
questions. This plugin is a TypeSafe decision tool, not a chat model provider.

## When to Use

- Use for a bounded decision over explicit current state and named questions.
- Prefer this skill when the request needs typed `noul`, `choice`, or `score`
  answers rather than prose generation.
- Treat returned answers as advisory data and keep the user's actual request in
  control of the final action.

## Prerequisites

- Install the reviewed `hermes-typesafe` wheel and `typesafe-sdk>=0.7,<0.9`
  into the same interpreter that runs Hermes; the plugin never auto-installs.
- Provide `TYPESAFE_API_KEY` through Hermes' scoped secret mechanism. The plugin
  does not read `.env`, auth files, or ambient environment fallbacks.
- The pinned default model is `jev-1.13.0` and the endpoint is
  `https://api.typesafe.ai/v1/systemone`.

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
4. Keep the tool's bounded error response and retry policy intact. Hook work has
   a two-second (2 seconds) absolute budget; `system_one` has a 120-second budget.

## Pitfalls

- Do not send history, system prompts, tool results, credentials, or unrelated
  host context as state.
- Do not expose a key in prompts, logs, examples, or error messages.
- Guardrails and skill suggestion are `HELD_UNSUPPORTED_HOST`; this bundled
  skill does not screen tools, approve actions, or inject live skill context.
- Synthetic ranking fixtures are contract tests only, not live roster support;
  this phase is not catalog-eligible.
- A provider failure is unavailable, not an invented answer or evaluated miss.

## Verification

- Confirm the plugin is enabled in the intended Hermes profile and that the
  scoped key check succeeds without reading files or mutating configuration.
- Verify a mixed `noul`/`choice`/`score` batch against sanitized answer names and
  stable error codes before using it.
- Keep outbound data limited to the explicitly requested bounded state and
  questions. Disable the plugin and unset the scoped key for rollback.
