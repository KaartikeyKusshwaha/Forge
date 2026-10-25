# Model connections and permissions

Open the extension's **Connection settings**, then **Models & API keys**. Keys
are managed only in extension settings and the owner-authenticated loopback API.
GitHub-page scripts cannot list keys, configure profiles, or approve API spending.

## Separate connection options

- **API key:** paste a key; Forge recognizes OpenRouter (`sk-or-`) and Groq
  (`gsk_`) prefixes, verifies access, reads available text/tool models, and picks
  a compatible default. OpenRouter prefers `thinkingmachines/inkling:free`.
  Unknown/ambiguous formats request an endpoint or provider API example; there is no provider picker and Forge never probes a secret across multiple providers.
- **Endpoint:** use a provider endpoint and its key, or an OpenAI-compatible local HTTP server on loopback ending in `/v1`. Additional public HTTPS endpoints can be used through compatible Chat Completions, Responses, and Messages adapters after destination consent. Local endpoints need no key. A local proxy must
  not forward to a paid service: Forge cannot inspect the billing behind a proxy.
- **CLI / environment:** paste curl, Python, JavaScript, JSON or environment-assignment examples. Forge extracts endpoint, key, model, and variable references without executing the example. Missing variables prompt for a value, saved in the protected local integration profile and available on subsequent connections. Existing environment/`.env` values can also be read. No global shell profile is modified.

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


## Broad provider compatibility and guided setup (0.5)

Normal setup is deterministic and requires no second AI API. Prefix detection
covers OpenRouter, Groq, NVIDIA, Cerebras, Anthropic, Google AI and recognizable
OpenAI key variants. Opaque keys require a destination from the provider's example.
Examples for DeepSeek, Together, Fireworks, SambaNova, Mistral, Moonshot, SiliconFlow,
xAI, DeepInfra, MiniMax and BigModel are covered by parser fixtures. These are format
coverage tests, not live integration guarantees for every provider/account.

The runtime adapters support OpenAI-compatible Chat Completions, Responses, and
Anthropic-style Messages. Gemini URLs normalize to Google's compatibility endpoint.
Providers must expose a compatible model catalog. Other formats (including custom
OAuth flows, Azure deployment-specific APIs, AWS SigV4, query-auth-only services,
non-model APIs, and endpoints without compatible discovery) need dedicated adapters
and stop with a specific explanation. There is no claim of supporting every API.

Unrecognized remote destinations ask for consent before credentials leave the
backend. HTTPS and public DNS resolution are checked, and redirects are disabled.
Generic model catalogs usually lack prices and do not always prove key validity.
For these profiles, free-only mode explicitly requires owner confirmation of
provider-side no-charge limits; Forge cannot independently verify that policy.
Paid modes require owner-supplied input/output token rates and provider-side caps.
Reservations use those estimates and retain uncertain costs. OpenRouter's verified
zero-price routes and routing ceilings remain the stricter path for free usage.
There are no autonomous account signups, billing changes or credit purchases.

A user's own Groq Free profile can serve as an optional setup helper; it is never
a bundled developer key. An active Groq profile can be reused, or users can configure
a separate assistant key. The helper sees endpoint structure, model names and
variable names, not raw code or extracted provider secrets. It suggests information
only; it cannot create endpoints, authorize installations or change usage policies.

If a local runtime is missing, the panel offers explicit setup actions. Windows
WinGet can install Ollama; fixed actions can launch its local server or download an
Ollama model. Each action requires a user click approving that exact device change.
Credentials are stripped from the child environment. No pasted command is executed,
no Docker is installed, and no repository dependency is installed on the user's host.
Other systems/runtime installers show a manual setup path. Install/download tests
are mocked; no runtime was installed on the user's device during development.


Version 0.5.1 scopes saved environment bindings to their endpoint, expands JSON/native authentication-header parsing, and retries connection after an approved local setup action completes. The retry does not approve subsequent installation or download steps.
