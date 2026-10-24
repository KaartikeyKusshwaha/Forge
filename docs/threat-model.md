# Trust boundaries

Trusted: local owner, control-plane code and token, configured App or local CLI
session, the trusted runner workflow/controller, and the browser profile.
Untrusted: issues, repository files, model output, tests, and logs.

- The API binds to loopback, checks Host, and requires a private bearer token.
  Webhooks require HMAC and never authorize execution on their own.
- Extension storage is limited to trusted contexts. A narrow background operation
  registry keeps tokens out of GitHub page scripts. Source text is escaped, and
  consequential controls require real input events plus server approval checks.
- Personal CLI access is restricted by a server-side repository allowlist, checked
  before reads and again before writes. App installation permissions remain a
  separate supported authorization path. Neither is public multi-user auth.
- A public GitHub-hosted VM is disposable per check. A systemd service runs source
  as nobody with private networking, no capabilities, no-new-privileges, protected
  system/home paths, and resource/time limits. The target receives no provider
  key, Actions runtime token, GitHub credential, or control-plane database access.
- Source snapshots and resulting logs are public. Private source is rejected.
  Exclusions and likely-secret scans reduce risk but do not prove a public source
  tree contains no embedded secrets. Logs remain untrusted when displayed.
- Runner reports are matched to a random request ID and SHA-256 of the submitted
  source snapshot. The trusted controller owns the report outside the target
  workspace. A model statement is not a command result.
- Same-model role separation is not independent correctness proof. External tests
  and human review remain necessary. Malicious tests can still misrepresent their
  own assertions; passing test counts are not a formal security assessment.
- Human approval binds exact files, patch, base, checks, profile and review. Expiry,
  changed candidates, moved bases, missing access, and unexpected remote branches
  block publication. No automatic merge, deploy or default-branch push exists.

Remaining limits: no adversarial third-party security review, hosted multi-user
auth, automated retention/backups, encrypted application storage, or universal
repository/dependency support. This is an owner-operated engineering tool, not a
public anonymous arbitrary-code service. No Docker is used.
