# Pilot trust boundaries

Trust: local owner, control-plane process, App key, Docker daemon/images, browser
profile. Untrust: issue text, source, model output, target tests, and logs.

- Loopback API with Host validation and bearer authentication; no permissive CORS.
  Webhooks require their own HMAC and never authorize a run.
- Background transport accepts fixed operations from GitHub and its own settings.
  It rejects page-selected URLs and restricts token storage to trusted contexts.
- Tokens never enter the GitHub content script. Source is escaped. Consequential
  UI actions require trusted events; the server enforces approval independently.
  A fully compromised GitHub page remains outside the overlay's threat boundary.
- Target code executes only in non-root Linux containers: no network, capabilities,
  host mounts, secrets, or Docker socket; read-only root, bounded scratch, CPU,
  memory, PID, file size, command duration, and output.
- The broker holds daemon access. Use a disposable worker host without production
  workloads. Docker shares a kernel and is not a public hostile-code guarantee.
- Distinct model roles do not prove independent reasoning or prevent dishonest
  tests. A live external evaluation set remains necessary.
- Fingerprints and expiring owner approvals gate every publication. The publisher
  mints a fresh repository-scoped token and never merges, force-pushes, edits CI,
  pushes the default branch, or deploys. Publishing may trigger target workflows.
- Secret exclusions/scans are limited defenses. Public code may contain embedded
  secrets; provider data terms still matter.

Pending: live container enforcement, adversarial repository exercises, retention,
backup/restore, Windows token ACL hardening, provider privacy review, multi-user
auth, and actual GitHub publication acceptance.
