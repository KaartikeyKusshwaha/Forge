# Forge

**An engineering companion inside GitHub.** Inspect the plan, proposed diff, and
executed checks. Approve an exact candidate before Forge creates a commit, branch,
or draft pull request. There is **no separate product website**.

Owner: start with [your final check](docs/OWNER_TEST.md). The prepared real
Python and TypeScript proposals are waiting for your review.

Manifest V3 extension + Python/FastAPI API + durable Python worker. Light/dark
themes, keyboard navigation, mobile review, Progress / Changes / Checks / Timeline views.

Version 0.3 adds public repository onboarding from GitHub's Code page, custom
contribution requests, owner-fork publication, and a history panel for requests,
commits and PRs. Reopen finished requests to propose follow-up changes with fresh
approval. See [the contribution workflow and current execution limits](docs/CONTRIBUTING_FLOW.md).

**Status: local pilot implementation.** The bundled sample works with real Python
regression checks, scripted agent steps, and no model calls or GitHub writes.
Real public GitHub issues have reached human review using Groq Qwen and isolated
GitHub Actions checks. Publishing stays gated on approval of the exact candidate. See [verified status](docs/acceptance.md).

Public source: [KaartikeyKusshwaha/Forge](https://github.com/KaartikeyKusshwaha/Forge).
Backend and the real unpacked extension passed
[GitHub CI](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40142462930).

## Start locally

Requirements: Python 3.12+, uv, Node 22+, pnpm, Chrome or Edge, and GitHub CLI.
No Docker is used. Repository checks run on disposable public GitHub Actions VMs.

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

## Model connections and usage permissions

Connection settings provide separate API-key, endpoint, and CLI/environment modes.
Recognized keys discover available models automatically; OpenRouter selects free
Inkling by default. Save multiple profiles and choose the active model. Free-only
is the default; optional OpenRouter paid access requires either per-call approval
or an explicit lifetime spending cap. See [model connections](docs/MODEL_CONNECTIONS.md).

Forge never imports `OPENAI_API_KEY` or other paid provider keys. It supports:

- OpenRouter entries currently ending in `:free`, with every catalog price zero.
  Catalog verification happens before each call; free-only profiles block paid fallback.
- An owner-confirmed Groq Free plan, using Qwen 3.8 27B when available. Forge
  never upgrades the account; free quotas can stop a run.
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

### Local Qwen coding model on Windows

On a suitable NVIDIA/Vulkan GPU, run `./scripts/start-local-model.ps1` in a separate
terminal. This downloads the official Apache-2.0 Qwen2.5-Coder-7B-Instruct Q4_K_M
model (4.68 GB) and an MIT llama.cpp runtime, verifies pinned SHA-256 checksums,
and starts a loopback-only model endpoint. There is no paid API or account.
The model and runtime remain in ignored `.forge/models/`.

Set these values in `.env` and restart Forge:

```dotenv
FORGE_LLM_PROVIDER=local
FORGE_LLM_BASE_URL=http://127.0.0.1:8788/v1
FORGE_LLM_MODEL=forge-qwen-coder-7b
FORGE_LLM_API_KEY=
```

No model is claimed universally best. This coding-specific 7B option is sized for
the owner's 8 GB GPU; hosted free models may be stronger but have account quotas.
The reproducible generation harness is `scripts/evaluate-local.py`. Its first
small-model attempts and limitations remain recorded under `evaluation/results`;
they are not a reliability benchmark. The active owner setup uses Groq Qwen 3.8.

## Real repository runs

Follow [GitHub App setup](docs/GITHUB_SETUP.md), or use explicit personal CLI mode.
GitHub CLI must be signed in for remote check dispatch:

Alternatively, select **Connect GitHub App** in the extension's Connection page:
the guided manifest flow saves those values locally after GitHub confirmation.

```powershell
gh auth status
uv run forge doctor
```

Restart, open an issue in a selected public repository, and choose **Start Forge**.
The configured free provider receives the issue and relevant public source. The
isolated runners install static Python dependencies from PyPI wheels, install the
project offline in its own virtual environment, and run pytest. Locked npm projects
use `npm ci --ignore-scripts` before offline `npm test`; Node's built-in runner
works without a package manifest. Setup output and wheel hashes appear in Checks.
Dependency retrieval has network access under an unprivileged identity without
credentials; project build hooks and tests run offline with filesystem, time,
memory and process limits. Direct Python URL/VCS dependencies, dynamic dependencies
and packages without compatible wheels require a reviewed setup profile. The runner repository must be public for
this free execution route; source snapshots and check logs are therefore public.

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
src/forge/actions.py    Isolated GitHub VM dispatch, evidence, cancellation
src/forge/sandbox.py    Exact-byte trusted demo
src/forge/policy.py     Paths, protected edits, patch limits, candidate fingerprints
scripts/actions-check.py Non-root, offline systemd execution controller
tests/                 API, policy, worker, provider, publication, browser tests
```

Read the [implementation scope](docs/IMPLEMENTATION.md),
[threat model](docs/threat-model.md), and original [master plan](docs/MASTER_PLAN.md).

## Personal installation without creating an App

The GitHub App adapter remains available. For a personal workspace, Forge can
also use the existing GitHub CLI sign-in with a strict local repository allowlist:

```dotenv
FORGE_GITHUB_AUTH=cli
FORGE_ALLOWED_REPOSITORIES=your-user/your-test-repository
```

Only listed public repositories can be read or published through Forge. The CLI
credential stays server-side and never reaches target tests or the GitHub page.
This is explicit owner mode, not multi-user App authorization or a silent fallback.
Checks use `.github/workflows/forge-check.yml` on the configured public runner
repository. Compressed source must fit GitHub's dispatch payload (58 KB encoded);
oversized repositories receive a clear refusal rather than host execution.

## Talk to Forge

Choose **Talk to Forge** on a GitHub repository or issue to start a conversation
without running code. Every run also has a persistent **Message Forge** composer
and **Chat** tab. Ask questions, refine requirements or discuss check failures.
Ctrl/Cmd+Enter sends a message. Replies use the connected model and its configured
spending policy; chat does not bypass provider authentication or billing controls.

Conversations are stored with the run in the local SQLite database and remain
available through History. Chat has the supplied run evidence, not unrestricted
repository or command access. **Build from conversation** turns your written
instructions into a new sandbox-checked proposal. On a new repository it enables
public source analysis first. Approval of the exact candidate is still required
before any target commit or PR. Published PRs remain preserved; follow-ups create
new proposals using the existing revision flow.

## Model output recovery on each installation

Forge uses the user's connected model and spending policy for recovery. It does
not require the developer's API key or a separate Groq connection. Engineering
roles share typed output contracts. For models advertising function output,
Forge requests a named result function and reads its JSON arguments as data;
there is no executable tool behind that output function. Other models use their
advertised JSON mode or schema instructions.

Malformed JSON, schema mismatches and truncated responses trigger up to two
correction attempts. Unsupported output controls fall back to schema instructions.
Every attempt remains subject to call/token limits, cancellation, paid-call
permission and spending caps. Rejected requests retain conservative financial
reservations; their token count uses reported usage, or zero when none is reported.
Authentication refusals, model access restrictions and exhausted budgets stop
rather than triggering another format-repair loop. Sandbox checks and exact-change
approval still run separately after a valid proposal is produced.

Protocol fixtures cover OpenAI-compatible, Anthropic-style and Responses-style
messages. This is coverage of those protocol adapters, not a claim that every
provider or operating-system configuration has been tested. Each installation
still needs its own credentials, GitHub permissions and configured trusted runner.

## Connection panel and sessions

Connection settings open in the browser's native extension side panel where
supported, with a settings-page fallback. Provider credentials are kept outside
the GitHub page. Choose Free, Limited or Unlimited usage; edit saved profiles'
permissions without replacing their keys. Ordinary setup needs no AI connection.
Optional setup help can use the connected model or a separately saved Groq key.
[Provider coverage and usage semantics](docs/PROVIDER_COVERAGE.md) distinguishes
adapter support, inferred configuration and remaining provider-specific needs.

**History** lists started conversations, engineering runs and Forge-created PRs.
Open a record to review it. **End session** stops work, **Forget conversation**
clears its chat context, and **Delete local record** removes the stopped local
session and events. These actions do not delete GitHub branches, commits or PRs.
Do not delete the local database if you want to retain history across updates.
