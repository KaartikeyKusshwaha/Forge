import io
import tarfile

import pytest

from forge.config import Settings
from forge.github import read_archive
from forge.llm import verify_free
from forge.policy import PolicyError, apply_edits, fingerprint, safe_path, seal_candidate
from forge.sandbox import DemoSandbox


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/etc/passwd",
        "x/../../secret",
        "C:/x",
        "a\\b",
        ".git/config",
        "a/./b",
        "a//b",
        "NUL.py",
        "file. ",
    ],
)
def test_unsafe_paths_rejected(path):
    with pytest.raises(PolicyError):
        safe_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "auth/login.py",
        "package.json",
        "requirements.txt",
        ".env",
        "migrations/001.sql",
    ],
)
def test_protected_paths_rejected(path):
    with pytest.raises(PolicyError):
        apply_edits({"main.py": "pass\n"}, [{"path": path, "content": "changed\n"}])


def test_candidate_fingerprint_includes_evidence():
    c = seal_candidate(
        "base", {"a.py": "before\n"}, {"a.py": "after\n"}, [{"exit_code": 0}], {"acceptable": True}, "python"
    )
    assert fingerprint(c) == c["fingerprint"]
    c["checks"][0]["exit_code"] = 1
    assert fingerprint(c) != c["fingerprint"]


def test_demo_cannot_execute_arbitrary_model_output():
    with pytest.raises(PolicyError):
        DemoSandbox().check({"evil.py": "raise SystemExit(0)"}, "candidate")


def test_archive_rejects_symlinks_and_traversal():
    for name, kind in [("repo/../../secret", tarfile.REGTYPE), ("repo/link", tarfile.SYMTYPE)]:
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            archive.addfile(member, io.BytesIO())
        with pytest.raises(PolicyError):
            read_archive(data.getvalue())


@pytest.mark.parametrize(
    "url", ["https://api.deepseek.com/v1", "https://api.openai.com/v1", "https://attacker.example/v1"]
)
def test_paid_or_unverified_endpoint_is_blocked(url):
    config = Settings(llm_base_url=url, llm_model="some-model", _env_file=None)
    with pytest.raises(PolicyError):
        verify_free(config)


def test_local_provider_requires_loopback():
    with pytest.raises(PolicyError):
        verify_free(Settings(llm_provider="local", llm_base_url="http://192.168.1.2/v1", _env_file=None))


def test_paid_model_id_not_in_verified_free_catalog(monkeypatch):
    monkeypatch.setattr("forge.llm.free_models", lambda: [{"id": "qwen/model:free"}])
    with pytest.raises(PolicyError):
        verify_free(Settings(llm_model="qwen/model", _env_file=None))
    assert verify_free(Settings(llm_model="auto", _env_file=None))["id"] == "qwen/model:free"
