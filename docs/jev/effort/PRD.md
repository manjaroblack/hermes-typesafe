# PRD: Jev-selected reasoning effort inside a closed per-pool map

STAG lock 2026-09-20: option 2, implement now.

Closed per-pool effort lists. Jev picks only inside that list. Not a free SKU.

## Project
- Board: hermes-jev
- Project: p_7211c32b / hermes-jev
- Primary: /root/apps/hermes-agent (fork, branch local/runtime)
- Plugin: /root/apps/hermes-typesafe (main)
- Live gateway and ~/.hermes/config.yaml are out of scope until STAG says merge/install
- No Nous PRs. No live gateway edits. No merge without STAG.

## Problem
Jev already routes `{model, provider}` from a closed pool. It does not set thinking level.
`agent.reasoning_effort` stays at config (`high` on the Grok door).
Host `apply_pre_llm_model_switch` accepts only `model`, `provider`, `allow_cache_break`.
Same-identity model/provider currently returns False, so an effort-only change is impossible.

## Locked product rules
1. Effort is never encoded in a model slug. Forbidden: `gpt-5.6-luna-max`, `grok-4.6-max`.
2. Each pool label has `reasoning_allowed` (list of Hermes effort tokens) and `reasoning_default`.
3. Empty `reasoning_allowed` means "this destination does not take effort"; omit the field.
4. Jev may choose only a token in the selected label's allowed list.
5. If Jev's choice is missing, malformed, or not in that list: use that label's default. Do not fail the model switch.
6. Same routing RPC as today. Add one Choice question. Do not add a fourth pre-LLM call.
7. Effort change is a cache-break. First turn may set effort with `allow_cache_break: false`. Later turns need `cache_break_if_worth_it` gates already used for model switch.
8. Effort-only (same model+provider, different allowed effort) MUST apply when those gates pass. Today's same-identity early return is a bug for this feature.
9. Host applies effort. Plugin never writes `agent.reasoning_effort` itself.
10. Unknown/unsupported token for the destination family: skip effort, keep model switch if any.

## Live pool (do not invent SKUs)
Already stored under `plugins.entries.typesafe.settings.routing.models`:

- cheap: `z-ai/glm-5.3-flash` / `openrouter` — `reasoning_allowed: []` (omit)
- coding: `gpt-5.6-luna` / `openai-codex` — allowed `low|medium|high` (not `max`), default `medium`
- reasoning: `grok-4.6` / `xai-oauth` — allowed `low|medium|high` (not `xhigh`), default `high`

Grok `xhigh` and Codex `max` stay out of the allowlists unless STAG later expands them.

## Settings shape
Keep `model` and `provider` required. Extra keys must NOT void the pool
(today `_bounded_routing_models` requires `set(entry) == {model, provider}` — that would kill routing if we add effort keys).

```yaml
routing:
  enabled: true
  mode: cache_break_if_worth_it
  models:
    cheap:
      model: z-ai/glm-5.3-flash
      provider: openrouter
      reasoning_allowed: []
    coding:
      model: gpt-5.6-luna
      provider: openai-codex
      reasoning_allowed: [low, medium, high]
      reasoning_default: medium
    reasoning:
      model: grok-4.6
      provider: xai-oauth
      reasoning_allowed: [low, medium, high]
      reasoning_default: high
```

Malformed allowed/default → that label omits effort, pool still valid for model routing.

## Host (fork) contract
Extend `model_switch` directive:

```json
{
  "model_switch": {
    "model": "grok-4.6",
    "provider": "xai-oauth",
    "allow_cache_break": true,
    "reasoning_effort": "medium"
  }
}
```

- `reasoning_effort` optional string. Absent = do not change effort.
- Validate against Hermes effort vocabulary, then destination-family clamp (reuse `agent.reasoning_effort` / Codex clamp; never invent a second vocab).
- Apply via existing `agent.switch_model` / request overrides. Do not rebuild frozen prompt.
- Same-model effort change: apply when first-turn or `allow_cache_break` gates pass.
- Plugin-proposed effort not in that label's allowed list: ignore effort.
- Tests in `tests/agent/test_plugin_pre_llm_switch.py` and fork contract tests.

## Plugin contract
- Same routing batch: existing Choice/Noul/Score plus `reasoning_effort` Choice whose criteria are the union of non-empty allowlists.
- After target label is chosen, intersect. Host sees only the intersected token or omission.
- `format_model_switch_directive` includes `reasoning_effort` only when intersected token exists.
- Offline tests: extra keys do not void pool; empty allowlist omits; out-of-allowlist falls back to default; first_turn vs cache-break; cheap Flash never emits effort.

## Non-goals
- No live config write from the plugin.
- No catalog, no Nous PR, no gateway restart, no merge.
- No suggestion miss/hit UX change in this slice.
- No opening the allowlists to `xhigh`/`max`.

## Acceptance
1. Independent review GO on fork PR and plugin PR.
2. Offline tests prove effort-only switch, allowlist intersection, Flash omit, invalid token skip.
3. Existing model routing still works if effort keys absent (compat).
4. STAG merge/install remains a later explicit order.

## Rollback
Leave flags as they are. Effort is additive. Disable by omitting `reasoning_allowed` or reverting the two PRs.
