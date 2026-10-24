# Verified status — 25 October 2026

This is a local pilot, not a production or live GitHub acceptance claim.

## GitHub verification update

Public repository: https://github.com/KaartikeyKusshwaha/Forge . Commit `2dfe31f`
passed [CI run 40142462930](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40142462930):
47 backend tests, the actual installed Manifest V3 extension flow (no test bridge),
and three real Linux Docker checks. The latter exercised Python, TypeScript, and
non-root/read-only/network-denied execution. The extension artifact's report
explicitly says `Real unpacked extension`, with no page errors. This supersedes
the earlier bridge-only and Docker-unverified entries below for Linux CI.

An actual local Qwen3-1.7B call also returned validated planner JSON without any
API fee. It exposed and led to fixing an empty-local-key Authorization-header bug.
This one call establishes adapter function, not coding quality or task success.

| Check | Observed result |
| --- | --- |
| Python policy/API/workflow/provider/publisher tests | 47 passed. Includes actual trusted-fixture regression execution, repairs, revision invalidation, duplicate claims, webhook HMAC/replay, authentication, tampering, expiry, moved bases, and PR reconciliation. |
| Background transport tests | 4 passed. Restricted origins/operations, trusted token storage, loopback-only transport, and no credential return to content. |
| Python lint/format and JavaScript syntax | Passed. |
| Panel browser journey | Passed with a headless test bridge, real content/background source, and real localhost API/worker. Covers run creation, diff switching, check details, demo approval, history, dark mode, mobile layout, and close. |
| Visual inspection | Welcome, Changes, dark Checks, and mobile screens inspected. No horizontal mobile panel overflow. |
| Bundled code checks | Baseline 3/3 pass; expanded regression on original 4/5 pass with expected zero-limit failure; candidate 5/5 pass. |
| Model catalog | 17 entirely zero-priced `:free` entries observed via the live OpenRouter API. No DeepSeek/Qwen free entries present in that observed response. Current auto preference was `poolside/laguna-s-2.1:free`; no quality comparison or inference was performed. |
| Paid inference | No calls made. Paid endpoints and paid model fallbacks are blocked by policy. |
| Extension ZIP | Built from extension files only, including icons; no backend secrets or owner token included. |

## Remaining acceptance and external configuration

- Full Chromium failed to start on this Windows host with a side-by-side assembly
  configuration error, including a freshly downloaded matching build. The headless
  renderer worked. Browser tests used a labelled runtime/storage bridge; actual
  unpacked-extension loading and permission prompts are not verified here.
- No free OpenRouter key is configured in the current environment. The existing
  paid-provider environment key was not reused. Add a free key locally or configure
  a suitable local model before a live agent evaluation.
- No GitHub App ID, private key, or installation is configured. GitHub publishing
  is verified against mocked transport, not a live account. No PR was created.
- Docker is not installed. Images and hardened invocation are implemented, but
  container execution, networking, and resource limits need an actual Linux engine.
- Public multi-user auth, private code, dependency installation, hosted operations,
  storage retention/backups, and a representative agent benchmark remain outside
  this pilot's verified scope. PostgreSQL and GitHub Actions have not run here.
- Pytest passed with one upstream Starlette warning about its future HTTP test
  client dependency; it did not affect these recorded results.

## Reproduce

Start `uv run forge serve --with-worker`, then follow the README check commands.
On this host, use `FORGE_TEST_UI_BRIDGE=1` for the browser journey. Full-extension
mode remains the default so CI does not silently substitute the bridge.

The intercepted GitHub page is explicitly labelled as a fixture. Scripted demo
agents do not count as a live LLM evaluation. Mocked publisher tests do not count
as a published PR. Local checks do not establish public hostile-code safety.

See [setup](GITHUB_SETUP.md), [scope](IMPLEMENTATION.md), and
[threat boundaries](threat-model.md).
