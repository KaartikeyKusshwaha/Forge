# Verification for owner review — 25 October 2026

## Version 0.4 additions

The updated controller fetched and reconstructed the real ahujasid/mcp-for-blender
source at a pinned SHA. Actual baseline execution:
https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40195232513
returned exit 2 with missing mcp imports during collection. This proves source
transport and isolated execution, not a passing Blender MCP baseline or completed
contribution. Dependency installation and Blender runtime checks remain unsupported.

Model-profile tests cover credential privacy, provider detection, local endpoints,
profile persistence, paid permission before inference, lifetime reservations,
free-only rejection and parse-only CLI input. Paid inference is mocked; no paid
request was made. Inkling inference awaits the owner's OpenRouter key. Historical
live Groq evidence below is not an Inkling benchmark.




Current design: GitHub companion, free models, isolated GitHub Actions execution,

and **no Docker**. Source is public at

[KaartikeyKusshwaha/Forge](https://github.com/KaartikeyKusshwaha/Forge).



## Real model and repository acceptance



Two actual issues in the owned public dummy repository were processed by the real

FastAPI/worker pipeline using Qwen 3.8 27B on the owner's confirmed Groq Free plan.

GitHub source was fetched at base `683ff962c5a8d27f9ab8d3c85ba71e012b8797ce`.

Planner, coder, tester and reviewer were separate calls. No mock provider was used.



| Requirement | Python issue 1 | TypeScript issue 2 |

| --- | --- | --- |

| Original baseline | 2 pass | 2 pass |

| New regression on original code | Fails as expected, 9 collected | Fails as expected, 4 collected |

| Proposed candidate | 9 pass | 4 pass |

| Additional evaluator tests on original code | Fails as expected, 8 collected | Fails as expected, 6 collected |

| Candidate plus evaluator tests | 15 pass | 8 pass |

| Model calls / metered tokens | 5 / 11,750 | 4 / 6,706 |

| Repair cycles | 0 | 0 |

| Publication | Waiting for exact human approval | Waiting for exact human approval |



Python [candidate checks](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40144143520)

and TypeScript [candidate checks](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40144352900)

are real public runner executions. The exact generated patches, fingerprints,

base/candidate/evaluator evidence and run URLs are in

[evaluation/results/live-groq-acceptance.json](../evaluation/results/live-groq-acceptance.json).

The evaluator test source was not given to the agents on the initial attempt.



These two smoke issues prove this narrow journey, not general coding reliability.

No model API fee was charged under the owner-confirmed Free plan. A rate-limit

retry is included in Python usage; token reservations can conservatively include

failed calls. The account was not upgraded and no paid fallback was used.



## Product and execution checks



- 58 local backend tests pass: policy, authorization, evidence, worker lifecycle,

  repair bounds, revisions, exact approvals, expiry/tampering, publisher ordering,

  existing PR reconciliation, manifest onboarding, and personal repository scope.

- Four background transport tests pass. Credentials are restricted to trusted

  extension contexts, fixed operations, and loopback transport.

- Lint, formatting, and JavaScript syntax checks pass.

- [CI 40144428216](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40144428216)

  passed backend, the actual installed/unpacked Manifest V3 extension, and real

  non-container runner isolation. The extension report says `Real unpacked

  extension`, no page errors, and covers progress, diff switching, checks, demo

  approval, history, light/dark, mobile, and close. Its GitHub page is a clearly

  intercepted fixture; live model acceptance is recorded separately above.

- The runner isolation job executes six Python checks (UID nobody, absent

  credentials, denied network, protected system paths, inaccessible home, file-size

  limit) and one TypeScript check through the actual systemd controller. A separate

  [remote isolation run](https://github.com/KaartikeyKusshwaha/Forge/actions/runs/40144128669)

  also passed five checks through the dispatch/artifact adapter.

- The extension ZIP contains only client files/icons, never the owner token, model

  key, source-control credential, or `.env`.



## Known failures and limits



The first small local-model research attempt produced an incorrect TypeScript

expectation and inconsistent reviewer output. It was not approved or published;

that predecessor is retained as failure history. One Groq planner initially set

needs_input without an actual question. The planner contract now distinguishes

missing requirements from the already-enforced final approval; a fresh TypeScript

run then completed. Failed runs remain visible in history.



Full Chrome launch on this Windows host failed with a side-by-side configuration

error; the headless bridge was used locally. Actual unpacked-extension verification

passed independently on Linux CI. A standard user browser still needs the owner to

load the extension and pair it, as described in OWNER_TEST.md.



App registration is implemented and tested with a simulated GitHub conversion.

The prepared owner setup uses explicit GitHub CLI mode plus an allowlist; App

registration has not been completed on the owner's GitHub account. A fresh scoped

App token or current CLI credential is used for publishing, as configured.



No generated target commit, branch, or PR has been made before human approval.

The final commit/PR action is deliberately left for the owner's exact-candidate

approval. Its transport/state logic has automated tests; the first real approved

publication remains the final user check. There is no automatic merge or deploy.



Public runner source/logs are public; private repositories are refused. Encoded

snapshots must fit 58 KB. Automatic dependency installation, shared-user hosting,

semantic/incremental indexing, automated retention/backups, PostgreSQL operation,

and extension-store distribution are not claimed as delivered. The upstream

Starlette test-client deprecation warning does not fail these test results.



Start with [the final check](OWNER_TEST.md), then review

[scope](IMPLEMENTATION.md) and [trust boundaries](threat-model.md).

