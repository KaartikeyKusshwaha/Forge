import asyncio
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from forge.actions import ActionsSandbox
from forge.config import Settings
from forge.github import GitHub, GitHubError
from forge.llm import free_models
from forge.policy import PolicyError, fingerprint
from forge.setup import AppSetup
from forge.store import Conflict, Store


class NewRun(BaseModel):
    repo: str = Field(max_length=200, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    issue: int = Field(ge=1, le=2**31)
    mode: Literal["github", "demo"] = "github"
    profile: Literal["auto", "python", "typescript"] = "auto"
    request_key: str = Field(min_length=12, max_length=100)


class Approval(BaseModel):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    publish_consent: bool = False


class Revision(BaseModel):
    feedback: str = Field(min_length=10, max_length=4000)
    request_key: str = Field(min_length=12, max_length=100)


def create_app(config: Settings, store: Store | None = None) -> FastAPI:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = store or Store(config.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(title="Forge", version="0.2.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    app.state.store = db

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

    @app.exception_handler(PolicyError)
    @app.exception_handler(GitHubError)
    async def policy_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"service": "forge", "version": "0.2.0", "status": "ok"}

    @app.get("/api/status", dependencies=[Depends(authenticated)])
    def status():
        return {
            "github": config.github_ready,
            "github_auth": config.github_auth,
            "model": config.llm_ready,
            "model_name": config.llm_model,
            "free_only": True,
            "provider": config.llm_provider,
            "demo": config.demo_enabled,
            "publishing": config.publish_enabled,
            "runner": ActionsSandbox.available(),
        }

    @app.get("/api/models", dependencies=[Depends(authenticated)])
    def models():
        return {"models": free_models(), "selection": config.llm_model, "paid_fallback": False}

    @app.get("/api/repositories", dependencies=[Depends(authenticated)])
    def repositories():
        return {"repositories": GitHub(config).repositories()}

    @app.get("/api/runs", dependencies=[Depends(authenticated)])
    def runs(repo: str | None = None):
        result = []
        for r in db.list(repo):
            result.append(
                {k: v for k, v in r.items() if k not in {"candidate", "context", "checks", "index"}}
            )
        return {"runs": result}

    @app.post("/api/runs", status_code=201, dependencies=[Depends(authenticated)])
    def new_run(body: NewRun):
        if body.mode == "demo" and not config.demo_enabled:
            raise HTTPException(403, "Demo mode is disabled.")
        if body.mode == "github":
            GitHub.validate_repo(body.repo)
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
                requested_profile=body.profile,
                title="Reject a page size of zero" if body.mode == "demo" else f"Issue #{body.issue}",
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
