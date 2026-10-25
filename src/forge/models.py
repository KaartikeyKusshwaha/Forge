"""Owner-local model profiles and explicit, bounded API spending."""

import base64
import ctypes
import json
import math
import os
import shlex
import sqlite3
import time
import uuid
from urllib.parse import urlparse

import httpx

from forge.policy import PolicyError

ENDPOINTS = {"openrouter-free": "https://openrouter.ai/api/v1", "groq-free": "https://api.groq.com/openai/v1"}


def local_endpoint(endpoint):
    url = urlparse(endpoint)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path.rstrip("/") != "/v1"
    ):
        raise PolicyError("A local model endpoint must be a loopback HTTP URL ending in /v1.")
    return endpoint.rstrip("/")


def discover_local(endpoint):
    endpoint = local_endpoint(endpoint)
    try:
        response = httpx.get(endpoint + "/models", timeout=15)
        response.raise_for_status()
        models = [
            {
                "id": m["id"],
                "name": m["id"],
                "parameters": [],
                "context": None,
                "prices": {"prompt": 0, "completion": 0},
                "free": True,
            }
            for m in response.json()["data"]
            if isinstance(m.get("id"), str)
        ]
        if not models:
            raise ValueError
        return "local", models
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise PolicyError("The local endpoint did not return an OpenAI-compatible model list.") from None


def connection_input(key, provider="auto", environment="", endpoint="", command=""):
    if command:
        if len(command) > 12000:
            raise PolicyError("Command configuration is too long.")
        try:
            parts = shlex.split(command.replace("\\\n", " "))
        except ValueError:
            raise PolicyError("The pasted command has unmatched quotes. Nothing was executed.") from None
        if not parts or parts[0] not in {"curl", "curl.exe"}:
            raise PolicyError("Paste a curl example. Shell scripts and other commands are not executed.")
        urls = [p for p in parts if p.startswith("https://")]
        if len(urls) != 1:
            raise PolicyError("Expected exactly one official provider URL.")
        endpoint = urls[0]
        auth = [p for p in parts if p.lower().startswith("authorization: bearer ")]
        if auth:
            key = auth[0].split(" ", 2)[2].strip()
    if environment and not key:
        from dotenv import dotenv_values

        key = os.environ.get(environment) or dotenv_values(".env").get(environment) or ""
        if not key:
            raise PolicyError(
                f"{environment} is not set in the local Forge service. Choose API key and paste your key, or paste a curl example containing its Bearer key. Selecting a variable does not create it."
            )
    if endpoint:
        if endpoint.startswith("http://"):
            local_endpoint(endpoint)
            return "", "local"
        matches = [
            name
            for name, base in ENDPOINTS.items()
            if endpoint.rstrip("/") in {base, base + "/chat/completions", base + "/models"}
        ]
        if not matches:
            raise PolicyError(
                "Only exact official OpenRouter and Groq endpoints are supported. No request was sent to the supplied URL."
            )
        provider = matches[0]
    for variable in ("OPENROUTER_API_KEY", "GROQ_API_KEY"):
        if key in {"$" + variable, "${" + variable + "}", "%" + variable + "%"}:
            from dotenv import dotenv_values

            key = os.environ.get(variable) or dotenv_values(".env").get(variable) or ""
            if not key:
                raise PolicyError(
                    f"The pasted command references {variable}, but it is not set in the local service. Use API key mode or replace the placeholder with your real key in settings."
                )
    return key.strip(), provider


def protect(value, decrypt=False):
    if os.name != "nt":
        return value
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

    raw = base64.b64decode(value) if decrypt else value.encode()
    buffer = ctypes.create_string_buffer(raw)
    source, target = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise PolicyError("Could not access the current Windows user's protected model key.")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode() if decrypt else base64.b64encode(result).decode()
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def discover(key, provider="auto", mode="free_only", groq_confirmed=False):
    detected = (
        "openrouter-free" if key.startswith("sk-or-") else "groq-free" if key.startswith("gsk_") else None
    )
    if provider == "auto":
        provider = detected
    elif detected and detected != provider:
        raise PolicyError("The key prefix belongs to a different provider.")
    if provider not in ENDPOINTS:
        raise PolicyError(
            "This key format is ambiguous or unsupported. Choose OpenRouter or Groq explicitly; keys are never probed across providers."
        )
    endpoint = ENDPOINTS[provider]
    headers = {"Authorization": "Bearer " + key}
    try:
        if provider == "openrouter-free":
            check = httpx.get(endpoint + "/key", headers=headers, timeout=20)
            if check.status_code != 200:
                raise PolicyError("OpenRouter rejected the API key. Check its permissions and expiry.")
        else:
            if mode == "free_only" and not groq_confirmed:
                raise PolicyError(
                    "Free usage selected. Confirm this Groq account has no paid billing enabled."
                )
        response = httpx.get(endpoint + "/models", headers=headers, timeout=20)
        response.raise_for_status()
        models = []
        for item in response.json()["data"]:
            if provider == "groq-free":
                if not item.get("active", True) or any(
                    t in item["id"].lower() for t in ("whisper", "tts", "speech", "guard", "embed")
                ):
                    continue
                prices = {"prompt": "0", "completion": "0"} if mode == "free_only" else {}
                parameters = ["response_format"]
            else:
                prices = item.get("pricing", {})
                parameters = item.get("supported_parameters", [])
                inputs = item.get("architecture", {}).get("input_modalities", ["text"])
                if "text" not in inputs or "tools" not in parameters:
                    continue
            try:
                rates = {k: float(v) for k, v in prices.items()}
            except (ValueError, TypeError):
                continue  # Unbounded/dynamic pricing cannot be authorized here.
            if mode not in {"limited", "unlimited"} and not {"prompt", "completion"}.issubset(rates):
                continue
            if any(not math.isfinite(v) or v < 0 for v in rates.values()):
                continue
            free = bool(rates) and all(v == 0 for v in rates.values())
            if provider == "openrouter-free" and free and not item["id"].endswith(":free"):
                continue
            if mode == "free_only" and not free:
                continue
            if not free and any(
                v != 0
                for k, v in rates.items()
                if k not in {"prompt", "completion", "input_cache_read", "input_cache_write"}
            ):
                continue
            models.append(
                {
                    "id": item["id"],
                    "name": item.get("name", item["id"]),
                    "parameters": parameters,
                    "context": item.get("context_length", item.get("context_window")),
                    "prices": rates,
                    "free": free,
                }
            )
        order = (
            "thinkingmachines/inkling:free",
            "qwen/qwen3.8-27b",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "openai/gpt-oss-120b",
        )
        models.sort(key=lambda m: (order.index(m["id"]) if m["id"] in order else 99, not m["free"], m["id"]))
        if not models:
            raise PolicyError("No supported text/tool model meets this profile's usage policy.")
        return provider, models
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        raise PolicyError(
            "Cannot verify provider access and current model pricing. No inference call was made."
        ) from None


class ModelVault:
    def __init__(self, config):
        self.config = config
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = config.data_dir / "model-profiles.sqlite3"
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS spend(id TEXT PRIMARY KEY,profile TEXT,run_id TEXT,role TEXT,amount REAL,status TEXT,created REAL);
                CREATE TABLE IF NOT EXISTS usage_calls(id TEXT PRIMARY KEY,profile TEXT,tokens INTEGER,created REAL);""")
        if os.name != "nt":
            self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def read(self, profile_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if not row:
            raise PolicyError("Model profile no longer exists.")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            active = db.execute("SELECT value FROM settings WHERE name='active'").fetchone()
            records = db.execute("SELECT id,data FROM profiles").fetchall()
            amounts = dict(
                db.execute(
                    "SELECT profile,SUM(amount) FROM spend WHERE status NOT IN ('denied','expired','cancelled') GROUP BY profile"
                )
            )
        with self.connect() as db:
            usage = {
                row[0]: {"calls": row[1], "tokens": row[2]}
                for row in db.execute(
                    "SELECT profile,COUNT(*),COALESCE(SUM(tokens),0) FROM usage_calls GROUP BY profile"
                )
            }
        return {
            "profiles": [
                {
                    k: v
                    for k, v in {
                        **json.loads(raw),
                        "id": pid,
                        "spent_usd": amounts.get(pid, 0),
                        "usage": usage.get(pid, {"calls": 0, "tokens": 0}),
                        "active": bool(active and active[0] == pid),
                    }.items()
                    if k != "key"
                }
                for pid, raw in records
            ]
        }

    def save(self, key, label, provider, mode, budget, groq_confirmed, endpoint=""):
        if provider == "local":
            provider, models = discover_local(endpoint)
        else:
            provider, models = discover(key, provider, mode, groq_confirmed)
        pid = uuid.uuid4().hex
        data = {
            "label": label
            or {"openrouter-free": "OpenRouter", "groq-free": "Groq", "local": "Local endpoint"}[provider],
            "endpoint": endpoint if provider == "local" else ENDPOINTS[provider],
            "provider": provider,
            "model": models[0]["id"],
            "models": models,
            "mode": mode,
            "budget_usd": budget,
            "groq_confirmed": groq_confirmed,
            "key": protect(key),
        }
        with self.connect() as db:
            db.execute("INSERT INTO profiles VALUES(?,?)", (pid, json.dumps(data)))
        return pid

    def activate(self, pid, model=None, verify=True):
        data = self.read(pid)
        if verify:
            if data.get("compatible"):
                from forge.integrations import discover_compatible

                result = discover_compatible(
                    data["endpoint"], protect(data["key"], True), data["protocol"], data["model"]
                )
                if "models" not in result:
                    raise PolicyError(result["message"])
                models = [
                    {**m, "prices": data["rates"], "free": data["mode"] == "free_only"}
                    for m in result["models"]
                ]
            elif data["provider"] == "local":
                _, models = discover_local(data["endpoint"])
            else:
                _, models = discover(
                    protect(data["key"], True), data["provider"], data["mode"], data["groq_confirmed"]
                )
            data["models"] = models
        chosen = model or data["model"]
        if chosen not in {m["id"] for m in data["models"]}:
            raise PolicyError("Selected model is unavailable under this profile's usage policy.")
        data["model"] = chosen
        with self.connect() as db:
            db.execute("UPDATE profiles SET data=? WHERE id=?", (json.dumps(data), pid))
            db.execute("INSERT OR REPLACE INTO settings VALUES('active',?)", (pid,))
        self.apply(pid, data)

    def apply(self, pid, data):
        self.config.llm_provider = data["provider"]
        self.config.llm_base_url = (
            data["endpoint"]
            if data["provider"] == "local" or data.get("compatible")
            else ENDPOINTS[data["provider"]]
        )
        self.config.llm_model = data["model"]
        self.config.llm_api_key = protect(data["key"], True)
        self.config.groq_free_plan_confirmed = data["groq_confirmed"]
        self.config.model_profile_id = pid
        self.config.model_usage_mode = data["mode"]
        self.config.llm_protocol = data.get("protocol", "openai")

    def save_compatible(self, key, endpoint, protocol, models, label, mode, budget, rates, environment_names):
        pid = uuid.uuid4().hex
        data = {
            "label": label or urlparse(endpoint).hostname,
            "endpoint": endpoint,
            "provider": "compatible",
            "compatible": True,
            "protocol": protocol,
            "model": models[0]["id"],
            "models": [{**m, "prices": rates, "free": mode == "free_only"} for m in models],
            "mode": mode,
            "budget_usd": budget,
            "groq_confirmed": False,
            "rates": rates,
            "environment_names": environment_names,
            "key": protect(key),
            "billing_basis": "Owner-confirmed provider account controls and rates; not independently verified",
        }
        with self.connect() as db:
            db.execute("INSERT INTO profiles VALUES(?,?)", (pid, json.dumps(data)))
        return pid

    def load_active(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE name='active'").fetchone()
        if row:
            self.apply(row[0], self.read(row[0]))

    def delete(self, pid):
        with self.connect() as db:
            active = db.execute("SELECT value FROM settings WHERE name='active'").fetchone()
            if active and active[0] == pid:
                raise PolicyError("Activate another profile before removing the active profile.")
            db.execute("DELETE FROM profiles WHERE id=?", (pid,))
            db.execute("DELETE FROM settings WHERE name='setup_helper' AND value=?", (pid,))

    def reserve_usage(self, tokens):
        """Atomic lifetime limits shared by chat, setup and coding on this profile."""
        pid = self.config.model_profile_id
        if not pid or self.config.model_usage_mode != "limited":
            return None
        record = self.read(pid)
        uid = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            calls, used = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(tokens),0) FROM usage_calls WHERE profile=?", (pid,)
            ).fetchone()
            if calls >= record.get("call_limit", 100) or used + tokens > record.get("token_limit", 1000000):
                raise PolicyError(
                    "This profile's API call or token limit is reached. Increase its limits in Connection settings."
                )
            db.execute("INSERT INTO usage_calls VALUES(?,?,?,?)", (uid, pid, tokens, time.time()))
        return uid

    def settle_usage(self, uid, tokens):
        if uid and isinstance(tokens, int) and tokens >= 0:
            with self.connect() as db:
                db.execute("UPDATE usage_calls SET tokens=? WHERE id=?", (tokens, uid))

    def reserve(self, amount, role, run_id, cancelled):
        if self.config.model_usage_mode in {"unlimited", "limited"}:
            return None
        if not amount:
            return None
        pid = self.config.model_profile_id
        data = self.read(pid)
        if data["mode"] == "free_only":
            raise PolicyError("Paid calls are forbidden by the active profile.")
        sid = uuid.uuid4().hex
        status = "pending" if data["mode"] == "ask_paid" else "reserved"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE spend SET status='expired',amount=0 WHERE status='pending' AND created<?",
                (time.time() - 300,),
            )
            used = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM spend WHERE profile=? AND status NOT IN ('denied','expired','cancelled')",
                (pid,),
            ).fetchone()[0]
            if used + amount > data["budget_usd"]:
                raise PolicyError("The model profile's lifetime spending cap would be exceeded.")
            db.execute(
                "INSERT INTO spend VALUES(?,?,?,?,?,?,?)",
                (sid, pid, run_id, role, amount, status, time.time()),
            )
        if status == "pending":
            deadline = time.monotonic() + 300
            while True:
                if cancelled() or time.monotonic() > deadline:
                    with self.connect() as db:
                        db.execute(
                            "UPDATE spend SET status='expired',amount=0 WHERE id=? AND status IN ('pending','approved')",
                            (sid,),
                        )
                    raise PolicyError(
                        "Paid API permission expired or the run was cancelled. No model call was sent."
                    )
                with self.connect() as db:
                    state = db.execute("SELECT status FROM spend WHERE id=?", (sid,)).fetchone()[0]
                if state == "approved":
                    break
                if state != "pending":
                    raise PolicyError("Paid API request was declined. No model call was sent.")
                time.sleep(0.5)
        return sid

    def settle(self, sid, cost):
        if sid and isinstance(cost, (float, int)) and math.isfinite(cost) and cost >= 0:
            with self.connect() as db:
                row = db.execute("SELECT amount FROM spend WHERE id=?", (sid,)).fetchone()
                db.execute("UPDATE spend SET amount=?,status='settled' WHERE id=?", (cost, sid))
                if cost > row[0]:
                    raise PolicyError(
                        "Provider-reported cost exceeded the reserved amount. Further execution stopped."
                    )

    def pending(self):
        with self.connect() as db:
            db.execute(
                "UPDATE spend SET status='expired',amount=0 WHERE status='pending' AND created<?",
                (time.time() - 300,),
            )
            return {
                "requests": [
                    dict(zip(("id", "profile", "run_id", "role", "maximum_usd", "created"), row))
                    for row in db.execute(
                        "SELECT id,profile,run_id,role,amount,created FROM spend WHERE status='pending'"
                    )
                ]
            }

    def decide(self, sid, approve):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE spend SET status=?,amount=CASE WHEN ? THEN amount ELSE 0 END WHERE id=? AND status='pending' AND created>?",
                ("approved" if approve else "denied", approve, sid, time.time() - 300),
            ).rowcount
        if not changed:
            raise PolicyError("This spending request is no longer pending.")


def load_profiles(config):
    ModelVault(config).load_active()
    return config
