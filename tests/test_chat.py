from types import SimpleNamespace

import pytest

from forge.chat import prepare, reply
from forge.policy import PolicyError
from forge.store import Conflict


def conversation(client):
    response = client.post(
        "/api/conversations",
        json={"repo": "owner/repo", "issue": 1, "request_key": "chat-session-fixture"},
    )
    assert response.status_code == 201
    return response.json()


def test_conversation_does_not_queue_execution_or_publish(setup):
    config, store, client = setup
    run = conversation(client)
    assert run["status"] == "needs_input"
    assert store.claim("fixture-worker") is None
    assert "candidate" not in run
    assert client.post(f"/api/runs/{run['id']}/approve", json={"fingerprint": "a" * 64}).status_code == 409


def test_chat_context_persistence_idempotency_and_approval_unchanged(setup, monkeypatch):
    config, store, client = setup
    run = conversation(client)
    seen = []

    def ask(self, role, instructions, context):
        seen.append(context)
        return {"reply": "We can add boundary tests. Build from conversation creates a checked proposal."}

    monkeypatch.setattr("forge.chat.Provider.ask", ask)
    monkeypatch.setattr(
        "forge.api.threading.Thread",
        lambda target, args, **kwargs: SimpleNamespace(start=lambda: target(*args)),
    )
    body = {"message": "Please add tests for invalid sizes.", "request_key": "chat-message-fixture"}
    assert client.post(f"/api/runs/{run['id']}/chat", json=body).status_code == 200
    saved = store.get(run["id"])
    assert saved["chat"][0]["status"] == "answered"
    assert "boundary tests" in saved["chat"][0]["reply"]
    assert seen[0]["repository"] == "owner/repo"
    assert saved["status"] == "needs_input" and "candidate" not in saved
    client.post(f"/api/runs/{run['id']}/chat", json=body)
    assert len(seen) == 1
    assert (
        client.post(f"/api/runs/{run['id']}/chat", json={**body, "message": "Different"}).status_code == 409
    )
    revision = client.post(
        f"/api/runs/{run['id']}/revision",
        json={"feedback": body["message"], "request_key": "chat-build-fixture"},
    ).json()
    assert revision["status"] == "queued" and revision["parent_run"] == run["id"]
    assert "candidate" not in revision


def test_failed_provider_reply_is_visible_and_does_not_lose_user_message(setup, monkeypatch):
    config, store, client = setup
    run = conversation(client)
    prepare(store, run["id"], "Explain the failed check", "chat-failure-fixture")

    def denied(*args):
        raise PolicyError("Model provider rejected the request (HTTP 403).")

    monkeypatch.setattr("forge.chat.Provider.ask", denied)
    result = reply(store, config, run["id"], "chat-failure-fixture")
    assert result["chat"][0]["message"] == "Explain the failed check"
    assert "403" in result["chat"][0]["error"]
    assert result["chat"][0]["status"] == "failed"
    assert result["status"] == "needs_input"
    prepare(store, run["id"], "Try once more", "chat-retry-fixture")
    with pytest.raises(Conflict, match="Wait"):
        prepare(store, run["id"], "Parallel request", "chat-parallel-fixture")


def test_chat_requires_owner_auth_and_rejects_blank_messages(setup):
    config, store, client = setup
    run = conversation(client)
    path = f"/api/runs/{run['id']}/chat"
    body = {"message": " ", "request_key": "chat-validation-fixture"}
    assert client.post(path, json=body).status_code == 422
    client.headers.pop("Authorization")
    assert client.post(path, json=body).status_code == 401
