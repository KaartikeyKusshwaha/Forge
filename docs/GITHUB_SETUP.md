# GitHub App setup

This pilot has one local owner and one server-configured GitHub App installation.
It does not use your GitHub password or a personal access token. Public multi-user
OAuth onboarding is not included.

## Guided local setup

After pairing the extension, open its Connection settings and choose **Connect
GitHub App**. The local one-time setup form opens GitHub's official App-manifest
flow with the required permissions. Confirm registration, then choose repositories
and install it. The generated key returns directly to `.forge/github-app.pem`;
App/installation configuration is saved privately in `.forge/github-registration.json`.
No key is shown in the page, extension, repository, or server logs. Publishing
stays disabled. This setup flow uses the default local port 8787.

An interrupted install can be resumed with the same button. The manual procedure
below remains available. The guided protocol is covered by local tests; real
GitHub registration still needs an owner-confirmed browser session.

## Manual setup

1. In GitHub **Settings → Developer settings → GitHub Apps**, register an App with
   a unique name. Use your source repository URL as the required homepage; no
   separate product website is needed.
2. Disable webhooks for local testing. Manual extension runs do not need them.
   Later, an HTTPS endpoint may receive `/api/webhooks/github` with the matching
   `FORGE_GITHUB_WEBHOOK_SECRET`. Webhooks never start execution themselves.
3. Repository permissions: **Contents: Read and write**, **Issues: Read**, and
   **Pull requests: Read and write**. Metadata read is implicit. Do not request
   administration, secrets, Actions write, or workflow write.
4. Generate a private key and store it at `.forge/github-app.pem`, or another
   private location outside version control. Set `FORGE_GITHUB_PRIVATE_KEY_PATH`.
5. Set `FORGE_GITHUB_APP_ID` using the App settings.
6. Install on **selected repositories only**, starting with a small public fixture.
   Set `FORGE_GITHUB_INSTALLATION_ID` from the installation settings URL.
7. Add a free model key, build both Docker images, and restart Forge. Connection
   settings should report GitHub, model, and Docker configured.
8. Start an issue and inspect the candidate. Publishing stays off until you review
   the repository CI and set `FORGE_PUBLISH_ENABLED=true`.

## Publication and recovery

Branch pushes and same-repository draft PRs may run CI with secrets. Use an isolated
fixture with no secrets or automatic deployment for the first live trial. Draft
status is not isolation. Do not expose the owner-token API to the public internet.

Approval binds the exact fingerprint. Changed bases, tampered candidates, expired
approvals, and revoked GitHub grants block publishing. The publisher uses GitHub's
Git database API and executes no target code or git hooks. Existing executable
modes are preserved. Branches use `forge/issue-<number>-<run-prefix>`; they are never
force-pushed. Persisted commits and matching existing branches/PRs are reconciled.

If interrupted after a remote commit but before local persistence, an unreferenced
Git object may remain. If a branch was already pushed, inspect its stored
publication intent and the failure before manual recovery. No failure grants an
automatic override. Mocked transport tests verify publisher logic; a live
installation trial is still required.

[App registration](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app),
[installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation),
[runner security](https://docs.github.com/en/actions/concepts/security/compromised-runners)
