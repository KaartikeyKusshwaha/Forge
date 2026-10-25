import asyncio
import hashlib
import hmac
import json
import threading
import time
from contextlib import asynccontextmanager
from functools import wraps
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from forge.actions import ActionsSandbox
from forge.config import Settings
from forge.github import GitHub, GitHubError
from forge.llm import free_models
from forge.models import ModelVault
from forge.policy import PolicyError, fingerprint
from forge.setup import AppSetup
from forge.store import Conflict, Store


class NewRun(BaseModel):
    repo: str = Field(max_length=200, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    issue: int = Field(ge=0, le=2**31)
    request: str = Field(default="", max_length=4000)
    mode: Literal["github", "demo"] = "github"
    profile: Literal["auto", "python", "typescript"] = "auto"
    request_key: str = Field(min_length=12, max_length=100)


class Approval(BaseModel):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    publish_consent: bool = False


class Revision(BaseModel):
    feedback: str = Field(min_length=10, max_length=4000)
    request_key: str = Field(min_length=12, max_length=100)


class SessionAction(BaseModel):
    action: Literal["end", "delete", "forget"]


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    request_key: str = Field(min_length=12, max_length=100)


class RepositoryRequest(BaseModel):
    repo: str = Field(max_length=200)
    enable: bool = False


class ModelConnection(BaseModel):
    api_key: str = Field(default="", repr=False)
    label: str = Field(default="", max_length=100)
    provider: Literal["auto", "openrouter-free", "groq-free"] = (
        "auto"  # Legacy clients only; UI has no picker.
    )
    mode: Literal["free_only", "limited", "unlimited", "ask_paid", "capped"] = "free_only"
    call_limit: int = Field(default=100, ge=1, le=1000000)
    token_limit: int = Field(default=1000000, ge=1000, le=1000000000)
    use_connected_model: bool = False
    budget_usd: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)
    groq_confirmed: bool = False
    activate: bool = True
    environment: str = Field(default="", max_length=100, pattern=r"^$|^[A-Z][A-Z0-9_]*$")
    endpoint: str = Field(default="", max_length=200)
    command: str = Field(default="", repr=False)
    environment_values: dict[str, str] = Field(default_factory=dict, repr=False, max_length=20)
    endpoint_consent: bool = False
    billing_guard_confirmed: bool = False
    input_price: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    output_price: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)


class UsagePolicy(BaseModel):
    mode: Literal["free_only", "limited", "unlimited"]
    call_limit: int = Field(default=100, ge=1, le=1000000)
    token_limit: int = Field(default=1000000, ge=1000, le=1000000000)


class ModelActivation(BaseModel):
    model: str | None = Field(default=None, max_length=200)


class SpendDecision(BaseModel):
    approve: bool


class LocalSetupAction(BaseModel):
    action: Literal["install_ollama", "start_ollama", "pull_model"]
    consent: bool = False
    model: str = Field(default="", max_length=100)


def create_app(config: Settings, store: Store | None = None) -> FastAPI:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = store or Store(config.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(title="Forge", version="0.7.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    app.state.store = db
    vault = ModelVault(config)
    from forge.device_setup import DeviceSetup

    device_setup = DeviceSetup()
    model_lock = threading.RLock()

    def model_serialized(function):
        @wraps(function)
        def locked(*args, **kwargs):
            with model_lock:
                return function(*args, **kwargs)

        return locked

    def authenticated(authorization: str = Header(default="")):
        if not config.owner_token or not hmac.compare_digest(authorization, "Bearer " + config.owner_token):
            raise HTTPException(401, "Connect the extension using the local owner token.")

    setup = AppSetup(config)
    setup.routes(app, authenticated)

    def get_run(run_id):
        try:
            return db.get(run_id)
        except KeyError:
            raise HTTPException(404, "Run not found.") from None

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        from fastapi.responses import JSONResponse

        # Pydantic's default error body includes rejected input, potentially a provider key.
        if request.url.path.startswith("/api/model-"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "Invalid model settings. Check provider, usage mode, spending cap, and field lengths."
                },
            )
        return JSONResponse(
            status_code=422,
            content={"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
        )

    @app.exception_handler(PolicyError)
    @app.exception_handler(GitHubError)
    async def policy_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"service": "forge", "version": "0.7.0", "status": "ok"}

    @app.get("/api/status", dependencies=[Depends(authenticated)])
    def status():
        return {
            "github": config.github_ready,
            "github_auth": config.github_auth,
            "model": config.llm_ready,
            "model_name": config.llm_model,
            "free_only": config.model_usage_mode == "free_only",
            "model_usage_mode": config.model_usage_mode,
            "provider": config.llm_provider,
            "demo": config.demo_enabled,
            "publishing": config.publish_enabled,
            "runner": ActionsSandbox.available(),
        }

    @app.get("/api/models", dependencies=[Depends(authenticated)])
    def models():
        return {"models": free_models(), "selection": config.llm_model, "paid_fallback": False}

    @app.get("/api/model-profiles", dependencies=[Depends(authenticated)])
    def model_profiles():
        return vault.list()

    @app.post("/api/model-profiles", dependencies=[Depends(authenticated)])
    @model_serialized
    def connect_model(body: ModelConnection):
        from forge.integrations import prepare_connection

        if body.activate and db.has_active_runs():
            raise Conflict("Wait for active runs to finish before changing the model connection.")
        if body.mode in {"ask_paid", "capped"} and body.budget_usd <= 0:
            raise HTTPException(422, "Set a positive lifetime spending cap for paid usage.")
        return prepare_connection(body, config, vault)

    @app.get("/api/setup-assistant", dependencies=[Depends(authenticated)])
    def setup_assistant_status():
        from forge.integrations import groq_helper

        return {"configured": groq_helper(config) is not None, "required": False}

    @app.get("/api/device-setup", dependencies=[Depends(authenticated)])
    def device_setup_status():
        return device_setup.status()

    @app.post("/api/device-setup", dependencies=[Depends(authenticated)])
    def device_setup_action(body: LocalSetupAction):
        return device_setup.start(body.action, body.consent, body.model)

    @app.post("/api/setup-assistant", dependencies=[Depends(authenticated)])
    def setup_assistant_connect(body: ModelConnection):
        if not body.api_key.startswith("gsk_"):
            raise HTTPException(422, "Use your own Groq key for the optional setup assistant.")
        pid = vault.save(body.api_key, "Setup assistant", "groq-free", "free_only", 0, body.groq_confirmed)
        record = vault.read(pid)
        record["setup_only"] = True
        with vault.connect() as connection:
            connection.execute("UPDATE profiles SET data=? WHERE id=?", (json.dumps(record), pid))
            connection.execute("INSERT OR REPLACE INTO settings VALUES('setup_helper',?)", (pid,))
        return {"configured": True, "required": False}

    @app.post("/api/setup-assistant/analyze", dependencies=[Depends(authenticated)])
    def setup_assistant_analyze(body: ModelConnection):
        from forge.integrations import assist

        return assist(config, body.command or body.endpoint, use_connected=body.use_connected_model)

    @app.post("/api/model-profiles/{profile_id}/policy", dependencies=[Depends(authenticated)])
    @model_serialized
    def update_policy(profile_id: str, body: UsagePolicy):
        if db.has_active_runs():
            raise Conflict("Wait for execution to stop before changing usage permissions.")
        record = vault.read(profile_id)
        record.update(mode=body.mode, call_limit=body.call_limit, token_limit=body.token_limit)
        if record["provider"] == "groq-free" and body.mode == "free_only":
            record["groq_confirmed"] = True
        if record.get("compatible") and body.mode == "free_only":
            record["rates"] = {"prompt": 0, "completion": 0}
        with vault.connect() as connection:
            connection.execute("UPDATE profiles SET data=? WHERE id=?", (json.dumps(record), profile_id))
        if any(p["id"] == profile_id and p["active"] for p in vault.list()["profiles"]):
            vault.apply(profile_id, record)
        return vault.list()

    @app.post("/api/model-profiles/{profile_id}/activate", dependencies=[Depends(authenticated)])
    @model_serialized
    def activate_model(profile_id: str, body: ModelActivation):
        if db.has_active_runs():
            raise Conflict("Wait for active runs to finish before switching profiles.")
        if vault.read(profile_id).get("setup_only"):
            raise Conflict(
                "This credential is reserved for setup assistance. Connect a separate coding profile."
            )
        vault.activate(profile_id, body.model)
        return vault.list()

    @app.delete("/api/model-profiles/{profile_id}", dependencies=[Depends(authenticated)])
    def delete_model(profile_id: str):
        vault.delete(profile_id)
        return vault.list()

    @app.get("/api/model-spending", dependencies=[Depends(authenticated)])
    def model_spending():
        return vault.pending()

    @app.post("/api/model-spending/{request_id}", dependencies=[Depends(authenticated)])
    def model_spend_decision(request_id: str, body: SpendDecision):
        vault.decide(request_id, body.approve)
        return vault.pending()

    @app.post("/api/conversations", status_code=201, dependencies=[Depends(authenticated)])
    def new_conversation(body: NewRun):
        GitHub.validate_repo(body.repo)
        if body.mode != "github":
            raise HTTPException(422, "Conversations require a repository context.")
        return db.create(
            body.repo,
            body.issue,
            dict(
                mode="github",
                conversation_only=True,
                request=body.request.strip(),
                title=f"Conversation · {body.repo}",
                checks=[],
                chat=[],
                usage={"calls": 0, "tokens": 0, "cost": 0},
            ),
            body.request_key,
            status="needs_input",
        )

    @app.post("/api/runs/{run_id}/session", dependencies=[Depends(authenticated)])
    def manage_session(run_id: str, body: SessionAction):
        get_run(run_id)
        return db.session_action(run_id, body.action)

    @app.post("/api/runs/{run_id}/chat", dependencies=[Depends(authenticated)])
    @model_serialized
    def chat_run(run_id: str, body: ChatMessage):
        from forge.chat import prepare, reply

        if get_run(run_id).get("ended"):
            raise Conflict("This session has ended. Start a new conversation to continue.")
        if get_run(run_id)["mode"] == "demo":
            raise HTTPException(
                409, "Open Talk to Forge on a repository for live chat. The demo makes no model calls."
            )
        message = body.message.strip()
        if not message:
            raise HTTPException(422, "Type a message for Forge.")
        run, created = prepare(db, run_id, message, body.request_key)
        if created:
            threading.Thread(
                target=reply,
                args=(db, config.model_copy(deep=True), run_id, body.request_key),
                daemon=True,
                name="forge-chat-" + run_id[:8],
            ).start()
        return run

    @app.post("/api/runs/{run_id}/diagnose", dependencies=[Depends(authenticated)])
    def diagnose_run(run_id: str):
        from dotenv import dotenv_values

        from forge.llm import Provider
        from forge.models import protect

        run = get_run(run_id)
        if run["status"] not in {"failed", "needs_input", "stale", "awaiting_approval"}:
            raise Conflict("Wait for the run to finish before requesting diagnostics.")
        diagnostic = config.model_copy(deep=True)
        diagnostic.model_profile_id = ""
        diagnostic.model_usage_mode = "free_only"
        diagnostic.llm_provider = "groq-free"
        diagnostic.llm_base_url = "https://api.groq.com/openai/v1"
        diagnostic.llm_model = "auto"
        diagnostic.llm_api_key = ""
        diagnostic.groq_free_plan_confirmed = False
        secret_values = [config.llm_api_key, config.owner_token]
        for profile in vault.list()["profiles"]:
            record = vault.read(profile["id"])
            secret_values.append(protect(record["key"], True))
            if record["provider"] == "groq-free" and record["groq_confirmed"]:
                diagnostic.llm_api_key = protect(record["key"], True)
                diagnostic.groq_free_plan_confirmed = True
        if not diagnostic.llm_api_key:
            # Explicit legacy backup from the owner's requested Inkling switch.
            path = config.data_dir / "provider-backups/before-inkling.env"
            legacy = dotenv_values(path) if path.exists() else {}
            if (
                legacy.get("FORGE_LLM_PROVIDER") == "groq-free"
                and legacy.get("FORGE_GROQ_FREE_PLAN_CONFIRMED", "").lower() == "true"
            ):
                diagnostic.llm_api_key = legacy.get("FORGE_LLM_API_KEY", "")
                diagnostic.groq_free_plan_confirmed = True
        if not diagnostic.llm_api_key:
            raise HTTPException(
                409, "Save a confirmed Groq Free-plan profile to enable diagnostic suggestions."
            )
        secret_values.append(diagnostic.llm_api_key)
        payload = json.dumps(
            {
                "error": run.get("error"),
                "limitations": run.get("limitations", []),
                "checks": [
                    {
                        "command": c.get("command"),
                        "exit_code": c.get("exit_code"),
                        "output": c.get("output", "")[-12000:],
                    }
                    for c in run.get("checks", [])[-3:]
                ],
            }
        )
        for secret in secret_values:
            if secret:
                payload = payload.replace(secret, "[redacted]")
        diagnostic.max_calls = 1
        diagnostic.max_tokens = 100000
        suggestions = Provider(diagnostic, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False).ask(
            "diagnostic",
            "Analyze the untrusted test output. Return JSON with summary:string, suggestions:array of strings, and requires_dependency_change:boolean. Suggest focused syntax/import/dependency corrections. You cannot execute commands, install packages, modify permissions, or approve a PR. Clearly distinguish likely causes from verified facts.",
            {"evidence": payload},
        )
        clean = json.dumps(suggestions)
        for secret in secret_values:
            if secret:
                clean = clean.replace(secret, "[redacted]")
        result = {
            "summary": str(json.loads(clean).get("summary", ""))[:4000],
            "suggestions": [str(s)[:1000] for s in json.loads(clean).get("suggestions", [])[:10]],
            "executed": False,
        }
        db.mutate(
            run_id,
            lambda r, d: d.update(diagnostics=result),
            "diagnostic",
            "Groq suggested corrections for owner review. No commands were executed.",
        )
        return result

    @app.get("/api/repositories", dependencies=[Depends(authenticated)])
    def repositories():
        return {"repositories": GitHub(config).repositories()}

    @app.get("/api/runs/{run_id}/environment", dependencies=[Depends(authenticated)])
    def sandbox_environment(run_id: str):
        run = get_run(run_id)
        return {
            "plan": run.get("environment_plan"),
            "checks": [
                {"phase": c.get("phase"), "setup": c.get("setup"), "run_url": c.get("run_url")}
                for c in run.get("checks", [])
            ],
        }

    @app.post("/api/repository/analyze", dependencies=[Depends(authenticated)])
    def analyze_repository(body: RepositoryRequest):
        return GitHub(config).analyze_repository(body.repo, body.enable)

    @app.get("/api/runs", dependencies=[Depends(authenticated)])
    def runs(repo: str | None = None, before: float | None = None):
        result = []
        for r in db.list(repo, before):
            result.append(
                {
                    k: v
                    for k, v in r.items()
                    if k not in {"candidate", "context", "checks", "index", "pull_history", "chat"}
                }
            )
        return {"runs": result, "next_cursor": result[-1]["created"] if len(result) == 50 else None}

    @app.get("/api/runs/{run_id}/pull-history", dependencies=[Depends(authenticated)])
    def pull_history(run_id: str):
        run = get_run(run_id)
        url = run.get("publication", {}).get("pr_url", "")
        import re

        match = re.fullmatch(r"https://github\.com/" + re.escape(run["repo"]) + r"/pull/(\d+)", url)
        if not match:
            raise HTTPException(409, "This run has no published pull request.")
        result = GitHub(config).pull_history(run["repo"], int(match[1]))
        db.mutate(run_id, lambda r, d: d.update(pull_history=result, pr_state=result["state"]))
        return result

    @app.post("/api/runs", status_code=201, dependencies=[Depends(authenticated)])
    @model_serialized
    def new_run(body: NewRun):
        if body.issue == 0 and (body.mode != "github" or len(body.request.strip()) < 10):
            raise HTTPException(422, "Describe the repository task in at least 10 characters.")
        if body.mode == "demo" and not config.demo_enabled:
            raise HTTPException(403, "Demo mode is disabled.")
        if body.mode == "github":
            GitHub.validate_repo(body.repo)
            if config.github_auth == "cli" and body.repo.lower() not in {
                r.lower() for r in GitHub(config).selected_repositories()
            }:
                raise HTTPException(409, "Choose Enable and analyze repository before starting this task.")
            if not config.github_ready or not config.llm_ready:
                raise HTTPException(
                    409,
                    "Configure the GitHub App and a free model key first. The built-in demo is available now.",
                )
            if not ActionsSandbox.available():
                raise HTTPException(
                    409,
                    "Sign in to GitHub CLI to use isolated GitHub Actions checks. Host execution is disabled.",
                )
        repo, issue = ("forge-demo/sample-api", 42) if body.mode == "demo" else (body.repo, body.issue)
        return db.create(
            repo,
            issue,
            dict(
                mode=body.mode,
                request=body.request.strip(),
                requested_profile=body.profile,
                title="Reject a page size of zero"
                if body.mode == "demo"
                else body.request.strip().splitlines()[0][:200]
                if body.issue == 0
                else f"Issue #{body.issue}",
                usage={"calls": 0, "tokens": 0, "cost": 0},
                checks=[],
                repairs=0,
            ),
            body.request_key,
        )

    @app.get("/api/runs/{run_id}", dependencies=[Depends(authenticated)])
    def run_detail(run_id: str):
        run = get_run(run_id)
        return {
            **run,
            "events": db.events(run_id),
            "approval_expires_at": run["ready_at"] + config.approval_ttl_seconds
            if run.get("ready_at")
            else None,
        }

    @app.get("/api/runs/{run_id}/events", dependencies=[Depends(authenticated)])
    async def events(run_id: str, request: Request, after: int = 0, last_event_id: str = Header(default="")):
        get_run(run_id)
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor.") from None

        async def stream():
            nonlocal cursor
            for _ in range(60):
                if await request.is_disconnected():
                    return
                rows = await asyncio.to_thread(db.events, run_id, cursor)
                for event in rows:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(event)}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/api/runs/{run_id}/patch", dependencies=[Depends(authenticated)])
    def patch(run_id: str):
        candidate = get_run(run_id).get("candidate")
        if not candidate:
            raise HTTPException(409, "No candidate is available.")
        return PlainTextResponse(
            candidate["patch"],
            headers={"Content-Disposition": f'attachment; filename="forge-{run_id[:8]}.patch"'},
        )

    @app.post("/api/runs/{run_id}/approve", dependencies=[Depends(authenticated)])
    def approve(run_id: str, body: Approval):
        def change(row, data):
            if row.status != "awaiting_approval":
                raise Conflict("This run is not awaiting approval.")
            candidate = data.get("candidate", {})
            if candidate.get("fingerprint") != body.fingerprint or fingerprint(candidate) != body.fingerprint:
                raise Conflict("Candidate changed. Refresh and review again.")
            if time.time() - data.get("ready_at", 0) > config.approval_ttl_seconds:
                raise Conflict("Candidate review window expired. Start a fresh run.")
            final = candidate["checks"][-1]
            if final["status"] != "passed" or final["count"] < 1 or not candidate["review"]["acceptable"]:
                raise Conflict("Candidate has not passed validation and review.")
            if data["mode"] != "demo" and (not config.publish_enabled or not body.publish_consent):
                raise Conflict(
                    "Enable publication after reviewing repository CI, then acknowledge its side effects."
                )
            data["approval"] = {
                "fingerprint": body.fingerprint,
                "actor": "local-owner",
                "at": time.time(),
                "expires": time.time() + config.approval_ttl_seconds,
            }
            return {"status": "publishing", "lease_owner": "", "lease_until": 0}

        return db.mutate(run_id, change, "approved", "Local owner approved the exact candidate fingerprint.")

    @app.post("/api/runs/{run_id}/reject", dependencies=[Depends(authenticated)])
    def reject(run_id: str):
        def change(row, data):
            if row.status != "awaiting_approval":
                raise Conflict("Only a candidate awaiting approval can be rejected.")
            return {"status": "rejected"}

        return db.mutate(
            run_id, change, "rejected", "Owner rejected the candidate. No changes were published."
        )

    @app.post("/api/runs/{run_id}/revision", status_code=201, dependencies=[Depends(authenticated)])
    @model_serialized
    def revision(run_id: str, body: Revision):
        get_run(run_id)
        return db.revise(run_id, body.feedback, body.request_key)

    @app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(authenticated)])
    def cancel(run_id: str):
        def change(row, data):
            if row.status in {
                "publishing",
                "pr_opened",
                "demo_complete",
                "failed",
                "cancelled",
                "rejected",
                "stale",
            }:
                raise Conflict("This run can no longer be cancelled. Refresh its outcome.")
            return {
                "cancel": True,
                **({"status": "cancelled"} if row.status in {"queued", "awaiting_approval"} else {}),
            }

        return db.mutate(
            run_id, change, "cancel_requested", "Cancellation requested; no further steps will be started."
        )

    @app.post("/api/webhooks/github")
    async def webhook(
        request: Request,
        x_hub_signature_256: str = Header(default=""),
        x_github_delivery: str = Header(default=""),
    ):
        if not config.github_webhook_secret:
            raise HTTPException(503, "Webhook secret is not configured.")
        body = await request.body()
        if len(body) > 1_000_000 or not x_github_delivery or len(x_github_delivery) > 200:
            raise HTTPException(400, "Invalid webhook delivery.")
        signature = (
            "sha256=" + hmac.new(config.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, x_hub_signature_256):
            raise HTTPException(401, "Webhook signature is invalid.")
        return {"received": True, "duplicate": not db.delivery(x_github_delivery), "execution_started": False}

    return app
