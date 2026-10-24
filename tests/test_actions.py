import json

import pytest

from forge.actions import ActionsSandbox
from forge.config import Settings
from forge.policy import PolicyError


def test_runner_rejects_private_execution_repository(monkeypatch):
    sandbox = ActionsSandbox(Settings(_env_file=None))
    monkeypatch.setattr(sandbox, "available", lambda: True)
    monkeypatch.setattr(sandbox, "gh", lambda *a, **k: {"private": True})
    with pytest.raises(PolicyError, match="public"):
        sandbox.check({"test.py": "pass"}, "baseline")


def test_runner_dispatch_and_evidence_are_bound_to_snapshot(monkeypatch):
    sandbox = ActionsSandbox(Settings(_env_file=None))
    monkeypatch.setattr(sandbox, "available", lambda: True)
    calls = []

    def gh(args, payload=None):
        calls.append((args, payload))
        if args[0] == "api" and args[1] == "repos/KaartikeyKusshwaha/Forge":
            return {"private": False, "fork": False}
        if payload:
            return {}
        request = calls[1][1]["inputs"]
        if args[0] == "api":
            return {
                "workflow_runs": [
                    {
                        "display_title": "forge-check " + request["request_id"],
                        "id": 123,
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "trusted-sha",
                        "html_url": "https://github.com/owner/runner/actions/runs/123",
                    }
                ]
            }
        folder = args[args.index("--dir") + 1]
        from pathlib import Path

        Path(folder, "result.json").write_text(
            json.dumps(
                {
                    "request_id": request["request_id"],
                    "snapshot_digest": request["digest"],
                    "count": 1,
                    "exit_code": 0,
                    "command": "pytest",
                    "output": "passed",
                }
            )
        )
        return {}

    monkeypatch.setattr(sandbox, "gh", gh)
    result = sandbox.check({"test_x.py": "def test_x(): assert True\n"}, "candidate")
    assert result["status"] == "passed"
    assert result["image"] == "github-vm:trusted-sha"
    assert "docker" not in json.dumps(calls).lower()


def test_runner_never_executes_target_locally(monkeypatch):
    sandbox = ActionsSandbox(Settings(_env_file=None))
    monkeypatch.setattr(sandbox, "available", lambda: False)
    with pytest.raises(PolicyError, match="GitHub CLI"):
        sandbox.check({"untrusted.py": "raise SystemExit(0)"}, "candidate")


def test_groq_cannot_run_without_free_plan_confirmation():
    from forge.llm import verify_free

    with pytest.raises(PolicyError, match="confirmation"):
        verify_free(
            Settings(
                llm_provider="groq-free",
                llm_base_url="https://api.groq.com/openai/v1",
                groq_free_plan_confirmed=False,
                _env_file=None,
            )
        )
