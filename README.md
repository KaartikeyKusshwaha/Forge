# Forge

**An engineering companion inside GitHub.** Inspect the plan, proposed diff, and
executed checks. Approve an exact candidate before Forge creates a commit, branch,
or draft pull request. There is **no separate product website**.

Manifest V3 extension + Python/FastAPI API + durable Python worker. Light/dark
themes, keyboard navigation, mobile review, Progress / Changes / Checks views.

**Status: local pilot implementation.** The bundled sample works with real Python
regression checks, scripted agent steps, and no model calls or GitHub writes.
Real GitHub/model/Docker/publisher adapters are implemented but need live
acceptance. See [verified status](docs/acceptance.md).

Public source: [KaartikeyKusshwaha/Forge](https://github.com/KaartikeyKusshwaha/Forge).
Backend, actual Linux Docker execution, and the real unpacked extension passed
[GitHub CI](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40142462930).

## Start locally

Requirements: Python 3.12+, uv, Node 22+, pnpm, Chrome or Edge. Docker is required
only for actual repository execution.

```powershell
uv sync --extra dev --frozen
uv run forge serve --with-worker
```

1. Open `chrome://extensions` or `edge://extensions`; enable Developer mode.
2. Select **Load unpacked** and choose this project's `extension` folder.
3. Click the extension icon to open Connection settings.
4. Use `http://127.0.0.1:8787` and paste the token from `.forge/owner-token`.
   `uv run forge setup` prints its file location, never the token itself.
5. Open a GitHub issue, click **Forge**, then **Take a small test drive**.
6. Review the diff and checks. Demo approval records the decision without any
   GitHub changes.

The API binds to loopback. The owner token controls this local installation; keep
the file and browser profile private. This is not a public multi-tenant service.
The development command runs a worker thread. Separate workers use
`uv run forge worker` and an API started without `--with-worker`.

## Free models only

Forge never imports `OPENAI_API_KEY` or other paid provider keys. It supports:

- OpenRouter entries currently ending in `:free`, with every catalog price zero.
  Catalog verification happens before each call; paid fallback is blocked.
- A loopback API-compatible local model server, such as Ollama. This uses your own
  compute and has no model API fee.

Copy `.env.example` to `.env` and add a free OpenRouter key, or set
`OPENROUTER_API_KEY` in the environment. Run `uv run forge models` to see the live
free catalog. `FORGE_LLM_MODEL=auto` prioritizes code-oriented candidates, including
Qwen/DeepSeek/GLM/Kimi when actual free entries exist. This is a preference list,
not a measured best-model claim. Pin a model for repeatable evaluations.

Free endpoints need an account/key, have quotas, and may become unavailable.
DeepSeek's own model API is paid and is excluded. Private repositories are blocked
until provider data handling is reviewed.
[Free variants](https://openrouter.ai/docs/guides/routing/model-variants/free),
[limits](https://openrouter.ai/docs/api/reference/limits),
[DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)

## Real repository runs

Follow [GitHub App setup](docs/GITHUB_SETUP.md). Add its ID, key path, and installation
ID to `.env`. With a Linux Docker engine, build:

Alternatively, select **Connect GitHub App** in the extension's Connection page:
the guided manifest flow saves those values locally after GitHub confirmation.

```powershell
docker build -f infra/sandbox/Dockerfile.python -t forge-python:local infra/sandbox
docker build -f infra/sandbox/Dockerfile.node -t forge-node:local infra/sandbox
```

Restart, open an issue in a selected public repository, and choose **Start Forge**.
The configured free provider receives the issue and relevant public source. The
initial images support pytest and Node's built-in runner. Dependencies must already
exist in the image; automatic package installation is not implemented.

Publishing defaults to off. Review target CI before enabling
`FORGE_PUBLISH_ENABLED=true`: branch pushes and draft PRs may trigger workflows
with secrets. Approval of the exact candidate plus a CI acknowledgment is required.
Forge never merges or deploys.

## Checks

```powershell
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q --basetemp=.forge/pytest
pnpm install --frozen-lockfile
pnpm check:extension
pnpm test:background
pnpm exec playwright install chromium
# Keep forge serve --with-worker running in another terminal.
pnpm test:extension
```

The browser test uses a temporary profile and an intercepted GitHub fixture. If
the full Chromium executable cannot start, set `FORGE_TEST_UI_BRIDGE=1` to test
the panel and actual background source through a headless runtime/storage bridge.
That is not installed-extension verification. Reports and screenshots are in
`test-results/`.

## Source map

```text
extension/             Manifest, background transport, panel, connection settings
src/forge/api.py        Authentication, runs, approval, progress events, webhooks
src/forge/store.py      Durable jobs, leases, optimistic updates, events
src/forge/worker.py     Planner → coder → tester → reviewer, bounded repairs
src/forge/github.py     App tokens, snapshots, Git database and draft PR publisher
src/forge/llm.py        Free-only catalog policy, provider calls, reservations
src/forge/sandbox.py    Docker broker and exact-byte trusted demo
src/forge/policy.py     Paths, protected edits, patch limits, candidate fingerprints
infra/sandbox/         Non-root, network-disabled Python and Node images
tests/                 API, policy, worker, provider, publication, browser tests
```

Read the [implementation scope](docs/IMPLEMENTATION.md),
[threat model](docs/threat-model.md), and original [master plan](docs/MASTER_PLAN.md).
