import json

import pytest

from forge.models import ModelVault
from forge.policy import PolicyError


def new_session(client):
    return client.post(
        "/api/conversations",
        json={"repo": "owner/repo", "issue": 0, "request_key": "session-controls-fixture"},
    ).json()


def test_end_forget_delete_are_local_and_preserve_publication(setup):
    config, store, client = setup
    run = new_session(client)
    store.mutate(
        run["id"],
        lambda r, d: d.update(
            chat=[{"status": "answered", "message": "private discussion"}],
            publication={"pr_url": "https://github.com/owner/repo/pull/1"},
        ),
    )
    base = f"/api/runs/{run['id']}/session"
    assert client.post(base, json={"action": "forget"}).status_code == 200
    saved = store.get(run["id"])
    assert not saved["chat"] and saved["publication"]["pr_url"].endswith("/1")
    assert client.post(base, json={"action": "end"}).json()["ended"]
    assert (
        client.post(
            f"/api/runs/{run['id']}/chat", json={"message": "continue", "request_key": "ended-chat-fixture"}
        ).status_code
        == 409
    )
    assert client.post(base, json={"action": "delete"}).json()["deleted"]
    assert client.get(f"/api/runs/{run['id']}").status_code == 404
    assert store.events(run["id"]) == []


def test_deletion_requires_execution_to_stop(setup):
    config, store, client = setup
    run = store.create("owner/repo", 1, {"mode": "github", "title": "Active"}, "active-delete-fixture")
    assert client.post(f"/api/runs/{run['id']}/session", json={"action": "delete"}).status_code == 409


def policy_profile(config, mode, calls=2, tokens=10000):
    vault = ModelVault(config)
    pid = vault.save_compatible(
        "fixture-key", "https://example.com/v1", "openai", [{"id": "coder"}], "Fixture", mode, 0, {}, []
    )
    data = vault.read(pid)
    data.update(call_limit=calls, token_limit=tokens)
    with vault.connect() as db:
        db.execute("UPDATE profiles SET data=? WHERE id=?", (json.dumps(data), pid))
    vault.activate(pid, verify=False)
    return vault


def test_limited_policy_reserves_before_call_and_counts_across_roles(setup):
    config, store, client = setup
    vault = policy_profile(config, "limited")
    first = vault.reserve_usage(8000)
    with pytest.raises(PolicyError, match="limit"):
        vault.reserve_usage(3000)
    vault.settle_usage(first, 100)
    vault.reserve_usage(8000)
    with pytest.raises(PolicyError, match="limit"):
        vault.reserve_usage(1)


def test_unlimited_does_not_require_pricing_or_a_credit_cap(setup):
    config, store, client = setup
    vault = policy_profile(config, "unlimited")
    assert vault.reserve_usage(99999999) is None
    assert vault.reserve(999999, "coder", "run", lambda: False) is None


def test_policy_changes_apply_to_active_profile_and_do_not_expose_key(setup):
    config, store, client = setup
    policy_profile(config, "limited")
    pid = config.model_profile_id
    response = client.post(f"/api/model-profiles/{pid}/policy", json={"mode": "unlimited"})
    assert response.status_code == 200
    assert config.model_usage_mode == "unlimited"
    assert "fixture-key" not in response.text


def test_unknown_provider_connects_in_unlimited_mode_without_price_prompts(setup, monkeypatch):
    import httpx

    config, store, client = setup
    monkeypatch.setattr("forge.integrations.validate_remote", lambda value: value)
    monkeypatch.setattr(
        "forge.integrations.httpx.get",
        lambda url, **kwargs: httpx.Response(
            200, request=httpx.Request("GET", url), json={"data": [{"id": "new-coder"}]}
        ),
    )
    response = client.post(
        "/api/model-profiles",
        json={
            "api_key": "opaque-new-provider-key",
            "endpoint": "https://new.example/v1",
            "endpoint_consent": True,
            "mode": "unlimited",
        },
    )
    assert response.status_code == 200 and "setup" not in response.json()
    assert config.model_usage_mode == "unlimited" and config.llm_model == "new-coder"
