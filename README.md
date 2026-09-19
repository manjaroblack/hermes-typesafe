# Hermes TypeSafe

Standalone native Hermes plugin for TypeSafe System One typed decisions.
This repository contains the bounded typed client/runtime phase: registration,
strict JSON preflight, mixed-question requests, sanitized responses, and an
offline canonical broker boundary.

Status: D implementation candidate; not feature-complete, not catalog-eligible,
and not installed into a live Hermes profile. Guardrails and suggestion remain
held on the inspected host.

## Capability boundary

| Capability | Current behavior |
| --- | --- |
| `system_one` tool | Registered under toolset `typesafe`; key-gated; accepts bounded string/object/array state and one mixed `noul`/`choice`/`score` batch. |
| TypeSafe client/network | Lazy per-operation SDK client; fixed `https://api.typesafe.ai/v1/systemone`, pinned `jev-1.13.0` default, retry count zero, and sanitized errors. |
| Suggestion hook | `HELD_UNSUPPORTED_HOST`; no hook, roster scan, snapshot, cache, or RPC. |
| Guardrails | `HELD_UNSUPPORTED_HOST`; no `pre_tool_call` or `transform_llm_output` callback, approval call, or final-output claim. |
| Routing | Default-off and not registered in this phase; later routing is advisory only. |
| Canonical broker | The same distribution carries `hermes_typesafe_broker.core`; runtime admission is unavailable when provenance, interpreter, lease, or broker checks fail. |

A held feature is not a secure pass or a completed product requirement. The
original suggestion and guardrail acceptance criteria remain open until a
fresh host-capability design and review authorize activation.

## Installation contract

The native discovery path is a copy or git clone at
`~/.hermes/plugins/typesafe`. Install the reviewed `hermes-typesafe` wheel and
its declared `typesafe-sdk>=0.7,<0.9` dependency into the same interpreter that
runs Hermes before invoking `system_one`. The plugin never
installs dependencies, adds its checkout to `sys.path`, downloads a broker, or
falls back to a per-profile runtime.

```bash
git clone <reviewed-private-repository> ~/.hermes/plugins/typesafe
python -m pip install 'typesafe-sdk>=0.7,<0.9' hermes-typesafe.whl
hermes plugins enable typesafe
```

Set `TYPESAFE_API_KEY` through Hermes' scoped secret mechanism. The plugin does
not read `.env`, auth files, or `os.environ` as a fallback. A missing or
whitespace-only key makes `system_one` unavailable.

## Settings

Settings are read only from the plugin-relative
`plugins.entries.typesafe.settings` namespace. Registration never persists
values or mutates the host configuration.

```yaml
plugins:
  entries:
    typesafe:
      settings:
        model: jev-1.13.0
        suggestion:
          enabled: false
        guardrails:
          enabled: false
        routing:
          enabled: false
          mode: first_turn
          models: {}
```

The model is pinned to `jev-1.13.0`; ambient model/base-URL variables do not
override the product contract. `questions.py` is the single production home
for decision thresholds and built-in question policy.

## Bounded runtime

Preflight rejects unsupported/custom JSON types, cycles, non-finite numbers,
invalid Unicode, and cap violations before SDK construction or broker admission.
The fixed limits are 32,768 UTF-8 bytes for state, 131,072 bytes for the
canonical request and raw response, depth 8, 4,096 JSON values/keys, 256 items
per container, 16 questions, 128 choice options, and 16 score levels. A single
process broker admits at most four operations, uses one lazy event-loop thread,
and has no waiting queue. Timeout or unload cancellation does not release a
slot until the underlying operation exits.

## Development

The project supports Python 3.10+. Use the lockfile and an isolated virtual
environment; do not install into a live Hermes profile.

```bash
uv sync --extra test
uv run pytest -q
uv run python -m build
```

The default test command excludes the explicit `live` marker. Offline tests
use synthetic keys, mocked boundaries, temporary homes, and network/thread
poison probes. Provider inference is not part of the default suite.

The wheel maps the flat native source package to `hermes_typesafe` and maps
`broker_src/hermes_typesafe_broker` to the canonical
`hermes_typesafe_broker` package. The broker source digest uses sorted
`__init__.py` and `core.py` records framed as relative path, NUL, decimal byte
length, NUL, exact bytes. Generated identity files are excluded from the
input set.

## Security and privacy limits

Only the explicitly invoked `system_one` tool sends bounded current state and
questions to TypeSafe. Secrets, history, system prompts, tool results, host
context, and raw exceptions are not projected into the request or error JSON.
Requests use a fixed endpoint and model policy; ambient base/model variables and
SDK debug body logging are suppressed. The held guardrails do not provide
screening, approval, stream prevention, or a security boundary. Streaming text
cannot be retracted by a future final-output hook.

## Rollback

For a human-managed installation, disable the plugin with `hermes plugins
disable typesafe` and unset `TYPESAFE_API_KEY`. Do not change Hermes core or
remove a live profile configuration as part of this repository's rollback.
