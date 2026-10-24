"""Disposable public GitHub-hosted VMs. No Docker and no target-code execution locally."""

import base64
import gzip
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from forge.config import Settings
from forge.policy import PolicyError, safe_path


class ActionsSandbox:
    def __init__(self, config: Settings):
        self.config = config

    @staticmethod
    def available() -> bool:
        if not shutil.which("gh"):
            return False
        try:
            return subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def gh(self, args, payload=None):
        result = subprocess.run(
            ["gh", *args],
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
        if result.returncode:
            raise PolicyError(
                "GitHub runner request failed. Check GitHub CLI access, workflow availability, and Actions limits."
            )
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except ValueError:
            raise PolicyError("GitHub runner returned an invalid response.") from None

    def check(self, files, phase, cancelled=lambda: False, profile="python"):
        if profile not in {"python", "typescript"}:
            raise PolicyError("Unsupported runner profile.")
        if not self.available():
            raise PolicyError("Sign in to GitHub CLI to use the isolated GitHub Actions runner.")
        repo = self.config.runner_repository
        from forge.github import GitHub

        GitHub.validate_repo(repo)
        metadata = self.gh(["api", f"repos/{repo}"])
        if metadata.get("private") is not False or metadata.get("fork"):
            raise PolicyError(
                "The execution repository must be a trusted public, non-fork repository for free Actions execution."
            )
        for path in files:
            safe_path(path)
        raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > 50_000_000 or len(files) > 10_000:
            raise PolicyError("Snapshot exceeds the supported runner limits.")
        packed = base64.b64encode(gzip.compress(raw)).decode()
        if len(packed) > 58_000:
            raise PolicyError(
                "Compressed snapshot exceeds the GitHub dispatch limit. Choose a smaller repository or subtree; no local execution fallback exists."
            )
        request_id = uuid.uuid4().hex
        digest = hashlib.sha256(raw).hexdigest()
        self.gh(
            ["api", f"repos/{repo}/actions/workflows/forge-check.yml/dispatches", "--input", "-"],
            {
                "ref": self.config.runner_ref,
                "inputs": {
                    "request_id": request_id,
                    "profile": profile,
                    "snapshot": packed,
                    "digest": digest,
                },
            },
        )
        start = time.monotonic()
        run_id = None
        while time.monotonic() - start < self.config.runner_timeout_seconds:
            if cancelled():
                if run_id:
                    self.gh(["api", "--method", "POST", f"repos/{repo}/actions/runs/{run_id}/cancel"])
                raise PolicyError("Run cancelled. Any discovered remote check was cancelled too.")
            runs = self.gh(["api", f"repos/{repo}/actions/workflows/forge-check.yml/runs?per_page=50"])[
                "workflow_runs"
            ]
            matched = [r for r in runs if r.get("display_title") == "forge-check " + request_id]
            if matched:
                remote = matched[0]
                run_id = remote["id"]
                if remote["status"] == "completed":
                    if remote["conclusion"] != "success":
                        raise PolicyError(f"Isolated runner could not complete. Inspect {remote['html_url']}")
                    with tempfile.TemporaryDirectory(prefix="forge-check-result-") as directory:
                        self.gh(
                            [
                                "run",
                                "download",
                                str(run_id),
                                "--repo",
                                repo,
                                "--name",
                                "forge-check-" + request_id,
                                "--dir",
                                directory,
                            ]
                        )
                        path = Path(directory, "result.json")
                        if not path.is_file() or path.stat().st_size > 300_000:
                            raise PolicyError("Missing or oversized isolated-runner report.")
                        result = json.loads(path.read_text(encoding="utf-8"))
                    if result.get("request_id") != request_id or result.get("snapshot_digest") != digest:
                        raise PolicyError("Runner evidence belongs to a different snapshot.")
                    if not isinstance(result.get("count"), int) or result["count"] < 0:
                        raise PolicyError("Runner returned an invalid test count.")
                    result.update(
                        phase=phase,
                        image="github-vm:" + remote["head_sha"],
                        environment="Disposable GitHub VM · systemd isolation · no network · non-root",
                        seconds=round(time.monotonic() - start, 2),
                        run_url=remote["html_url"],
                    )
                    result["status"] = (
                        "passed" if result["exit_code"] == 0 and result["count"] > 0 else "failed"
                    )
                    return result
            for _ in range(20):
                if cancelled():
                    break
                time.sleep(0.25)
        if run_id:
            self.gh(["api", "--method", "POST", f"repos/{repo}/actions/runs/{run_id}/cancel"])
        raise PolicyError("GitHub runner wait budget exceeded. No local execution fallback exists.")
