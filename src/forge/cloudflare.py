"""Workers AI catalog discovery with OpenAI-compatible inference."""

import re

import httpx

from forge.policy import PolicyError

BASE = "https://api.cloudflare.com/client/v4/accounts/"
PREFERRED = (
    "@cf/zai-org/glm-4.7-flash",
    "@cf/qwen/qwen2.5-coder-32b-instruct",
    "@cf/openai/gpt-oss-120b",
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
)
# Cloudflare's documented paid-only frontier models. Catalog metadata takes
# precedence when the API also supplies a paid-plan property.
PAID_ONLY = {
    "@cf/moonshotai/kimi-k2.6",
    "@cf/moonshotai/kimi-k2.7-code",
    "@cf/zai-org/glm-5.2",
    "@cf/zai-org/glm-5.3",
    "@cf/zai-org/glm-5.3-flash",
    "@cf/deepseek-ai/deepseek-v4-flash-0731",
    "@cf/deepseek-ai/deepseek-v4-pro-0813",
}


def endpoint(account_id):
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account_id):
        raise PolicyError("Cloudflare Account ID must contain 32 hexadecimal characters.")
    return BASE + account_id + "/ai/v1"


def is_workers_ai(value):
    return bool(re.fullmatch(re.escape(BASE) + r"[a-fA-F0-9]{32}/ai/v1", value))


def discover(base, token, selected=""):
    if not is_workers_ai(base):
        raise PolicyError("Use the official account-scoped Cloudflare Workers AI endpoint.")
    models = []
    try:
        for page in range(1, 11):
            response = httpx.get(
                base.removesuffix("/v1") + "/models/search",
                headers={"Authorization": "Bearer " + token},
                params={"page": page, "per_page": 100},
                timeout=30,
                follow_redirects=False,
            )
            if response.status_code in {401, 403}:
                raise PolicyError(
                    "Cloudflare rejected this account/token combination. Grant Workers AI Read permission for the selected account."
                )
            response.raise_for_status()
            data = response.json()
            if not data.get("success") or not isinstance(data.get("result"), list):
                raise ValueError
            for item in data["result"]:
                if item.get("task", {}).get("name", "").lower() != "text generation":
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not name.startswith("@cf/"):
                    continue
                props = {p["property_id"]: p.get("value") for p in item.get("properties", [])}
                paid = name in PAID_ONLY or str(props.get("requires_paid_plan", "")).lower() == "true"
                params = (
                    ["tools", "tool_choice"]
                    if str(props.get("function_calling", "")).lower() == "true"
                    else []
                )
                models.append(
                    {
                        "id": name,
                        "name": name,
                        "parameters": params,
                        "context": props.get("context_window"),
                        "prices": {},
                        "free": False,
                        "free_allocation": not paid,
                        "requires_paid_plan": paid,
                    }
                )
            if len(data["result"]) < 100:
                break
        if not models:
            raise ValueError
        models.sort(
            key=lambda m: (
                m["id"] != selected if selected else False,
                PREFERRED.index(m["id"]) if m["id"] in PREFERRED else len(PREFERRED),
                m["id"],
            )
        )
        return {"models": models, "provider_name": "Cloudflare Workers AI", "authenticated": True}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise PolicyError(
            "Could not read the Cloudflare Workers AI catalog. Check the account, token permissions and network. No inference call was sent."
        ) from None
