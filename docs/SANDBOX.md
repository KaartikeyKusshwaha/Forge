# Disposable execution environments

Forge checks public source on a fresh GitHub-hosted Linux VM. Docker and local
target-code execution are not used. Provider keys stay in the local service;
the worker sends a pinned public commit, an exact change overlay, and a digest.
The controller verifies the reconstructed source before setup.

## Python

The controller reads `pyproject.toml`, standard requirements files and nested
requirements includes without importing the project. It collects runtime,
test/dev and build dependencies. A separate unprivileged download stage resolves
compatible wheels from PyPI. Downloaded wheel names and SHA-256 hashes accompany
the report. Each check gets a fresh virtual environment, with no shared cache.

Dependency installation uses those downloaded wheels offline. Project packaging
hooks execute as `nobody` with network disabled, using the declared build tools.
Pytest then runs against the installed project in the same environment. Installed
pytest plugins are available, including plugins declared in test dependencies.
Collection errors do not count as executed tests.

## Node / TypeScript

For npm projects without a lockfile, Forge resolves one in the disposable workspace without changing the upstream repository. With a lockfile, Forge runs
`npm ci --ignore-scripts --no-audit --no-fund` in the disposable VM, under the
unprivileged identity. Install lifecycle hooks are disabled during retrieval.
`npm test` runs offline afterward. Detected pnpm/yarn projects use Corepack with their package-manager configuration. Node build scripts run offline. Playwright projects get a temporary headless Chromium download before offline tests. Without a test script, the runner discovers
`.test.ts` / `.test.js` files for Node's built-in test runner. TAP and common
Jest/Vitest/Mocha summaries supply test counts. A successful process with no
recognized tests cannot pass the review gate.

## Execution boundary and evidence

Setup and tests use systemd services with a different user, no capabilities,
no privilege escalation, protected system and home directories, inaccessible
controller credentials, private devices, memory/process/CPU/time limits and
bounded output. Each stage has a dedicated writable scratch directory. Only
dependency retrieval has network access. Project build hooks and tests have
private network namespaces. Test stages cannot modify the installed Python
environment. No Actions token, model key or repository credential is forwarded.

Check reports include setup status/output, requested dependencies, wheel hashes,
test output/count/exit code, source digest and the GitHub run URL. Setup failures
stop before model edits; failing baseline tests remain evidence for the repair
loop. Every candidate is checked again. Publishing still requires human approval
of the exact candidate. Reports survive cleanup errors; the hosted VM is disposed
of after the job, including any files owned by the sandbox identity.

## Current boundaries

These profiles support Python 3.12 and Node 22. They do not provision Blender's
GUI, databases, external services, OS packages or GPU drivers. Python URL/VCS/local
dependency references, dynamic dependencies without static declarations, and
dependencies without compatible wheels stop with setup evidence. npm dependencies
that need install scripts may require an additional reviewed build step. A
repository requiring another toolchain needs a corresponding runner profile;
Forge must report that limitation rather than silently run on the user's device.

CI executes real fixtures proving non-root identity, missing credentials, offline
tests/build hooks, protected filesystem, file-size limits, installed Python source
packages, locked npm dependencies with install hooks disabled, and pinned public
source reconstruction. No LLM is needed for dependency detection or installation.


## Backend orchestration

Run setup exposes a static environment plan (runtime, manifests, package manager,
build, browser needs and unavailable toolchains). `GET /api/runs/{id}/environment`
returns the plan and recorded setup evidence to the authenticated extension.
The Checks panel shows environment details. Fixed CI/test flags are provided;
no host environment or user secret is copied into repository execution.
The CI fixtures include a real Chromium launch, disposable npm lock resolution,
a build artifact and tests that read it, under the same execution boundary.

The runner does not claim universal environment coverage. Python wheels and
supported Node package managers work through these profiles. OS packages,
databases, GPU drivers, Blender GUI and additional language runtimes still need
reviewed runner profiles. Forge reports such needs; it does not install arbitrary
repository-supplied system commands on the user's device.
