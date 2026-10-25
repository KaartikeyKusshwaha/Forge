# Model connections and permissions

Open the extension's **Connection settings**, then **Models & API keys**. Keys
are managed only in extension settings and the owner-authenticated loopback API.
GitHub-page scripts cannot list keys, configure profiles, or approve API spending.

## Separate connection options

- **API key:** paste a key; Forge recognizes OpenRouter (`sk-or-`) and Groq
  (`gsk_`) prefixes, verifies access, reads available text/tool models, and picks
  a compatible default. OpenRouter prefers `thinkingmachines/inkling:free`.
  Unknown formats require an explicit supported provider; Forge never probes a
  secret across multiple providers.
- **Endpoint:** use an exact official OpenRouter/Groq base URL and its key, or an
  OpenAI-compatible local HTTP server on loopback ending in `/v1`. Local endpoints
  need no key. Arbitrary external endpoints are not supported. A local proxy must
  not forward to a paid service: Forge cannot inspect the billing behind a proxy.
- **CLI / environment:** reference `OPENROUTER_API_KEY` or `GROQ_API_KEY` in the
  backend's environment/`.env`, or paste a curl example containing an official
  endpoint and Bearer header. Curl is parsed as configuration only. Shell scripts,
  installers, environment changes, and dependency commands are never executed.

The API key alone identifies a provider when its format is recognized; a key
does not inherently identify one model. The provider's catalog supplies available
models. Connection verification uses metadata requests, not inference calls or a
paid coding benchmark. A saved profile offers a model picker and displays the
active provider and policy. Multiple keys are separate profiles; Forge does not
rotate them to bypass quotas. Switching is blocked while runs are queued/active.

## Usage permissions

- **Free limits only** (default): current zero-price routes only, with no paid
  fallback. Groq additionally requires the user's Free-plan confirmation because
  its public model list does not establish the account's billing plan.
- **Ask before every paid API call:** OpenRouter only. Each attempt, including a
  retry, reserves a maximum token cost within the profile's lifetime USD cap and
  pauses. In settings, review the role, run and reserved amount, then approve or
  decline. Requests expire after five minutes. No inference request is sent before
  approval. Free calls need no spending approval.
- **Paid API calls allowed within my cap:** OpenRouter only. No per-call prompt,
  but every attempt reserves its maximum against the profile's lifetime USD cap.

Forge sets provider routing price ceilings and bounds output tokens. A conservative
UTF-8 input-token estimate plus framing overhead reserves cost before sending.
Reported costs reconcile the reservation; missing/uncertain cost keeps it reserved.
The cap covers this profile's Forge calls, not usage in other apps or provider-side
billing changes. Use a provider-side API-key spending limit as an additional account
control. Forge never purchases credits, enables auto-recharge, or upgrades a plan.
The permission modes cannot grant those account actions or override PR approval.

## Credential storage

Provider keys are not stored in the extension or returned by profile APIs. Windows
profiles use current-user DPAPI encryption. On other systems the owner-local vault
file uses mode 0600. Keys exist in memory for authorized provider requests. The vault
and usage reservations are in ignored `.forge/model-profiles.sqlite3`. Back up this
directory privately; Windows-encrypted keys are bound to the current Windows user.
Legacy `.env` keys remain local; a saved active profile takes precedence on restart.

The API is an owner-operated local control plane, not a multi-user hosted credential
service. Free research endpoints can log prompts; use public repository content and
review provider terms. No claim of a production security audit is made.

## Groq diagnostic helper

On a failed run, **Analyze failure with Groq Free** sends a bounded, redacted subset
of recorded errors and test output to a confirmed free-plan Groq profile. This
installation can also use its private pre-Inkling Groq backup. Other provider keys
and the Forge owner token are removed from that context. The helper returns likely
syntax/import/dependency corrections and saves them with the run. It never installs
packages or executes the returned text. Model suggestions are not verification.
This helper is separate from the selected planner/coder/reviewer model.
