"""Local one-time GitHub App manifest onboarding, not a separate product website."""

import html
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from forge.github import GitHub, GitHubError


def private_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(temporary, path)


def load_registration(config):
    path = config.data_dir / "github-registration.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "github_app_id",
            "github_private_key_path",
            "github_installation_id",
            "github_app_slug",
            "github_webhook_secret",
        ):
            if key in data and not getattr(config, key):
                setattr(config, key, data[key])
    return config


class AppSetup:
    def __init__(self, config):
        self.config = config
        self.pending = {}
        self.lock = threading.Lock()

    def begin(self):
        with self.lock:
            if self.config.github_ready:
                raise HTTPException(
                    409,
                    "An App is already configured. Complete its installation or edit local configuration.",
                )
            state = secrets.token_urlsafe(32)
            self.pending = {
                "state": state,
                "expires": time.time() + 1800,
                "phase": "install" if self.config.github_app_id else "register",
            }
        return {"url": "http://127.0.0.1:8787/setup/github?ticket=" + state}

    def validate(self, state, phase):
        if (
            not isinstance(state, str)
            or not secrets.compare_digest(state, self.pending.get("state", ""))
            or not state
            or self.pending.get("expires", 0) < time.time()
            or self.pending.get("phase") != phase
        ):
            raise HTTPException(403, "Setup link expired or already used. Start again from Forge Connection.")

    @staticmethod
    def page(title, content):
        return HTMLResponse(
            f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Forge · GitHub setup</title>
<style>body{{background:#f7f8f3;color:#293129;font:15px/1.8 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0}}
main{{max-width:540px;margin:10vh auto;padding:30px}}h1{{font-size:32px;letter-spacing:-1px;line-height:1.2}}
button,a{{display:inline-block;background:#405537;color:white;border:0;border-radius:10px;padding:12px 20px;font:inherit;text-decoration:none;cursor:pointer}}
small{{color:#77826d}}p{{margin:22px 0}}</style><main><small>FORGE · LOCAL CONNECTION</small><h1>{html.escape(title)}</h1>{content}</main></html>""",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action https://github.com; frame-ancestors 'none'",
            },
        )

    def routes(self, app, authenticated):
        from fastapi import Depends

        @app.post("/api/setup/github", dependencies=[Depends(authenticated)])
        def begin():
            return self.begin()

        @app.get("/setup/github", include_in_schema=False)
        def registration(ticket: str):
            with self.lock:
                phase = "install" if self.config.github_app_id else "register"
                self.validate(ticket, phase)
            if phase == "install":
                slug = self.config.github_app_slug
                if not re.fullmatch(r"[a-z0-9-]+", slug):
                    raise HTTPException(409, "Configure the existing App installation manually.")
                return self.page(
                    "Finish connecting GitHub.",
                    f'<p>Your App is already registered. Select the repositories Forge may use.</p><a href="https://github.com/apps/{slug}/installations/new?state={ticket}">Choose repositories →</a>',
                )
            manifest = {
                "name": "Forge Companion " + secrets.token_hex(3),
                "url": "https://github.com/KaartikeyKusshwaha/Forge",
                "public": False,
                "description": "Human-approved issue-to-PR engineering inside GitHub.",
                "redirect_url": "http://127.0.0.1:8787/setup/github/callback",
                "setup_url": "http://127.0.0.1:8787/setup/github/installed",
                "hook_attributes": {"url": "http://127.0.0.1:8787/api/webhooks/github", "active": False},
                "default_permissions": {"contents": "write", "issues": "read", "pull_requests": "write"},
                "default_events": [],
            }
            encoded = html.escape(json.dumps(manifest), quote=True)
            return self.page(
                "Connect your GitHub repositories.",
                f'''<p>Create an App owned by your GitHub account. The App key returns directly to your local Forge service; you do not need to copy it.</p>
<p>Requested access: repository contents read/write, issues read, and pull requests read/write. Select only the repositories you want Forge to use.</p>
<form method="post" action="https://github.com/settings/apps/new?state={ticket}"><input type="hidden" name="manifest" value="{encoded}"><button>Create my GitHub App →</button></form>
<p><small>GitHub will ask you to confirm. Publishing remains disabled until you enable it and approve an exact patch.</small></p>''',
            )

        @app.get("/setup/github/callback", include_in_schema=False)
        def callback(code: str, state: str):
            if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", code):
                raise HTTPException(400, "Invalid GitHub setup code.")
            with self.lock:
                self.validate(state, "register")
                self.pending["phase"] = "exchanging"
            try:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    response = client.post(
                        f"https://api.github.com/app-manifests/{code}/conversions",
                        headers={"Accept": "application/vnd.github+json"},
                    )
                if response.status_code != 201:
                    raise GitHubError("GitHub could not complete App registration. Start a fresh setup link.")
                data = response.json()
                if not re.fullmatch(r"[a-z0-9-]+", data["slug"]):
                    raise GitHubError("GitHub returned an invalid App slug.")
                key_path = (self.config.data_dir / "github-app.pem").resolve()
                if key_path.exists():
                    raise GitHubError("An App key already exists. It was not overwritten.")
                private_write(key_path, data["pem"])
                self.config.github_app_id = str(data["id"])
                self.config.github_private_key_path = str(key_path)
                self.config.github_app_slug = data["slug"]
                self.config.github_webhook_secret = data["webhook_secret"]
                self.persist()
                with self.lock:
                    self.pending["phase"] = "install"
                link = f"https://github.com/apps/{data['slug']}/installations/new?state={state}"
                return self.page(
                    "Your App is ready to install.",
                    f'<p>Select the repositories Forge may work on. Your private key is stored locally. Forge never needs your GitHub password.</p><a href="{link}">Choose repositories →</a><p><small>Once installed, return to the extension’s Connection settings.</small></p>',
                )
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise HTTPException(
                    502, "Registration did not complete. No credentials were displayed."
                ) from exc

        @app.get("/setup/github/installed", include_in_schema=False)
        def installed(installation_id: int, request: Request, state: str = ""):
            # GitHub setup redirects may omit state; never accept the ID as authority.
            # Authenticate to the App, list its installations, and match the ID instead.
            with self.lock:
                if self.pending.get("phase") != "install" or self.pending.get("expires", 0) < time.time():
                    raise HTTPException(403, "No local installation setup is pending.")
                if state:
                    self.validate(state, "install")
            github = GitHub(self.config)
            installation = github.app_request("GET", f"/app/installations/{installation_id}")
            if str(installation.get("app_id")) != self.config.github_app_id:
                raise HTTPException(403, "Installation belongs to a different App.")
            self.config.github_installation_id = installation_id
            self.persist()
            with self.lock:
                self.pending.clear()
            return self.page(
                "GitHub is connected.",
                "<p>Return to your GitHub issue and open Forge. Your selected repositories are now available to the local worker.</p><p><small>Publishing remains disabled until the target CI policy is reviewed.</small></p>",
            )

    def persist(self):
        private_write(
            self.config.data_dir / "github-registration.json",
            json.dumps(
                {
                    key: getattr(self.config, key)
                    for key in (
                        "github_app_id",
                        "github_private_key_path",
                        "github_installation_id",
                        "github_app_slug",
                        "github_webhook_secret",
                    )
                },
                indent=2,
            ),
        )
