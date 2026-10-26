"""Parse provider examples as data. No supplied code or shell command is executed."""

import ast
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values

from forge.policy import PolicyError

PREFIXES = {
    "sk-or-": "https://openrouter.ai/api/v1",
    "gsk_": "https://api.groq.com/openai/v1",
    "nvapi-": "https://integrate.api.nvidia.com/v1",
    "csk-": "https://api.cerebras.ai/v1",
    "sk-ant-": "https://api.anthropic.com/v1",
    "AIza": "https://generativelanguage.googleapis.com/v1beta/openai",
    "sk-proj-": "https://api.openai.com/v1",
    "sk-svcacct-": "https://api.openai.com/v1",
}


# Variable names identify a provider without sending credentials to guesses.
# Endpoint/code examples remain the fallback for ambiguous keys.
ENV_ENDPOINTS = {
    "OPENROUTER_API_KEY": "https://openrouter.ai/api/v1",
    "GROQ_API_KEY": "https://api.groq.com/openai/v1",
    "OPENAI_API_KEY": "https://api.openai.com/v1",
    "ANTHROPIC_API_KEY": "https://api.anthropic.com/v1",
    "GEMINI_API_KEY": "https://generativelanguage.googleapis.com/v1beta/openai",
    "GOOGLE_API_KEY": "https://generativelanguage.googleapis.com/v1beta/openai",
    "DEEPSEEK_API_KEY": "https://api.deepseek.com",
    "FIREWORKS_API_KEY": "https://api.fireworks.ai/inference/v1",
    "XAI_API_KEY": "https://api.x.ai/v1",
    "MISTRAL_API_KEY": "https://api.mistral.ai/v1",
    "ZAI_API_KEY": "https://api.z.ai/api/paas/v4",
    "NVIDIA_API_KEY": "https://integrate.api.nvidia.com/v1",
    "CEREBRAS_API_KEY": "https://api.cerebras.ai/v1",
}


def endpoint_base(value):
    url = urlparse(value.strip().rstrip("/"))
    if url.username or url.password or url.fragment or url.query or url.scheme not in {"https", "http"}:
        raise PolicyError("Use an endpoint without credentials, query parameters, or fragments.")
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if not url.hostname or (not local and url.scheme != "https"):
        raise PolicyError("Remote provider endpoints must use HTTPS.")
    path = url.path.rstrip("/")
    if url.hostname == "generativelanguage.googleapis.com":
        path = "/v1beta/openai"
    else:
        path = re.sub(r"/(chat/completions|messages|models|responses)$", "", path)
        if local and url.port == 11434 and path in {"", "/api/chat", "/api/generate"}:
            path = "/v1"
        elif not path and url.hostname != "api.deepseek.com":
            path = "/v1"
    return f"{url.scheme}://{url.netloc}{path}", local


def validate_remote(endpoint):
    endpoint, local = endpoint_base(endpoint)
    if local:
        return endpoint
    host = urlparse(endpoint).hostname
    try:
        addresses = socket.getaddrinfo(host, urlparse(endpoint).port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise PolicyError(
            "Provider hostname could not be resolved. Check the endpoint and your connection."
        ) from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise PolicyError("Remote endpoints must resolve to public addresses. Use loopback for local models.")
    return endpoint


def parse_example(key="", endpoint="", code="", environment="", supplied=None):
    """Extract literal configuration from common Python, JS, JSON and curl examples."""
    supplied = supplied or {}
    if len(code) > 30000:
        raise PolicyError("Provider example is too long.")
    literals = []
    try:
        tree = ast.parse(code)
        literals = [
            n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
    except SyntaxError:
        pass
    urls = re.findall(r"https?://[^\s\"'`<>\\)]+", code)
    relevant = [
        u
        for u in urls
        if any(x in u for x in ("/v1", "/v4", "/chat", "/messages", "/models", "/openai", ":11434"))
    ]
    if not relevant and len(urls) == 1:
        relevant = urls
    if not endpoint and relevant:
        bases = list(dict.fromkeys(endpoint_base(u)[0] for u in relevant))
        if len(bases) > 1:
            return {
                "needs": "endpoint",
                "message": "The example contains multiple service endpoints. Enter the endpoint you want Forge to use.",
                "urls": bases,
            }
        endpoint = bases[0]
    key_patterns = [
        r"(?m)(?:export\s+|set\s+|\$env:)?[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN)\s*=\s*[\"']?([^\s\"';]+)",
        r"(?i)(?:api_key|apiKey|apikey|x-api-key|x-goog-api-key)[\"']?\s*[=:]\s*[\"']([^\"']+)",
        r"(?i)(?:x-api-key|x-goog-api-key)\s*:\s*([^\s\"']+)",
        r"(?i)(?:authorization\s*:\s*bearer|bearer)\s+([^\s\"'`]+)",
        r"(?i)[\"'](?:x-api-key|api-key|x-goog-api-key)[\"']\s*:\s*[\"']([^\"']+)",
    ]
    if not key:
        for pattern in key_patterns:
            match = re.search(pattern, code)
            if match:
                key = match[1]
                break
    envs = re.findall(
        r"(?:\$\{?|process\.env\.|os\.environ\[?[\"']?|(?:getenv|environ\.get)\([\"'])([A-Z][A-Z0-9_]{2,})",
        code,
    )
    envs.extend(re.findall(r"\b([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN))\b", key))
    if environment:
        envs.insert(0, environment)
    envs = list(dict.fromkeys(e for e in envs if "KEY" in e or "TOKEN" in e))
    model = next((m[1] for m in [re.search(r"(?:[\"']?model[\"']?)\s*[:=]\s*[\"']([^\"']+)", code)] if m), "")
    placeholders = {
        "your_api_key",
        "your_key",
        "api_key",
        "your-api-key",
        "<api_key>",
        "<your_api_key>",
        "your_groq_api_key",
        "your_openrouter_api_key",
    }
    if (
        key.lower() in placeholders
        or key in {"+", "{", "None", "null"}
        or key.startswith(("$", "${", "%"))
        or "YOUR_" in key
        or "_API_KEY" in key
    ):
        key = ""
    if not key and envs:
        values = dotenv_values(".env")
        for name in envs:
            key = supplied.get(name) or os.environ.get(name) or values.get(name) or ""
            if key:
                break
        if not key:
            return {
                "needs": "environment",
                "variables": envs,
                "endpoint": endpoint,
                "model": model,
                "message": f"The example references {', '.join(envs)}. Enter the missing key below and approve saving it for this Forge integration.",
            }
    if not endpoint and (key.startswith("cfut_") or "CLOUDFLARE" in code):
        from forge.cloudflare import endpoint as cloudflare_endpoint

        account = supplied.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        match = re.search(r"CLOUDFLARE_ACCOUNT_ID[\"']?\s*[=:]\s*[\"']?([a-fA-F0-9]{32})", code)
        account = account or (match[1] if match else "")
        if not account:
            return {
                "needs": "environment",
                "variables": ["CLOUDFLARE_ACCOUNT_ID"],
                "message": "Cloudflare detected. Enter your Account ID to connect this token to Workers AI.",
            }
        endpoint = cloudflare_endpoint(account)
    if not endpoint:
        names = set(envs) | set(re.findall(r"\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN)\b", code))
        matches = {ENV_ENDPOINTS[n] for n in names if n in ENV_ENDPOINTS}
        if len(matches) == 1:
            endpoint = matches.pop()
    if not endpoint:
        endpoint = next((base for prefix, base in PREFIXES.items() if key.startswith(prefix)), "")
    if not endpoint:
        return {
            "needs": "endpoint",
            "message": "This key does not uniquely identify its provider. Paste the provider's endpoint or curl/Python/JavaScript API example. Your key has not been sent anywhere.",
        }
    endpoint, local = endpoint_base(endpoint)
    if key.startswith("cfut_") and urlparse(endpoint).hostname not in {
        "api.cloudflare.com",
        "gateway.ai.cloudflare.com",
    }:
        raise PolicyError("The Cloudflare token and supplied endpoint identify different services.")
    detected = next((base for prefix, base in PREFIXES.items() if key.startswith(prefix)), None)
    if detected and endpoint_base(detected)[0] != endpoint:
        raise PolicyError(
            "The key format and supplied endpoint identify different services. Check the example before sending credentials."
        )
    if not key and not local:
        return {
            "needs": "key",
            "endpoint": endpoint,
            "message": "This remote API needs a key. Paste it in the password field; Forge will keep it on this device.",
        }
    if len(key) > 4096:
        raise PolicyError(
            "The extracted credential is too long. Check whether an entire code block was pasted into the key field."
        )
    protocol = (
        "anthropic"
        if ("api.anthropic.com" in endpoint or any("/messages" in u for u in relevant))
        else "responses"
        if ("responses.create" in code or any(u.endswith("/responses") for u in relevant))
        else "openai"
    )
    return {
        "key": key,
        "endpoint": endpoint,
        "local": local,
        "protocol": protocol,
        "model": model,
        "environment_names": envs,
        "literals": literals,
    }


def discover_compatible(endpoint, key, protocol="openai", model=""):
    endpoint = validate_remote(endpoint)
    from forge.cloudflare import discover as cloudflare_discover
    from forge.cloudflare import is_workers_ai

    if is_workers_ai(endpoint):
        return cloudflare_discover(endpoint, key, model)
    headers = {"Authorization": "Bearer " + key} if key else {}
    if protocol == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        response = httpx.get(endpoint + "/models", headers=headers, timeout=20, follow_redirects=False)
        if response.status_code in {404, 405}:
            if model and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", model):
                return {
                    "endpoint": endpoint,
                    "protocol": protocol,
                    "authenticated": False,
                    "discovery_basis": "Model supplied in the user's API example; first inference verifies access",
                    "models": [{"id": model, "name": model, "parameters": [], "prices": {}, "free": False}],
                }
            return {
                "needs": "unsupported_catalog",
                "message": "This service does not expose a compatible model catalog at /models. Authentication is not verified. Its protocol needs a discovery adapter before it can be connected safely.",
                "endpoint": endpoint,
            }
        response.raise_for_status()
        items = response.json().get("data", [])
        models = [
            {
                "id": m["id"],
                "name": m.get("name", m.get("display_name", m["id"])),
                "parameters": [],
                "context": m.get("context_length"),
                "prices": {},
                "free": False,
            }
            for m in items
            if isinstance(m.get("id"), str)
            and m.get("active", True)
            and not any(
                term in m["id"].lower()
                for term in (
                    "embedding",
                    "embed-",
                    "whisper",
                    "speech",
                    "tts",
                    "rerank",
                    "moderation",
                    "safeguard",
                    "prompt-guard",
                )
            )
        ]
        if not models:
            raise ValueError
        if model:
            models.sort(key=lambda m: m["id"] != model)
        else:
            models.sort(
                key=lambda m: (
                    not any(
                        t in m["id"].lower()
                        for t in (
                            "coder",
                            "deepseek",
                            "qwen",
                            "gpt-oss",
                            "gemini",
                            "claude",
                            "nemotron",
                            "kimi",
                            "glm",
                        )
                    ),
                    m["id"],
                )
            )
        return {"models": models}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise PolicyError(
            "The service did not return a valid model catalog. Check its endpoint, authentication and API compatibility. No inference call was sent."
        ) from None


def redacted_example(code):
    """Send Groq structural evidence only, never raw provider examples or credentials."""
    urls = re.findall(r"https?://[^\s\"'`<>\\)]+", code)
    safe_urls = []
    for value in urls:
        u = urlparse(value)
        route = "/".join(
            p
            for p in u.path.split("/")
            if p in {"v1", "v1beta", "v4", "openai", "chat", "completions", "messages", "models", "responses"}
        )
        safe_urls.append(
            f"{u.scheme}://{u.hostname}/{route}" if not u.username and not u.password else "[redacted URL]"
        )
    models = re.findall(r"(?:[\"']?model[\"']?)\s*[:=]\s*[\"']([^\"']+)", code)
    secret_literals = re.findall(
        r"(?i)(?:api_key|apiKey|token|x-api-key)[\"']?\s*[=:]\s*[\"']([^\"']+)", code
    )
    secret_literals += re.findall(r"(?i)bearer\s+([^\s\"']+)", code)
    models = [
        m
        for m in models
        if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,150}", m)
        and not m.startswith(("sk-", "gsk_", "nvapi-"))
        and not any(secret and secret in m for secret in secret_literals)
    ]
    return {
        "urls": safe_urls[:5],
        "model_literals": models[:5],
        "environment_names": re.findall(r"\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN)\b", code)[:10],
        "signals": [
            word
            for word in (
                "OpenAI",
                "Anthropic",
                "genai",
                "base_url",
                "baseURL",
                "messages",
                "chat.completions",
                "curl",
                "requests",
            )
            if word in code
        ],
    }


def groq_helper(config):
    from forge.models import ModelVault, protect

    vault = ModelVault(config)
    with vault.connect() as db:
        row = db.execute("SELECT value FROM settings WHERE name='setup_helper'").fetchone()
    candidate = vault.read(row[0]) if row else None
    if not candidate:
        profiles = vault.list()["profiles"]
        automatic = next(
            (p for p in profiles if p["provider"] == "groq-free" and p["groq_confirmed"] and p.get("active")),
            None,
        )
        if automatic:
            candidate = vault.read(automatic["id"])
    key = ""
    if candidate and candidate["provider"] == "groq-free" and candidate["groq_confirmed"]:
        key = protect(candidate["key"], True)
    if not key:
        legacy = dotenv_values(config.data_dir / "provider-backups/before-inkling.env")
        if (
            legacy.get("FORGE_LLM_PROVIDER") == "groq-free"
            and legacy.get("FORGE_GROQ_FREE_PLAN_CONFIRMED", "").lower() == "true"
        ):
            key = legacy.get("FORGE_LLM_API_KEY", "")
    if not key:
        return None
    helper = config.model_copy(deep=True)
    helper.llm_provider = "groq-free"
    helper.llm_base_url = "https://api.groq.com/openai/v1"
    helper.llm_model = "auto"
    helper.llm_api_key = key
    helper.groq_free_plan_confirmed = True
    helper.model_profile_id = ""
    helper.model_usage_mode = "free_only"
    helper.max_calls = 1
    helper.max_tokens = 100000
    return helper


def prepare_connection(body, config, vault):
    """Return a public setup prompt or a saved profile. Never echo input keys."""
    from forge.models import protect

    # Saved variable names are integration-local: API_KEY on one service must
    # never silently select another service's credential.
    if body.account_id:
        from forge.cloudflare import endpoint as cloudflare_endpoint

        target_endpoint = cloudflare_endpoint(body.account_id)
        if body.endpoint and endpoint_base(body.endpoint)[0] != target_endpoint:
            raise PolicyError("Cloudflare Account ID does not match the supplied endpoint.")
        body.endpoint = target_endpoint
    initial = parse_example(
        body.api_key, body.endpoint, body.command, body.environment, body.environment_values
    )
    target = initial.get("endpoint", "")
    target = endpoint_base(target)[0] if target else ""
    bindings = {}
    for profile in vault.list()["profiles"]:
        if target and profile.get("endpoint") == target and profile.get("environment_names"):
            record = vault.read(profile["id"])
            for name in record["environment_names"]:
                bindings.setdefault(name, set()).add(protect(record["key"], True))
    values = {name: next(iter(keys)) for name, keys in bindings.items() if len(keys) == 1}
    values.update(body.environment_values)
    parsed = parse_example(body.api_key, body.endpoint, body.command, body.environment, values)
    if parsed.get("needs"):
        return {"setup": parsed}
    endpoint, key = parsed["endpoint"], parsed["key"]
    local = parsed["local"]
    known = {"https://openrouter.ai/api/v1": "openrouter-free", "https://api.groq.com/openai/v1": "groq-free"}
    provider = known.get(endpoint)
    if provider == "groq-free" and body.mode != "free_only":
        provider = (
            None  # Paid Groq profiles use explicit generic billing controls, never Free-plan assumptions.
        )
    if not local and not provider and not body.endpoint_consent:
        return {
            "setup": {
                "needs": "endpoint_consent",
                "endpoint": endpoint,
                "message": f"Forge detected {urlparse(endpoint).hostname}. Approve sending your key only to this endpoint to verify access and discover models.",
            }
        }
    if provider == "groq-free" and body.mode == "free_only":
        body.groq_confirmed = True
    if local:
        from forge.models import discover_local

        try:
            _, models = discover_local(endpoint)
        except PolicyError:
            return {
                "setup": {
                    "needs": "local_runtime",
                    "endpoint": endpoint,
                    "message": "No compatible local model catalog was found. Start your local model server, or set up Ollama below, then retry. This does not install anything automatically.",
                }
            }
        pid = vault.save("", body.label, "local", body.mode, body.budget_usd, False, endpoint=endpoint)
    elif provider:
        pid = vault.save(key, body.label, provider, body.mode, body.budget_usd, body.groq_confirmed)
    else:
        result = discover_compatible(endpoint, key, parsed["protocol"], parsed["model"])
        if result.get("needs"):
            return {"setup": result}
        if body.mode == "free_only":
            rates = {"prompt": 0, "completion": 0}
        elif body.mode in {"limited", "unlimited"}:
            rates = {}
        else:
            if not body.billing_guard_confirmed or body.input_price is None or body.output_price is None:
                return {
                    "setup": {
                        "needs": "pricing",
                        "endpoint": endpoint,
                        "message": "This endpoint does not expose verified pricing. Enter conservative input/output prices per million tokens and confirm a matching provider-side spending limit. Forge reserves these estimates; it cannot enforce the remote provider's billing.",
                    }
                }
            rates = {"prompt": body.input_price / 1_000_000, "completion": body.output_price / 1_000_000}
        pid = vault.save_compatible(
            key,
            endpoint,
            parsed["protocol"],
            [m for m in result["models"] if body.mode != "free_only" or not m.get("requires_paid_plan")],
            body.label or result.get("provider_name", ""),
            body.mode,
            body.budget_usd,
            rates,
            parsed["environment_names"],
        )
    record = vault.read(pid)
    record["environment_names"] = parsed["environment_names"]
    record["call_limit"] = body.call_limit
    record["token_limit"] = body.token_limit
    if parsed["model"]:
        if parsed["model"] in {m["id"] for m in record["models"]}:
            record["model"] = parsed["model"]
    with vault.connect() as db:
        db.execute("UPDATE profiles SET data=? WHERE id=?", (json.dumps(record), pid))
    if body.activate:
        vault.activate(pid, verify=False)
    return vault.list()


def assist(config, code, use_connected=False):
    from forge.llm import Provider

    helper = config.model_copy(deep=True) if use_connected and config.llm_ready else groq_helper(config)
    if not helper:
        return {
            "message": "Configure your own Groq Free setup assistant below for help interpreting examples."
        }
    evidence = redacted_example(code)
    result = Provider(helper, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False).ask(
        "setup-helper",
        "Interpret only these redacted configuration signals. Return JSON: summary:string, endpoint:string, model:string, steps:array of strings. Do not invent URLs, models, keys, or install commands. No action is authorized. Identify missing information.",
        evidence,
    )
    # A language model cannot invent a credential destination or authorize setup actions.
    allowed_urls = evidence["urls"]
    allowed_models = evidence["model_literals"]
    return {
        "summary": str(result.get("summary", ""))[:2000],
        "endpoint": result.get("endpoint") if result.get("endpoint") in allowed_urls else "",
        "model": result.get("model") if result.get("model") in allowed_models else "",
        "steps": [str(x)[:500] for x in result.get("steps", [])[:8]],
    }
