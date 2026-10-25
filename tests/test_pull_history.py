import pytest

from forge.config import Settings
from forge.github import GitHub, GitHubError


def test_pull_history_tracks_state_without_writing(monkeypatch):
    github = GitHub(Settings())
    monkeypatch.setattr(github, "repositories", lambda: [{"id": 1, "name": "owner/repo", "private": False}])
    monkeypatch.setattr(github, "token", lambda repo_id: "test-only")
    calls = []

    def request(method, path, token):
        calls.append((method, path))
        if "/pulls/" in path:
            return {
                "state": "closed",
                "created_at": "2026-10-24T10:00:00Z",
                "updated_at": "2026-10-25T10:00:00Z",
                "merged_at": "2026-10-25T10:00:00Z",
            }
        return [
            {
                "event": "review_requested",
                "created_at": "2026-10-24T11:00:00Z",
                "actor": {"login": "reviewer"},
            }
        ]

    monkeypatch.setattr(github, "request", request)
    result = github.pull_history("owner/repo", 2)
    assert result["state"] == "merged"
    assert [e["event"] for e in result["events"]] == ["opened", "review_requested", "merged"]
    assert all(method == "GET" for method, _ in calls)


def test_pull_history_rejects_unselected_and_private_repos(monkeypatch):
    github = GitHub(Settings())
    monkeypatch.setattr(github, "repositories", lambda: [{"id": 1, "name": "owner/private", "private": True}])
    monkeypatch.setattr(github, "token", lambda *_: pytest.fail("Must check access before token creation"))
    for repo in ("other/repo", "owner/private"):
        with pytest.raises(GitHubError):
            github.pull_history(repo, 1)
