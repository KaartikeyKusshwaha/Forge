import pytest

from forge.config import Settings
from forge.github import GitHub, GitHubError


def test_cli_mode_requires_explicit_repository_allowlist(tmp_path):
    assert not Settings(
        data_dir=tmp_path, github_auth="cli", allowed_repositories="", _env_file=None
    ).github_ready
    assert Settings(
        data_dir=tmp_path, github_auth="cli", allowed_repositories="owner/fixture", _env_file=None
    ).github_ready


def test_cli_cannot_read_unlisted_repository(monkeypatch, tmp_path):
    github = GitHub(
        Settings(data_dir=tmp_path, github_auth="cli", allowed_repositories="owner/fixture", _env_file=None)
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Transport must not be called for an unlisted repository")

    monkeypatch.setattr(github, "token", forbidden)
    with pytest.raises(GitHubError, match="allowlist"):
        github.context("owner/sensitive-repo", 1)


def test_cli_repository_list_is_explicit_not_account_wide(monkeypatch, tmp_path):
    github = GitHub(
        Settings(data_dir=tmp_path, github_auth="cli", allowed_repositories="owner/fixture", _env_file=None)
    )
    monkeypatch.setattr(github, "token", lambda: "not-returned-to-browser")
    requests = []

    def request(method, path, token):
        requests.append(path)
        return {"id": 10, "full_name": "owner/fixture", "private": False, "default_branch": "main"}

    monkeypatch.setattr(github, "request", request)
    assert github.repositories() == [
        {"id": 10, "name": "owner/fixture", "private": False, "default_branch": "main"}
    ]
    assert requests == ["/repos/owner/fixture"]
