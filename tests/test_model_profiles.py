import json
import threading
import time

import pytest

from forge.config import Settings
from forge.models import ModelVault, connection_input, discover, protect
from forge.policy import PolicyError

KEY = "sk-or-fixture-key-for-tests-only"


def fake_discover(key, provider, mode, confirmed):
    assert key == KEY
    return "openrouter-free", [
        {
            "id": "thinkingmachines/inkling:free",
            "name": "Inkling",
            "parameters": [],
            "prices": {"prompt": 0, "completion": 0},
            "free": True,
        }
    ]


def test_key_detection_never_sprays_unknown_keys(monkeypatch):
    monkeypatch.setattr(
        "forge.models.httpx.get", lambda *a, **k: pytest.fail("Unknown key must not leave the host")
    )
    with pytest.raises(PolicyError, match="ambiguous"):
        discover("unknown-provider-secret")
    with pytest.raises(PolicyError, match="different"):
        discover("gsk_fixture", "openrouter-free")


def test_local_endpoint_needs_no_key_but_must_stay_loopback(monkeypatch, tmp_path):
    import httpx

    def get(url, **kwargs):
        assert url == "http://127.0.0.1:11434/v1/models"
        assert "headers" not in kwargs
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{"id": "local-coder"}]})

    monkeypatch.setattr("forge.models.httpx.get", get)
    config = Settings(data_dir=tmp_path, _env_file=None)
    vault = ModelVault(config)
    key, provider = connection_input("", endpoint="http://127.0.0.1:11434/v1")
    vault.activate(
        vault.save(key, "Local", provider, "free_only", 0, False, endpoint="http://127.0.0.1:11434/v1")
    )
    assert config.llm_provider == "local" and config.llm_api_key == ""
    with pytest.raises(PolicyError, match="loopback"):
        connection_input("", endpoint="http://10.0.0.1/v1")


def test_profile_round_trip_hides_keys_and_persists_selection(monkeypatch, tmp_path):
    monkeypatch.setattr("forge.models.discover", fake_discover)
    config = Settings(data_dir=tmp_path, _env_file=None)
    vault = ModelVault(config)
    pid = vault.save(KEY, "My profile", "auto", "free_only", 0, False)
    vault.activate(pid)
    assert KEY not in json.dumps(vault.list())
    assert config.llm_model == "thinkingmachines/inkling:free"
    assert config.llm_api_key == KEY
    other = Settings(data_dir=tmp_path, _env_file=None)
    ModelVault(other).load_active()
    assert other.llm_api_key == KEY
    assert protect(protect(KEY), True) == KEY
    with pytest.raises(PolicyError, match="another"):
        vault.delete(pid)


def test_no_costly_call_without_explicit_approval_and_cap(monkeypatch, tmp_path):
    monkeypatch.setattr("forge.models.discover", fake_discover)
    config = Settings(data_dir=tmp_path, _env_file=None)
    vault = ModelVault(config)
    pid = vault.save(KEY, "Ask me", "auto", "ask_paid", 0.05, False)
    vault.activate(pid)
    result = []
    thread = threading.Thread(
        target=lambda: result.append(vault.reserve(0.02, "coder", "run-one", lambda: False))
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not vault.pending()["requests"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert thread.is_alive() and not result
    pending = vault.pending()["requests"][0]
    vault.decide(pending["id"], True)
    thread.join(3)
    assert result == [pending["id"]]
    vault.settle(result[0], 0.01)
    assert vault.list()["profiles"][0]["spent_usd"] == 0.01
    with pytest.raises(PolicyError, match="cap"):
        vault.reserve(0.05, "coder", "run-two", lambda: False)


def test_free_mode_rejects_paid_reservation(monkeypatch, tmp_path):
    monkeypatch.setattr("forge.models.discover", fake_discover)
    config = Settings(data_dir=tmp_path, _env_file=None)
    vault = ModelVault(config)
    vault.activate(vault.save(KEY, "Free", "auto", "free_only", 0, False))
    assert vault.reserve(0, "coder", "r", lambda: False) is None
    with pytest.raises(PolicyError, match="forbidden"):
        vault.reserve(0.001, "coder", "r", lambda: False)


def test_configuration_import_is_parse_only(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    assert connection_input("", environment="OPENROUTER_API_KEY")[0] == KEY
    command = "curl https://openrouter.ai/api/v1/models -H 'Authorization: Bearer " + KEY + "'"
    assert connection_input("", command=command) == (KEY, "openrouter-free")
    with pytest.raises(PolicyError, match="official"):
        connection_input(KEY, endpoint="https://evil.test")
    with pytest.raises(PolicyError, match="not executed"):
        connection_input("", command="powershell install-something")


def test_pasted_bearer_key_takes_precedence_over_missing_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    command = "curl https://openrouter.ai/api/v1/models -H 'Authorization: Bearer " + KEY + "'"
    assert connection_input("", environment="OPENROUTER_API_KEY", command=command) == (KEY, "openrouter-free")
    with pytest.raises(PolicyError, match="Choose API key"):
        connection_input("", environment="OPENROUTER_API_KEY")


def test_api_profiles_never_return_secrets_and_block_active_switch(monkeypatch, setup):
    monkeypatch.setattr("forge.models.discover", fake_discover)
    config, store, client = setup
    response = client.post("/api/model-profiles", json={"api_key": KEY})
    assert response.status_code == 200, response.text
    assert KEY not in response.text
    assert config.llm_model == "thinkingmachines/inkling:free"
    pid = response.json()["profiles"][0]["id"]
    store.create("owner/repo", 1, {"mode": "github", "title": "Queued"}, "queued-fixture-model")
    assert client.post(f"/api/model-profiles/{pid}/activate", json={}).status_code == 409
    client.headers.clear()
    assert client.get("/api/model-profiles").status_code == 401


def test_invalid_profile_inputs_do_not_echo_secrets(setup):
    _, _, client = setup
    response = client.post("/api/model-profiles", json={"api_key": {"secret": KEY}})
    assert response.status_code == 422
    assert KEY not in response.text and '"input"' not in response.text


def test_groq_diagnostic_suggests_without_executing_or_receiving_other_keys(monkeypatch, setup):
    config, store, client = setup
    backup = config.data_dir / "provider-backups/before-inkling.env"
    backup.parent.mkdir()
    backup.write_text(
        "FORGE_LLM_PROVIDER=groq-free\nFORGE_GROQ_FREE_PLAN_CONFIRMED=true\nFORGE_LLM_API_KEY=gsk_fixture_secret_only\n"
    )
    config.llm_api_key = KEY
    run = store.create(
        "owner/repo",
        1,
        {"mode": "github", "title": "Failure", "error": "ImportError " + KEY, "checks": []},
        "diagnostic-fixture-one",
    )
    store.mutate(run["id"], lambda r, d: {"status": "failed"})

    def ask(self, role, instructions, context):
        assert role == "diagnostic" and KEY not in json.dumps(context)
        assert self.config.llm_provider == "groq-free"
        assert self.config.model_usage_mode == "free_only"
        return {"summary": "A dependency may be absent", "suggestions": ["Review the package requirements"]}

    monkeypatch.setattr("forge.llm.Provider.ask", ask)
    response = client.post(f"/api/runs/{run['id']}/diagnose")
    assert response.status_code == 200, response.text
    assert response.json()["executed"] is False
    assert store.get(run["id"])["status"] == "failed"


def test_discovery_checks_access_and_defaults_to_inkling_without_inference(monkeypatch):
    import httpx

    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("/key"):
            return httpx.Response(200, json={"data": {}}, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "data": [
                    {
                        "id": "other/paid",
                        "supported_parameters": ["tools"],
                        "pricing": {"prompt": "1", "completion": "1"},
                    },
                    {
                        "id": "thinkingmachines/inkling:free",
                        "supported_parameters": ["tools", "reasoning"],
                        "context_length": 1000000,
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                ]
            },
        )

    monkeypatch.setattr("forge.models.httpx.get", get)
    provider, models = discover(KEY)
    assert provider == "openrouter-free"
    assert [m["id"] for m in models] == ["thinkingmachines/inkling:free"]
    assert calls == ["https://openrouter.ai/api/v1/key", "https://openrouter.ai/api/v1/models"]


def test_provider_does_not_send_paid_request_until_owner_grants_permission(monkeypatch, tmp_path):
    import httpx

    from forge.llm import Provider

    monkeypatch.setattr("forge.models.discover", fake_discover)
    config = Settings(data_dir=tmp_path, max_tokens=100000, _env_file=None)
    vault = ModelVault(config)
    vault.activate(vault.save(KEY, "Permission test", "auto", "ask_paid", 1, False))
    monkeypatch.setattr(
        "forge.llm.verify_free",
        lambda _: {
            "id": "fixture/paid",
            "prices": {"prompt": 0.000001, "completion": 0.000001},
            "parameters": [],
        },
    )
    calls, results = [], []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                    "usage": {"cost": 0.001, "total_tokens": 20},
                },
            )

    monkeypatch.setattr("forge.llm.httpx.Client", Client)
    thread = threading.Thread(
        target=lambda: results.append(
            Provider(config, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False).ask(
                "diagnostic", "Fix", {}
            )
        )
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not vault.pending()["requests"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not calls
    vault.decide(vault.pending()["requests"][0]["id"], True)
    thread.join(3)
    assert len(calls) == 1 and results == [{"summary": "ok"}]
