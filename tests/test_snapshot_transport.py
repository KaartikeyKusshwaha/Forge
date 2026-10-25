import json

import pytest

from forge.actions import ActionsSandbox
from forge.config import Settings
from forge.policy import PolicyError
from forge.snapshot import public_snapshot, reconstruct


def test_reconstruction_preserves_exact_source_and_applies_only_overlay(monkeypatch):
    monkeypatch.setattr(
        "forge.snapshot.public_snapshot", lambda *_: {"a.py": "old", "b.py": "delete", "unchanged": "keep"}
    )
    files, raw = reconstruct(
        {"edits": {"a.py": "new", "b.py": None, "new.py": "added"}}, "owner/repo", "a" * 40
    )
    assert files == {"a.py": "new", "unchanged": "keep", "new.py": "added"}
    assert raw == json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(PolicyError):
        reconstruct({"edits": {"../escape": "bad"}}, "owner/repo", "a" * 40)


def test_remote_source_rejects_unpinned_or_unsafe_urls_before_network():
    for repo, sha in [("owner/repo", "main"), ("../repo", "a" * 40), ("https://evil.test", "a" * 40)]:
        with pytest.raises(PolicyError, match="exact commit"):
            public_snapshot(repo, sha)


def test_large_repository_dispatches_small_overlay(monkeypatch):
    import base64
    import gzip
    import hashlib
    import random

    sandbox = ActionsSandbox(Settings(_env_file=None))
    randomizer = random.Random(42)
    files = {"large.txt": "".join(randomizer.choices("abcdef0123456789", k=250000)), "test.py": "old"}
    sandbox.set_source({"repo": "owner/repo", "base_sha": "a" * 40}, files)
    candidate = {**files, "test.py": "new"}
    monkeypatch.setattr(sandbox, "available", lambda: True)
    captured = []

    def gh(args, payload=None):
        if payload:
            captured.append(payload)
            raise PolicyError("Fixture ends after dispatch capture")
        return {"private": False, "fork": False}

    monkeypatch.setattr(sandbox, "gh", gh)
    with pytest.raises(PolicyError, match="Fixture ends"):
        sandbox.check(candidate, "candidate")
    inputs = captured[0]["inputs"]
    assert inputs["source_sha"] == "a" * 40
    assert len(inputs["snapshot"]) < 1000
    assert json.loads(gzip.decompress(base64.b64decode(inputs["snapshot"]))) == {"edits": {"test.py": "new"}}
    assert (
        inputs["digest"]
        == hashlib.sha256(json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
