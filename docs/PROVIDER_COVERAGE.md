# Provider connections and usage permissions

Forge parses a key, endpoint or CLI/Python/JavaScript/JSON example without running
that example. No LLM or Groq credential is required for ordinary setup. Distinct
key prefixes identify OpenRouter, Groq, NVIDIA, Cerebras, Anthropic, Gemini and
OpenAI project/service keys. Provider-named variables additionally identify
DeepSeek, Mistral, Fireworks, xAI and Z.AI. Opaque key formats are shared by many
services: Forge asks for an endpoint or example instead of sending the key to
multiple companies. Models are discovered from the selected account's catalog,
not a static global list.

| Route | Connection path | Evidence / boundary |
| --- | --- | --- |
| OpenRouter | Distinct key; catalog and zero-price filtering | Multiple model families; model-specific access restrictions still apply |
| Groq | Distinct key; active text-model catalog | Usage selection is stored; no repeated Free-key prompt |
| Gemini | Distinct key or named variable; OpenAI compatibility endpoint | [Official compatibility guide](https://ai.google.dev/gemini-api/docs/openai) |
| DeepSeek | Named variable or provider example; Chat Completions, Responses or Anthropic format | [Official API guide](https://api-docs.deepseek.com/quick_start/agent_integrations/) |
| Anthropic | Distinct key or named variable; native Messages adapter | [Official compatibility documentation](https://platform.claude.com/docs/en/api/openai-sdk) |
| Mistral | Named variable or API example; compatible adapter | [Official migration guide](https://docs.mistral.ai/resources/migration-guides) |
| Fireworks | Named variable or API example; compatible adapter | [Official compatibility guide](https://docs.fireworks.ai/tools-sdks/openai-compatibility) |
| Z.AI | Named variable or API example; compatible adapter | [Official request example](https://docs.z.ai/guides/capabilities/mcp-call) |
| xAI | Named variable or API example; compatible Chat/Responses adapter | [Official API overview](https://docs.x.ai/overview) |
| NVIDIA / Cerebras | Distinct key prefix or provider example; compatible adapter | Catalog and endpoint validation required |
| Other compatible APIs | Paste the service's endpoint and example | OpenAI-compatible, native Messages and Responses adapters; an endpoint alone does not prove protocol compatibility |
| LiteLLM gateways | Paste your gateway endpoint, key and model | [Gateway documentation](https://docs.litellm.ai/docs/providers) covers provider-specific cloud integrations; gateway must be configured separately |
| Ollama / local compatible servers | Loopback endpoint and available models | Local-runtime setup can be requested in Connection settings |

## Three usage choices

- **Free usage:** verified zero-price models where the service exposes pricing.
  Otherwise this records the user's declaration that their provider account
  stops at its free allowance. Forge cannot change third-party account billing.
- **Limited API usage:** lifetime inference-call and conservative token limits
  are reserved atomically per profile across coding, chat and setup assistance.
  Known token usage settles the reservation; uncertain usage stays reserved.
  This mode does not promise a currency cap when a provider omits pricing.
- **Unlimited:** no Forge call/token or spending cap. Timeouts, bounded recovery,
  sandbox restrictions and repository-publication approval remain. Provider
  quotas and charges still apply. This choice does not purchase credits.

Existing advanced spending profiles remain readable. New connection UI presents
only the three choices above, with editable permissions on saved profiles.
An unavailable catalog can use the model explicitly supplied in the user's
example; the first inference call verifies model access. A successful catalog
response alone does not prove access to every listed model.

Normal configuration is deterministic. Optional assistance uses either the
user's connected model (with its selected policy) or a separate Groq setup key.
Only redacted configuration structure is sent for analysis. Suggestions cannot
authorize key destinations, run pasted commands, or change permissions.

These are supported adapter paths, not live verification of every vendor/model.
Azure deployment routing, AWS/Vertex service-account authentication, realtime,
image/audio/video APIs and arbitrary noncompatible APIs need dedicated adapters
or a configured gateway. Credentials stay with the owning installation. Public
releases contain no developer API key.
