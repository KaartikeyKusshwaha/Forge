# Contributing with Forge

Reload the unpacked extension after updating its files, then refresh GitHub.
Restart the local Forge service to load backend changes.

## Start from a public repository

On the repository's Code page, open Forge and choose **Enable and analyze
repository**. This saves an explicit local repository selection. It permits public
source reads and free-model processing; it does not create a fork or publish code.
The current onboarding flow uses the explicitly configured local GitHub CLI account.
GitHub App installations must select repositories through GitHub's installation settings.

Analysis pins a revision, lists test paths, reads root contribution/project files,
and shows open issues from the first 30 issue/PR results. Select an issue or type
a concrete contribution in **Or describe your contribution**. Repository guidelines
are included in the model context. This is a source/configuration preflight, not a
claim that the project builds or that every listed issue is suitable for automation.

## Review and publish

Forge snapshots the selected repository, runs its baseline in the isolated Actions
runner, and only proceeds through planning, coding, regression checks, and review
when the supported workflow permits it. No repository code executes on your host.
The current runner accepts Python/Node profiles, with no automatic dependency
installation and a 58 KB compressed snapshot dispatch limit. Blender runtime tests
are not supported. Unsupported or oversized projects can be analyzed but may stop
before generating a verified candidate. These limits remain visible in the panel.

After exact human approval, Forge creates a unique branch. If the GitHub CLI user
cannot push upstream, Forge creates or finds their fork, verifies the owner and
parent repository, commits there, and opens a draft PR against upstream. Fork setup
is after approval. The PR may need repository-specific contributor steps. A newly
created fork may require a retry while GitHub prepares it. Forge never force-pushes,
merges, or edits upstream's default branch. Fork publication is covered by mocked
transport tests; no third-party PR was opened during acceptance.

## History and follow-up requests

The history button opens a separate view with **All requests** and **Commits & pull
requests** filters. Use **Load older requests** beyond the first 50 records. Select
a record to review its diff, checks, and full Forge timeline, including the published
commit link and branch. **Refresh GitHub timeline** retrieves and stores current PR
state, up to 100 PR events, and up to 100 PR commits; limits are disclosed. This is
manual synchronization of Forge-created PRs, not an account-wide GitHub tracker.

Choose **Suggest changes** on a pending proposal or **Request follow-up changes**
on a finished request. Describe the desired change in the dialog. The fresh run
links to its parent, preserves the original request and previous publication
reference, snapshots the current upstream base, and requires new checks and approval.
Pending proposals are retired; published records retain their status and artifacts.
This creates a new proposal, not an in-place edit to an existing unmerged PR. The
model is instructed not to assume that an earlier PR has been merged.

All data is local to this owner's Forge database. Back up `.forge/` privately to
retain history; credentials inside it must not be shared.
