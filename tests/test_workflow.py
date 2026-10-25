import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor

from conftest import create_demo

from forge.worker import Worker


def test_real_fixture_checks_and_exact_approval(setup):
    config, store, client = setup
    run = create_demo(client)
    assert client.post(f"/api/runs/{run['id']}/approve", json={"fingerprint": "a" * 64}).status_code == 409
    assert Worker(config, store).run_once()
    result = client.get(f"/api/runs/{run['id']}").json()
    assert result["status"] == "awaiting_approval", result
    assert [(c["phase"], c["status"], c["count"]) for c in result["checks"]] == [
        ("baseline", "passed", 3),
        ("regression_on_base", "failed", 5),
        ("candidate", "passed", 5),
    ]
    assert "FAIL: test_zero_limit" in result["checks"][1]["output"]
    assert result["usage"]["calls"] == 0
    fingerprint = result["candidate"]["fingerprint"]
    assert client.post(f"/api/runs/{run['id']}/approve", json={"fingerprint": "f" * 64}).status_code == 409
    assert client.post(f"/api/runs/{run['id']}/approve", json={"fingerprint": fingerprint}).status_code == 200
    assert client.post(f"/api/runs/{run['id']}/approve", json={"fingerprint": fingerprint}).status_code == 409
    assert Worker(config, store).run_once()
    done = store.get(run["id"])
    assert done["status"] == "demo_complete"
    assert "publication" not in done
    assert "-    if limit < 0" in client.get(f"/api/runs/{run['id']}/patch").text


def test_tampered_candidate_is_not_approved(setup):
    config, store, client = setup
    run = create_demo(client)
    Worker(config, store).run_once()
    original = store.get(run["id"])["candidate"]["fingerprint"]
    store.mutate(run["id"], lambda r, d: d["candidate"].update(patch="tampered"))
    assert client.post(f"/api/runs/{run['id']}/approve", json={"fingerprint": original}).status_code == 409


def test_expired_candidate_is_not_approved(setup):
    config, store, client = setup
    run = create_demo(client)
    Worker(config, store).run_once()
    result = store.mutate(run["id"], lambda r, d: d.update(ready_at=time.time() - 4000))
    assert (
        client.post(
            f"/api/runs/{run['id']}/approve", json={"fingerprint": result["candidate"]["fingerprint"]}
        ).status_code
        == 409
    )


def test_cancellation_and_rejection_are_final(setup):
    config, store, client = setup
    run = create_demo(client)
    assert client.post(f"/api/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert not Worker(config, store).run_once()
    run = create_demo(client, "fixture-request-0002")
    Worker(config, store).run_once()
    assert client.post(f"/api/runs/{run['id']}/reject").json()["status"] == "rejected"
    assert not Worker(config, store).run_once()


def test_single_claim_under_concurrency(setup):
    _, store, client = setup
    create_demo(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(store.claim, ["worker-one", "worker-two"]))
    assert sum(claim is not None for claim in claims) == 1


def test_worker_recovery_stops_unvalidated_work(setup):
    _, store, client = setup
    run = create_demo(client)
    store.mutate(run["id"], lambda r, d: {"status": "coding", "lease_owner": "dead", "lease_until": 1})
    store.recover()
    assert store.get(run["id"])["status"] == "failed"


def test_authentication_and_host_boundary(setup):
    _, _, client = setup
    run = create_demo(client)
    for endpoint in ("/api/status", "/api/runs", f"/api/runs/{run['id']}", f"/api/runs/{run['id']}/patch"):
        assert client.get(endpoint, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/runs", json={}, headers={"Authorization": ""}).status_code == 401
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400


def test_webhook_signature_replay_never_starts_a_run(setup):
    config, store, client = setup
    body = b'{"action":"opened"}'
    signature = "sha256=" + hmac.new(config.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": signature, "X-GitHub-Delivery": "fixture-delivery"}
    assert (
        client.post(
            "/api/webhooks/github", content=body, headers={**headers, "X-Hub-Signature-256": "bad"}
        ).status_code
        == 401
    )
    assert client.post("/api/webhooks/github", content=body, headers=headers).json()["duplicate"] is False
    assert client.post("/api/webhooks/github", content=body, headers=headers).json()["duplicate"] is True
    assert not store.list()


def test_idempotent_creation_and_unknown_run(setup):
    _, store, client = setup
    first = create_demo(client)
    second = create_demo(client)
    assert first["id"] == second["id"]
    assert len(store.list()) == 1
    assert client.get("/api/runs/missing").status_code == 404


def test_live_run_does_not_fall_back_to_host_or_paid_model(setup):
    _, store, client = setup
    response = client.post(
        "/api/runs", json=dict(repo="owner/repo", issue=1, mode="github", request_key="real-run-request-001")
    )
    assert response.status_code == 409
    assert not store.list()


def test_revision_retires_old_approval_and_creates_fresh_idempotent_run(setup):
    config, store, client = setup
    original = create_demo(client)
    Worker(config, store).run_once()
    # Exercise revision transitions with a prepared candidate without a live API call.
    ready = store.mutate(original["id"], lambda r, d: d.update(mode="github"))
    body = {
        "feedback": "Please also cover a limit of exactly one.",
        "request_key": "owner-revision-request-001",
    }
    response = client.post(f"/api/runs/{original['id']}/revision", json=body)
    assert response.status_code == 201, response.text
    next_run = response.json()
    assert next_run["id"] != original["id"]
    assert next_run["status"] == "queued"
    assert next_run["parent_run"] == original["id"]
    assert "candidate" not in next_run and "approval" not in next_run
    assert store.get(original["id"])["status"] == "rejected"
    assert client.post(f"/api/runs/{original['id']}/revision", json=body).json()["id"] == next_run["id"]
    assert (
        client.post(
            f"/api/runs/{original['id']}/approve", json={"fingerprint": ready["candidate"]["fingerprint"]}
        ).status_code
        == 409
    )


def test_single_active_run_across_distinct_jobs(setup):
    _, store, client = setup
    create_demo(client)
    create_demo(client, "second-separate-request")
    assert store.claim("first-worker") is not None
    assert store.claim("second-worker") is None


def test_follow_up_preserves_published_history_and_requires_fresh_approval(setup):
    _, store, client = setup
    old = store.create(
        "owner/repo",
        0,
        {
            "mode": "github",
            "title": "Custom task",
            "request": "Improve the boundary validation.",
            "publication": {"pr_url": "https://github.com/owner/repo/pull/7", "commit_sha": "a" * 40},
        },
        "published-request-001",
    )
    store.mutate(old["id"], lambda r, d: {"status": "pr_opened"})
    body = {
        "feedback": "Also add regression coverage for invalid strings.",
        "request_key": "follow-up-request-001",
    }
    response = client.post(f"/api/runs/{old['id']}/revision", json=body)
    assert response.status_code == 201, response.text
    new = response.json()
    assert store.get(old["id"])["status"] == "pr_opened"
    assert new["previous_publication"]["commit_sha"] == "a" * 40
    assert new["request"] == old["request"]
    assert "publication" not in new and "approval" not in new and "candidate" not in new
