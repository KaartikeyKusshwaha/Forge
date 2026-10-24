import json
from urllib.parse import parse_qs, urlparse

import httpx

from forge.config import Settings
from forge.setup import load_registration


def test_app_manifest_requires_owner_and_valid_single_use_state(setup):
    _, _, client = setup
    assert client.post("/api/setup/github", headers={"Authorization": ""}).status_code == 401
    response = client.post("/api/setup/github")
    ticket = parse_qs(urlparse(response.json()["url"]).query)["ticket"][0]
    page = client.get("/setup/github", params={"ticket": ticket})
    assert page.status_code == 200
    assert "https://github.com/settings/apps/new" in page.text
    assert "client_secret" not in page.text
    assert "no-store" in page.headers["cache-control"]
    assert client.get("/setup/github", params={"ticket": "wrong"}).status_code == 403
    client.post("/api/setup/github")
    assert client.get("/setup/github", params={"ticket": ticket}).status_code == 403


def test_manifest_exchange_saves_credentials_without_returning_them(setup, monkeypatch):
    config, _, client = setup
    ticket = parse_qs(urlparse(client.post("/api/setup/github").json()["url"]).query)["ticket"][0]
    original = httpx.Client.post

    def response(self, url, **kwargs):
        if str(url).startswith("https://api.github.com/app-manifests/"):
            return httpx.Response(
                201,
                json={
                    "id": 12345,
                    "slug": "forge-fixture",
                    "pem": "PRIVATE FIXTURE KEY",
                    "webhook_secret": "fixture-webhook",
                },
            )
        return original(self, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "post", response)
    result = client.get("/setup/github/callback", params={"code": "fixture-code-valid-001", "state": ticket})
    assert result.status_code == 200
    assert "PRIVATE FIXTURE KEY" not in result.text
    assert "fixture-webhook" not in result.text
    assert "github.com/apps/forge-fixture/installations/new" in result.text
    assert (
        client.get(
            "/setup/github/callback", params={"code": "fixture-code-valid-001", "state": ticket}
        ).status_code
        == 403
    )
    assert config.github_app_id == "12345"
    saved = json.loads((config.data_dir / "github-registration.json").read_text())
    assert saved["github_installation_id"] == 0
    monkeypatch.setattr("forge.setup.GitHub.app_request", lambda *a, **k: {"app_id": 12345})
    result = client.get("/setup/github/installed", params={"installation_id": 678, "state": ticket})
    assert result.status_code == 200
    assert config.github_ready
    restored = load_registration(Settings(data_dir=config.data_dir, _env_file=None))
    assert restored.github_installation_id == 678
    assert (
        client.get("/setup/github/installed", params={"installation_id": 678, "state": ticket}).status_code
        == 403
    )


def test_installation_callback_cannot_replace_owner_installation(setup):
    _, _, client = setup
    assert client.get("/setup/github/installed", params={"installation_id": 999}).status_code == 403
    assert client.get("/setup/github/callback", params={"code": "invalid", "state": "bad"}).status_code == 400
