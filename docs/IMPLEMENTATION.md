# Current implementation scope

Owner decisions: Forge lives inside GitHub through a browser extension; no
separate product website, free model access only, and no Docker work. These
supersede the original master plan and earlier pilot notes.

## Actual runtime

The Manifest V3 extension has Progress, Changes, Checks, history, revisions,
patch download, and exact-candidate approval. FastAPI and a durable Python worker
run locally. Target code never runs in that control process or on this laptop.

Repository access supports a GitHub App (guided manifest registration) or explicit
personal mode using the owner's existing GitHub CLI sign-in and a local repository
allowlist. Personal mode is not multi-user App authorization. It is enabled here
only for the owned public Forge-Acceptance fixture repository. Both paths keep
credentials outside page scripts, model contexts, and execution workers.

Real checks dispatch `.github/workflows/forge-check.yml` on a trusted public runner
repository. Each run receives a fresh GitHub-hosted VM; the controller launches
source as a separate non-root systemd service with private networking, protected
system/home paths, no capabilities or privileges, memory/task/CPU/file-size/time
limits, and no model or GitHub credentials. There are no containers or local target
execution fallbacks. The only local code check is an exact-byte bundled demo.

Public runner source and logs are visible on GitHub. Private repositories are
blocked. Encoded compressed snapshots must fit GitHub's dispatch input limit
(58 KB here); oversized snapshots fail clearly. The existing pytest and Node test
profiles are supported. Automatic target dependency installation is not enabled.

The active model is Qwen 3.8 27B on the owner's explicitly confirmed Groq Free
plan. No account upgrade or paid fallback occurs. Free-plan quotas can stop work.
Verified OpenRouter free entries and local models remain optional alternatives.
The supplied API key is in ignored local configuration only.

## Workflow and evidence

Repository retrieval pins a base SHA, inventories text, parses Python symbols,
and performs bounded lexical/symbol search. TypeScript symbols are best effort.
The four agent roles make separate calls. Two repair cycles are permitted, and
rate-limit retries are metered. Required checks, exact edits, base SHA, and review
are sealed in a candidate fingerprint. Approval expires and is single-use. A
revision retires the old candidate and requires fresh validation and approval.

The publisher uses GitHub's Git database API and never runs target code, hooks,
merges, force-pushes, default-branch updates, or deployments. Publishing can trigger
repository CI; final confirmation explicitly acknowledges that effect.

SQLite is used locally. PostgreSQL compatibility, public multi-user OAuth,
semantic/incremental indexing, automated retention/backup, dependency preparation,
enterprise features, and extension-store listing are not claimed as delivered.
Worker crashes fail analysis safely; partial publication is reconciled using stored
identifiers, rather than pretending every interrupted step resumes transparently.

See acceptance.md for actual run links and the final owner-check procedure.
