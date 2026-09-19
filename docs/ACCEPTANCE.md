# Acceptance

Scope: H cumulative integration from the exact reviewed G ancestor. A passing
row records this repository's offline or isolated evidence; held capabilities
remain held and are never counted as original feature completion.

| ID | Contract | Evidence/status |
| --- | --- | --- |
| AC01 | Missing/blank `TYPESAFE_API_KEY` is false; an ambient environment key is ignored; a scoped synthetic key exposes one mixed `noul`/`choice`/`score` schema. | `tests/test_registration.py`; default suite. |
| AC02 | One bounded mixed batch reaches the mocked SDK once; normalized model/answers/usage and sanitized fail-closed errors are returned. | `tests/test_client.py`, `tests/test_system_one.py`; default suite. |
| AC03R3 | Suggestion remains `HELD_UNSUPPORTED_HOST`: no production hook, roster scan, cache, worker, or RPC. Pure verified-snapshot/ranking fixtures are separately tested. | `tests/test_plugin_integration.py`, `tests/test_suggest.py`, `tests/test_skills_adapter.py`; original live-suggestion AC is held. |
| AC04R3 | Guard helpers are pure fixtures only; native registration exposes zero `pre_tool_call`/`transform_llm_output` callbacks, SDK calls, approval calls, and final-screen access. | `tests/test_guard.py`, `tests/test_plugin_integration.py`; original live guard AC is held. |
| AC05 | Hook work is bounded to two seconds; tools to 120 seconds; canonical broker admits four operations globally, uses one loop thread, keeps cancelled slots charged, and bounds reload/shutdown state. | `tests/test_runtime.py`, `tests/test_broker.py`, installed two-home lane. |
| AC06 | Routing is default-off, empty/invalid pools no-op, first-turn/high gates are enforced, and output is a current-message-only hint with no switch/config/cache/provider mutation. | `tests/test_route.py`, `tests/test_plugin_integration.py`; default suite. |
| AC07 | `questions.py` is the sole production home for built-in questions, rubrics, and thresholds; settings are detached, validated, and read-only. | `tests/test_registration.py`, `tests/test_guard.py`; default suite. |
| AC08R3 | Wheel/sdist carry explicit root and canonical broker assets. The installed wheel is copied into two temporary homes and loaded by the pinned immutable public `PluginManager`/registry. | `tests/test_packaging.py`, `tests/test_plugin_integration.py`, `tests/test_two_home.py`; Python 3.12 isolated lane. |
| AC09 | Bundled original skill has the compact period-terminated description, required sections, pinned tool/key/privacy contract, and qualified `typesafe:typesafe-system-one` discovery. | `tests/test_skill_contract.py`, `tests/test_plugin_integration.py`; default/public fixture lanes. |
| AC10 | No Hermes core edits; H remains on the approved G head lineage, uses a private cumulative feature PR, and leaves merge/deploy/tag/catalog decisions to human gates. | Git/PR/CI handoff; same-card independent review required. |
| AC11 | Default pytest/CI is keyless, socket-denied, provider-mocked, and excludes `live`; optional live results are separate and redacted. | `pyproject.toml`, CI workflow, registration adversarial key test, default suite. |
| AC12R3 | README/manifest/docs state wheel prerequisite, enable/env/flags, fail-open experimental routing, streaming limits, hint-only gap, held capabilities, and rollback. | `README.md`, `plugin.yaml`, `DECISIONS.md`, `THREAT-MODEL.md`; documented. |
| AC13 | Numeric limits reject exact one-over cases before SDK construction, broker admission, or wire transport. | `tests/test_limits.py`, `tests/test_client.py`; default suite. |
| AC14 | Unknown callback kwargs, ambient host `ContextVar`s, history/system/results, and secret markers are not inspected, retained, outbound, or logged. | projection/privacy tests across client, route, registration, and two-home lanes. |
| AC15 | Canonical installed broker identity/ABI is matched across native and broker generated files; missing, shadowed, mismatched, unsupported, or wrong-home runtime is unavailable rather than duplicated. | `tests/test_packaging.py`, `tests/test_runtime.py`, `tests/test_two_home.py`; isolated lane. |

## Verification matrix

```text
uv sync --locked --extra test
uv run --no-sync pytest -q
uv run --no-sync ruff check .
python -m compileall -q .
uv build --wheel --sdist
```

The required installed acceptance uses CPython 3.12, the immutable public
fixture `NousResearch/hermes-agent@ee4452991d17534aa561f31ee55596d082aa94e7`,
a temporary two-home `HERMES_HOME`, a wheel installed outside the checkout,
and `pytest -q tests/test_two_home.py`. Dependency setup may use the network;
provider tests use mocks and deny inference sockets. A skipped optional live
lane is not provider success.

## Not accepted by H

- TypeSafe inference or authentication against the provider in default CI.
- Live skill suggestion, roster/snapshot access, or catalog eligibility.
- Guardrail callbacks, Hermes approval, final-output screening, or streaming safety.
- Actual model switching, cache mutation, host config mutation, core changes,
  live installation, merge, deployment, visibility changes, release tags, or
  catalog submission.
