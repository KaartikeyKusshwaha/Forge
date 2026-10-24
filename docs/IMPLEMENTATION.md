# Implementation scope

Latest owner decisions supersede the original standalone Next.js plan: Forge is
a GitHub App plus a browser extension; all model access must be free.

This version is a single-owner local pilot. One private bearer token authenticates
the extension; one GitHub installation is configured on the server. Multi-user
OAuth, team roles, private repositories, and public hosting are not included.
SQLite is the local store. PostgreSQL can be configured via SQLAlchemy but has
not been acceptance-tested; future schema-upgrade migrations are still pending.

Indexing is per-run lexical/symbol retrieval at a pinned SHA. Python uses AST;
TypeScript uses best-effort symbol extraction. Persistent incremental indexing,
semantic vectors, and complete dependency graphs are future work.

Planner, coder, tester, and reviewer are distinct provider calls. A deterministic
worker enforces protected paths, call/token/time limits, and two repair attempts.
It works from bounded retrieved context and whole-file edits, not arbitrary host
shell tools. Model changes and actual runner evidence are kept separate.

The two sandbox images support pytest and Node's built-in runner with type
stripping. They do not automatically install dependencies, execute target
Dockerfiles, or run online integration tests. Image digest pinning and runtime
resource-limit validation remain pending. The bundled demo runs only exact,
trusted fixture bytes locally; its agent outputs are scripted and its checks real.

Approval covers base SHA, proposed edits/diff, profile/policy, checks, and review.
It is single-use and expires. A requested revision retires the previous candidate
and queues a fresh run with owner feedback and fresh base discovery/validation.

Worker crashes during analysis mark the run failed, requiring a fresh run. The
publisher reconciles stored commit, branch, and PR identifiers on retry. This is
safe recovery, not transparent resumption of every model/tool step.

Automatic retention, encrypted storage, backup/restore, shared tenants, hosted
workers, a benchmark dataset, and public extension-store distribution are not
implemented. No local test implies a live model result, deployed service, registered
GitHub App, published PR, or complete production security review.
