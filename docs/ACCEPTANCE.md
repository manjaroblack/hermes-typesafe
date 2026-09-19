# Acceptance

Scope: C foundation only. A passing row means the foundation contract is
verified; it does not close later client, broker, suggestion, guardrail, or
routing work.

| ID | C-phase contract | Evidence/status |
| --- | --- | --- |
| AC01 | Missing/blank `TYPESAFE_API_KEY` is false; synthetic key exposes one mixed `noul`/`choice`/`score` schema; handler returns static unavailable JSON. | Offline pytest registration tests; implemented. |
| AC07 | `questions.py` is the sole production home for built-in thresholds; settings defaults are inert and read-only. | Offline defaults/config-isolation tests; implemented. |
| AC08R3 | Real public-fixture PluginManager loads the checkout in a `hermes_plugins.typesafe` namespace and unloads it in a temporary home. | Namespaced integration test; required local/CI fixture lane. |
| AC10 | No Hermes core edits; Conventional feature branch/worktree; private exact-head PR and independent same-card review. | Git/PR/CI handoff; pending remote and review. |
| AC11 | Default pytest is keyless, mocked, socket-denied, and excludes `live` even when an ambient key exists. | Offline pytest + marker configuration; implemented. |
| AC12R3 | README/manifest visibly state runtime prerequisite and suggestion/guard holds; helper/unavailable behavior is not advertised as feature-complete. | README, manifest, decisions, threat model; implemented. |
| AC15 | Wheel contains explicit root and canonical broker package mappings plus generated identity; no C runtime support claim. | Build archive inspection and identity test; implemented pending final build output. |

## Not accepted by C

- TypeSafe inference or authentication against the provider.
- Canonical broker lifecycle/two-home/global-cap/credential/reload proof.
- Live skill suggestion or roster/snapshot access.
- Guardrail callbacks, approval, final-output screening, or streaming safety.
- Model switching, cache mutation, core/catalog changes, installation, merge, or deployment.
