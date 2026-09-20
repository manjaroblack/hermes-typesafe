# Hermes TypeSafe

Standalone native Hermes plugin for TypeSafe System One typed decisions.
The distribution contains a bounded typed client/runtime, the `system_one`
tool, and a reviewed capability-gated harness for skill suggestion, guardrails,
final-output screening, and model routing.

Status: H cumulative experimental candidate; install and catalog decisions remain
human-gated. The harness activates only when the host exposes the complete
reviewed fork API. On the current host, or any host missing a marker, the
harness remains inert with `HELD_UNSUPPORTED_HOST` semantics.

## Capability boundary

| Capability | Behavior |
| --- | --- |
| `system_one` tool | Registered under toolset `typesafe`; key-gated; accepts bounded string/object/array state and one mixed `noul`/`choice`/`score` batch. |
| TypeSafe client/network | Lazy per-operation SDK client; fixed `https://api.typesafe.ai/v1/systemone`, exact harness model `jev-1.13.0`, retry count zero, and sanitized errors. |
| Combined pre-LLM hook | With all markers, one callback performs local-pool routing plus two-stage suggestion ranking; it sends only allowlisted current-message/snapshot projections and returns host-applied directives/context. |
| Tool guard hook | With all markers and `guardrails.enabled`, one decision-phase `pre_tool_call` screens exact bounded `{tool_name,args}` state, skips `system_one`, blocks sensitive keys locally, and delegates medium risk to native approval. |
| Final transform | With all markers and `guardrails.enabled`, one `transform_llm_output` callback applies a separate final rubric after complete output; unavailable paths prepend a static marker and never retract streaming text. |
| Bundled skill | `typesafe:typesafe-system-one`; documents activation markers, limits, seven offline recipes, privacy, and rollback. |
| Canonical broker | The same distribution carries `hermes_typesafe_broker.core`; runtime admission is unavailable when provenance, interpreter, lease, or broker checks fail. |

Missing any of `pre_llm_call.model_switch.v1`,
`pre_tool_call.decision.v1`, or `skills.snapshot.v1` registers none of the
three harness callback families, even when flags are enabled. All flags are
default-off. Registration never writes host configuration, discovers a roster,
starts a worker, or contacts TypeSafe merely because a flag is present.

## Installation contract

The native discovery path is a copy or git clone at
`~/.hermes/plugins/typesafe`. Install the reviewed `hermes-typesafe` wheel and
its declared `typesafe-sdk>=0.7,<0.9` dependency into the same interpreter that
runs Hermes before invoking `system_one`. The plugin never installs
dependencies, adds its checkout to `sys.path`, downloads a broker, or falls back
to a per-profile runtime.

```bash
git clone <reviewed-private-repository> ~/.hermes/plugins/typesafe
python -m pip install 'typesafe-sdk>=0.7,<0.9' hermes-typesafe.whl
hermes plugins enable typesafe
```

Set `TYPESAFE_API_KEY` through Hermes' scoped secret mechanism. The plugin does
not read `.env`, auth files, or `os.environ` as a fallback. A missing or
whitespace-only key makes `system_one` unavailable and makes optional pre-LLM
features no-op; guard and final paths fail closed.

## Settings

Settings are read only from the plugin-relative
`plugins.entries.typesafe.settings` namespace. Registration never persists
values or mutates host configuration.

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

An enabled pool uses the strict named-entry shape:

```yaml
routing:
  enabled: true
  mode: first_turn
  models:
    cheap:
      model: jev-cheap
      provider: typesafe
    coding:
      model: jev-coding
      provider: typesafe
```

Only `cheap`, `coding`, `reasoning`, and `long-context` labels are accepted,
with at most four unique `{model, provider}` identities. Routing resolves both
fields locally; no provider-proposed SKU is accepted. `first_turn` requires the
actual first-turn boolean and cannot break cache. `cache_break_if_worth_it`
requires a later turn and only returns `allow_cache_break: true` after
confidence, mismatch, worth, difficulty, and current-identity gates pass.

## Bounded hook contracts

Every hook has a two-second absolute budget and a useful 1.8-second budget. The
combined pre-LLM callback makes no more than three RPCs: one routing batch and,
when a verified roster is available, one rank/gate batch plus one shortlist
rerank. Guard and final callbacks make at most one RPC each. The tool operation
retains its 120-second budget.

The suggestion snapshot is immutable, bounded to 512 entries, 1 MiB metadata,
and 2 MiB raw publication input. Skill names are bounded to 128 bytes,
descriptions to 512 bytes, and excerpts to 700 characters/2,800 bytes. Profile,
registry, roots, and quarantine generations must all equal the published
generation. The rank request includes only names plus descriptions capped at 60
characters; the rerank adds excerpts capped at 700. A generation change between
requests discards the result. Only a valid evaluated hit or evaluated miss can
produce context; provider failure, malformed answers, stale data, and
unavailable snapshots do not claim a miss.

Tool guard state is exactly `{tool_name, args}`. The plugin's own `system_one`
call is skipped before validation. Keys named (case-insensitively)
`authorization`, `api_key`, `token`, `password`, `secret`, or `cookie` block
locally and are never uploaded; arbitrary string values are not scanned or
claimed to be secrets. Low risk passes, high risk blocks, and medium risk
returns a native approval decision bound by the host to the current call's
nonce, generation, tool identity, and canonical arguments. Missing key, model,
identity, broker, provider, malformed result, deadline, or runtime error blocks.

Final output uses separate final-specific questions. High risk replaces the
complete response with a static safe response; medium risk prepends a static
warning; unavailable/error/deadline paths prepend
`Safety screen unavailable; response not verified.` to the original text.
Streaming/interim output is never buffered or retracted.

## Offline recipes

`questions.py` contains seven schema-validated, offline-only examples:
`intent-before-expensive-tools`, `rerank`, `citation check` (`citation-check`),
`spawn-or-not`, `cron-worth-it`, `kanban class` (`kanban-class`), and
`memory-worthiness`. Each preserves an explicit uncertain/unavailable outcome.
The examples do not schedule work, call the provider, authorize tools, or write
memory; they are not catalog eligibility by themselves.

## Bounded runtime and privacy

Preflight rejects unsupported/custom JSON types, cycles, non-finite numbers,
invalid Unicode, and cap violations before SDK construction or broker
admission. The broker admits at most four operations globally, uses one lazy
event-loop thread, and keeps cancelled slots charged until the underlying
operation exits. Requests use a fixed endpoint and model policy; SDK debug body
logging is suppressed.

Only explicitly invoked TypeSafe operations send bounded state and questions.
History, system prompts, tool results, host context, credentials, raw
exceptions, and ambient `ContextVar` values are not projected into harness
requests or error JSON. The plugin captures no roster, starts no worker, and
uses no filesystem discovery on an unsupported host.

## Development

The package metadata accepts Python 3.10+. Use the lockfile and an isolated
virtual environment; do not install into a live Hermes profile.

```bash
uv sync --locked --extra test
uv run --no-sync pytest -q
uv build --wheel --sdist
```

The default test command excludes the explicit `live` marker. Offline tests use
synthetic keys, mocked boundaries, temporary homes, and network/thread poison
probes. Provider inference is not part of the default suite.

## Rollback

For a human-managed installation, disable the plugin with `hermes plugins
disable typesafe` and unset `TYPESAFE_API_KEY`. Do not change Hermes core or
remove a live profile configuration as part of this repository's rollback.
