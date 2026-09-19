role: hermes-orchestrator
do: decompose this PRD into a durable task graph on board hermes-typesafe; assign implementation to hermes-coding; route review to hermes-review
¬: implement code; merge; deploy; edit NousResearch/hermes-agent core; catalog PR in v1; live TypeSafe network in tests; scratch workspace
board: hermes-typesafe
project: hermes-typesafe
primary: /root/apps/hermes-typesafe
github_repo_intended: manjaroblack/hermes-typesafe
plugin_id: typesafe

This is a new product. Treat the following as the authoritative product-intent document.

Target project path:
 /root/apps/hermes-typesafe

Workspace rules:
- Bootstrap / discovery: dir:/root/apps/hermes-typesafe
- Implementation cards: git worktree under /root/apps/hermes-typesafe/.worktrees/<task-id>
- Never scratch.

Operating rules:
- Planning and decomposition only on this card.
- Do not implement code directly.
- Create a durable task graph on board hermes-typesafe; pass --board hermes-typesafe for every task command.
- Assign implementation to hermes-coding (Luna). Same-card review via hermes-review (Grok). Do not set-model those cards to Grok for coding.
- Cheap OpenRouter default unless a card already has a profile model. Do not spend Claude-class SKUs.
- Discover the global profile roster before assignment.
- Identify assumptions, unknowns, acceptance criteria, tests, risks, and non-goals.
- Do not merge, deploy, expose publicly, or modify production systems without STAG explicit approval.
- Do not edit /root/.hermes/hermes-agent.
- Catalog YAML PR to upstream Hermes is OUT OF SCOPE until STAG says so (two-week pin maturity after a stable tag).

Repository and delivery contract (write these into implementer bodies):
1. Bootstrap git repo at /root/apps/hermes-typesafe before implementation if absent.
2. Verify git status, remotes, default branch, ownership.
3. Never implement directly on main.
4. Dedicated feature branch + Kanban worktree for code-changing tasks.
5. Conventional commits.
6. Add .gitignore and README.
7. Add GitHub Actions CI for tests (pytest, no live network).
8. TDD for new behavior.
9. Run real local verification and record output.
10. Push feature branch to GitHub manjaroblack/hermes-typesafe (create private or public repo as gh default for this user; do not merge).
11. Open a PR with summary, test plan, acceptance mapping.
12. Wait for GitHub checks; diagnose failures.
13. kanban_request_review reviewer=hermes-review.
14. Do not merge without STAG.

# PRD — Hermes TypeSafe / Jev plugin

## Why this is a plugin, not core
Hermes AGENTS.md rejects third-party SaaS in the core tree. Jev is TypeSafe's System One model: typed decisions, not chat. Do not add a model provider. Do not add tools/jev.py to hermes-agent.

TypeSafe docs: https://docs.typesafe.ai/introduction and llms.txt index.
API: POST https://api.typesafe.ai/v1/systemone
SDK: typesafe-sdk>=0.7,<0.9 (PyPI 0.7.0 as of 2026-09-18). Python >=3.10.
Pin model jev-1.13.0. Do not pin jev-latest for behavior.
Secret: TYPESAFE_API_KEY only.
Settings: plugins.entries.typesafe.settings via ctx.get_config / ctx.set_config.

## Product
Standalone native plugin (plugin.yaml + register(ctx)).

v1 catalog-eligible: tool + skill suggestion (suggestion flag default off).
Experimental behind flags: guardrails, routing. Not in first catalog pin.

## Seams (Hermes plugin API, do not invent hooks)
- ctx.register_tool → system_one, toolset typesafe, check_fn=key present
- ctx.register_hook pre_llm_call → skill suggestion context string on current user message (never system prompt; cache-safe)
- ctx.register_hook pre_tool_call → {action:block,message} or {action:approve,message,rule_key}
- ctx.register_hook transform_llm_output → replace final reply string
- Skip the plugin's own tool in guardrails (no recursion)
- Plugins CANNOT call switch_model. Routing computes + injects a hint only. Actual model switch is a documented gap. cache_break_if_worth_it logs "would have switched" and still only hints until Hermes grows a generic hook.

## Timeouts
- Harness hooks (suggest/route/guard): 2s. Fail open on timeout/429/529/errors.
- Tool system_one: 120s. Fail closed with JSON error.

## Tool system_one
Agent-callable. Parameters: state (string|object|array), questions map of noul|choice|score with instructions and criteria, optional model override defaulting to settings.model. Return JSON: model, answers (choice/probabilities/confidence, score/legend/probabilities/confidence, noul), usage. Many questions in one call (speculative fan-out). Schema must not name tools from other toolsets.

## Skill suggestion (flag suggestion.enabled default false)
Adapt TypeSafe cookbook https://docs.typesafe.ai/cookbooks/skill_suggestion.md
State: current user message only (locked).
Two calls: rank live Hermes skill index + gate nouls; rerank top 3 with fits nouls.
At most one skill name.
pre_llm_call context:
- hit: "Relevant to the current request: NAME. Ignore this if it does not fit what the user actually asked for."
- miss: "No skill in the roster appears relevant to this request."
If TypeSafe down: return no context.
Do not mutate the skills index in the system prompt.

## Guardrails (flag guardrails.enabled default false)
Screen: tool arguments + final assistant text only. Not inbound user. Not tool results.
Default questions in ONE file (questions.py or questions.yaml): jailbreak/injection in tool args, credential exfil, destructive irreversible action.
Thresholds in that same file: high 0.80, medium 0.50 (settings may override).
High → block tool / replace reply.
Medium → approve tool (Hermes approval, rule_key per check) / warning prefix on reply.
Low or TypeSafe down → pass.

## Routing (flag routing.enabled default false)
Modes: off | first_turn | cache_break_if_worth_it (settings.routing.mode default first_turn).
Pool: settings.routing.models named map cheap/coding/reasoning/long-context each {model, provider}. Empty pool → no-op.
One TypeSafe call, current user message only:
- Choice: which named model
- Noul: current model mismatch
- Noul: worth breaking cache
- Score: task difficulty
Switch only in the hypothetical future hook if mismatch AND worth-it high AND Choice confidence high AND winner != current. Today: hint only.

## Config defaults
model: jev-1.13.0
suggestion.enabled: false
routing.enabled: false
routing.mode: first_turn
routing.models: {}
guardrails.enabled: false
guardrails.high: 0.80
guardrails.medium: 0.50

## Repo layout
plugin.yaml — name typesafe; capabilities honest (tools, hooks, requires_env TYPESAFE_API_KEY)
__init__.py — register(ctx)
client.py — TypeSafe client wrapper
tool_system_one.py
questions.py — only place questions+thresholds live
suggest.py
route.py
guard.py
skills/typesafe-system-one/SKILL.md — Hermes authoring: description ≤60 chars ending period; When to Use; Prerequisites; Procedure; Pitfalls; Verification. Do not vendor typesafe-ai official SKILL.md (fails 60-char rule).
tests/ — stdlib+pytest+unittest.mock; no live network; temp HERMES_HOME if needed
README.md — install: copy/clone to ~/.hermes/plugins/typesafe; hermes plugins enable; set TYPESAFE_API_KEY; flags
.gitignore
pyproject.toml with typesafe-sdk>=0.7,<0.9

## Tests that must exist before calling this done
- No key → tool check_fn false / not exposed
- Key → schema has noul, choice, score
- Suggestion off → pre_llm_call returns nothing
- Suggestion on, mocked rank+rerank → one name in suffix; empty roster → nothing
- Guard off → tools pass
- Guard on high noul → action=block with message
- Guard on medium → action=approve with rule_key
- Hook timeout → fail open
- Routing empty pool → no-op
- Questions file is sole threshold home

## Phased implementer cards (suggested graph)
1. Bootstrap repo + plugin skeleton + pyproject + README (hermes-coding, worktree)
2. TDD client + system_one tool (hermes-coding)
3. TDD suggestion hook (hermes-coding)
4. Plugin-local skill (hermes-routine or coding)
5. TDD guardrails experimental (hermes-coding) — not catalog-required
6. TDD routing hint experimental (hermes-coding) — not catalog-required
7. CI + GitHub repo/PR (hermes-coding)
8. Independent review of the PR (hermes-review)

Catalog pin to NousResearch/hermes-agent/plugin-catalog/ is a later STAG-gated card. Do not create it now.

## Acceptance
Install from git into a temp HERMES_HOME in tests. system_one works against mocked SDK. Suggestion and guardrails off unless flagged. Zero files changed under /root/.hermes/hermes-agent.

## Rollback
hermes plugins disable typesafe; unset key. No Hermes core revert.

## Origin
STAG Discord thread Integrate Jev into Hermes agent. Locked grill Q1B Q2D Q3B Q4A Q5A Q6A Q7B Q8 A+cache_break-as-setting-but-hint-only-until-core-hook Q9C-tools Q10A Q11A Q12A Q13 pack accepted Q14A.
