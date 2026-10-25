import base64

import pytest

from forge.config import Settings
from forge.github import GitHub, GitHubError


def test_public_repository_analysis_enables_only_requested_repo_and_persists(monkeypatch, tmp_path):
    config = Settings(
        github_auth="cli", allowed_repositories="owner/fixture", data_dir=tmp_path, _env_file=None
    )
    github = GitHub(config)
    monkeypatch.setattr(github, "token", lambda: "fixture")
    calls = []

    def request(method, path, token, **kwargs):
        calls.append(method)
        if path == "/repos/upstream/blender-tools":
            return {"private": False, "default_branch": "main", "description": "Blender tools"}
        if "/commits/" in path:
            return {"sha": "a" * 40}
        if "/git/trees/" in path:
            return {"tree": [{"path": p, "type": "blob"} for p in ("CONTRIBUTING.md", "tests/test_tools.py")]}
        if "/contents/" in path:
            assert kwargs["params"]["ref"] == "a" * 40
            return {
                "encoding": "base64",
                "size": 10,
                "content": base64.b64encode(b"Run tests first.").decode(),
            }
        if path.endswith("/issues"):
            return [{"number": 3, "title": "Fix a tool"}, {"number": 4, "title": "A PR", "pull_request": {}}]
        pytest.fail(path)

    monkeypatch.setattr(github, "request", request)
    assert github.analyze_repository("upstream/blender-tools")["enabled"] is False
    result = github.analyze_repository("upstream/blender-tools", enable=True)
    assert result["enabled"] is True
    assert result["issues"] == [{"number": 3, "title": "Fix a tool"}]
    assert result["guides"][0]["text"] == "Run tests first."
    assert any("Blender" in line for line in result["limitations"])
    assert GitHub(config).selected_repositories() == ["owner/fixture", "upstream/blender-tools"]
    assert set(calls) == {"GET"}


def test_private_repository_is_not_enabled(monkeypatch, tmp_path):
    github = GitHub(Settings(github_auth="cli", data_dir=tmp_path, _env_file=None))
    monkeypatch.setattr(github, "token", lambda: "fixture")
    monkeypatch.setattr(github, "request", lambda *_: {"private": True})
    with pytest.raises(GitHubError, match="public"):
        github.analyze_repository("owner/private", enable=True)
    assert not (tmp_path / "repositories.json").exists()
