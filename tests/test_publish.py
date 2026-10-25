import copy
import time

import pytest

from forge.config import Settings
from forge.github import GitHub
from forge.policy import PolicyError, seal_candidate


@pytest.fixture
def publication():
    candidate = seal_candidate(
        "base123",
        {"a.py": "old\n"},
        {"a.py": "new\n"},
        [{"phase": "candidate", "status": "passed", "command": "pytest", "count": 1}],
        {"acceptable": True},
        "python",
    )
    return {
        "id": "abc123",
        "status": "publishing",
        "repo": "owner/repo",
        "issue": 4,
        "candidate": candidate,
        "context": {
            "repo_id": 1,
            "branch": "main",
            "base_tree": "tree123",
            "title": "Fix the example",
            "issue_url": "https://github.com/owner/repo/issues/4",
        },
        "approval": {
            "fingerprint": candidate["fingerprint"],
            "actor": "local-owner",
            "expires": time.time() + 100,
        },
    }


def fake_github(monkeypatch, base="base123", existing_commit=None, existing_pr=None):
    github = GitHub(Settings(publish_enabled=True, _env_file=None))
    writes = []
    monkeypatch.setattr(github, "token", lambda *args, **kwargs: "fixture-token")

    def request(method, path, token, **kwargs):
        if method == "POST":
            writes.append((path, kwargs.get("json")))
        if "/commits/" in path:
            return {"sha": base}
        if path.endswith("/git/trees"):
            return {"sha": "newtree"}
        if path.endswith("/git/commits"):
            return {"sha": "approved-commit"}
        if "/git/matching-refs/" in path:
            return (
                []
                if existing_commit is None
                else [{"ref": "refs/heads/forge/issue-4-abc123", "object": {"sha": existing_commit}}]
            )
        if path.endswith("/git/refs"):
            return {}
        if path.endswith("/pulls") and method == "GET":
            return [existing_pr] if existing_pr else []
        if path.endswith("/pulls") and method == "POST":
            return {"html_url": "https://github.com/owner/repo/pull/9", "number": 9}
        raise AssertionError((method, path))

    monkeypatch.setattr(github, "request", request)
    return github, writes


def test_publish_no_writes_before_approval(monkeypatch, publication):
    github, writes = fake_github(monkeypatch)
    publication["approval"] = {}
    with pytest.raises(PolicyError):
        github.publish(publication, lambda _: None)
    assert not writes


def test_moved_base_is_never_committed(monkeypatch, publication):
    github, writes = fake_github(monkeypatch, base="different")
    with pytest.raises(PolicyError, match="base branch moved"):
        github.publish(publication, lambda _: None)
    assert not writes


def test_publish_creates_draft_and_preserves_executable_mode(monkeypatch, publication):
    github, writes = fake_github(monkeypatch)
    publication["context"]["file_modes"] = {"a.py": "100755"}
    persisted = []
    result = github.publish(publication, persisted.append)
    assert result["pr_number"] == 9
    assert writes[0][1]["tree"][0]["mode"] == "100755"
    assert writes[-1][1]["draft"] is True
    assert persisted[0]["commit_sha"] == "approved-commit"


def test_reconcile_existing_branch_and_pr_without_duplicates(monkeypatch, publication):
    pr = {"html_url": "https://github.com/owner/repo/pull/9", "number": 9}
    github, writes = fake_github(monkeypatch, existing_commit="approved-commit", existing_pr=pr)
    publication["publication"] = {"commit_sha": "approved-commit", "branch": "forge/issue-4-abc123"}
    assert github.publish(publication, lambda _: None)["pr_number"] == 9
    assert not writes


def test_never_overwrite_unexpected_branch(monkeypatch, publication):
    github, writes = fake_github(monkeypatch, existing_commit="someone-elses-commit")
    publication["publication"] = {"commit_sha": "approved-commit"}
    with pytest.raises(PolicyError, match="unexpected changes"):
        github.publish(publication, lambda _: None)
    assert not writes


def test_tamper_or_expiry_blocks_github_writes(monkeypatch, publication):
    github, writes = fake_github(monkeypatch)
    expired = copy.deepcopy(publication)
    expired["approval"]["expires"] = 1
    with pytest.raises(PolicyError, match="expired"):
        github.publish(expired, lambda _: None)
    publication["candidate"]["patch"] = "other changes"
    with pytest.raises(PolicyError, match="changed"):
        github.publish(publication, lambda _: None)
    assert not writes


def test_external_contribution_writes_only_to_verified_owner_fork(monkeypatch, publication, tmp_path):
    github, writes = fake_github(monkeypatch)
    github.config = Settings(
        github_auth="cli",
        allowed_repositories="owner/repo",
        publish_enabled=True,
        data_dir=tmp_path,
        _env_file=None,
    )
    publication["context"]["can_push"] = False
    original_request = github.request

    def request(method, path, token, **kwargs):
        if path == "/user":
            return {"login": "contributor"}
        if path.endswith("/forks"):
            if method == "GET":
                return []
            writes.append((path, kwargs["json"]))
            return {"full_name": "contributor/repo"}
        if path == "/repos/contributor/repo":
            return {"owner": {"login": "contributor"}, "parent": {"id": 1}}
        return original_request(method, path, token, **kwargs)

    monkeypatch.setattr(github, "request", request)
    result = github.publish(publication, lambda _: None)
    assert result["write_repo"] == "contributor/repo"
    assert all(path.startswith("/repos/contributor/repo/git/") for path, _ in writes if "/git/" in path)
    assert writes[-1][0] == "/repos/owner/repo/pulls"
    assert writes[-1][1]["head"].startswith("contributor:")
    assert writes[-1][1]["draft"] is True


def test_foreign_fork_identity_blocks_commit(monkeypatch, publication, tmp_path):
    github, writes = fake_github(monkeypatch)
    github.config = Settings(
        github_auth="cli",
        allowed_repositories="owner/repo",
        publish_enabled=True,
        data_dir=tmp_path,
        _env_file=None,
    )
    publication["context"]["can_push"] = False
    original_request = github.request

    def request(method, path, token, **kwargs):
        if path == "/user":
            return {"login": "contributor"}
        if path.endswith("/forks"):
            return [{"full_name": "attacker/repo", "owner": {"login": "contributor"}}]
        if path == "/repos/attacker/repo":
            return {"owner": {"login": "attacker"}, "parent": {"id": 99}}
        return original_request(method, path, token, **kwargs)

    monkeypatch.setattr(github, "request", request)
    with pytest.raises(PolicyError, match="identity"):
        github.publish(publication, lambda _: None)
    assert not writes
