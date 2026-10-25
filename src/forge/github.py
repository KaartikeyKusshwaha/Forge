"""GitHub transport. No target code is ever imported or executed here."""

import base64
import hashlib
import io
import json
import re
import subprocess
import tarfile
import time
from pathlib import Path

import httpx
import jwt

from forge.config import Settings
from forge.policy import PolicyError, eligible, fingerprint, safe_path


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, config: Settings):
        self.config = config

    def selected_repositories(self):
        selected = {r.strip() for r in self.config.allowed_repositories.split(",") if r.strip()}
        path = self.config.data_dir / "repositories.json"
        if path.exists():
            selected.update(json.loads(path.read_text(encoding="utf-8")))
        return sorted(selected)

    def analyze_repository(self, repo: str, enable: bool = False):
        self.validate_repo(repo)
        token = self.token()
        metadata = self.request("GET", f"/repos/{repo}", token)
        if metadata.get("private"):
            raise GitHubError("Only public repositories are supported.")
        if enable:
            if self.config.github_auth != "cli":
                raise GitHubError("Select repositories through your GitHub App installation settings.")
            selected = self.selected_repositories()
            if repo.lower() not in {r.lower() for r in selected}:
                selected.append(repo)
            self.config.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.config.data_dir / "repositories.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(selected), encoding="utf-8")
            temporary.replace(path)
        branch = metadata["default_branch"]
        commit = self.request("GET", f"/repos/{repo}/commits/{branch}", token)
        sha = commit["sha"]
        tree = self.request("GET", f"/repos/{repo}/git/trees/{sha}?recursive=1", token)
        paths = [e["path"] for e in tree.get("tree", []) if e["type"] == "blob"]
        guides = []
        for path in paths:
            if path.lower() in {
                "contributing.md",
                ".github/contributing.md",
                "agents.md",
                "pyproject.toml",
                "package.json",
            }:
                entry = self.request("GET", f"/repos/{repo}/contents/{path}", token, params={"ref": sha})
                if entry.get("encoding") == "base64" and entry.get("size", 0) < 50000:
                    guides.append(
                        {
                            "path": path,
                            "text": base64.b64decode(entry["content"]).decode("utf-8", errors="replace")[
                                :12000
                            ],
                        }
                    )
        issues = self.request("GET", f"/repos/{repo}/issues", token, params={"state": "open", "per_page": 30})
        limits = [
            "Execution supports Python/Node test profiles without automatic dependency installation.",
            "Runner payload is limited to 58 KB compressed; large snapshots stop without execution.",
        ]
        if "blender" in repo.lower():
            limits.append(
                "Blender-dependent checks require a Blender runtime and are not supported by the current runner."
            )
        if tree.get("truncated"):
            limits.append("Repository tree is truncated; full analysis is unavailable.")
        return {
            "repo": repo,
            "description": metadata.get("description"),
            "base_sha": sha,
            "enabled": repo.lower() in {r.lower() for r in self.selected_repositories()},
            "file_count": len(paths),
            "tests": [p for p in paths if "test" in p.lower()][:30],
            "guides": guides,
            "limitations": limits,
            "issues": [
                {"number": i["number"], "title": i["title"]} for i in issues if "pull_request" not in i
            ],
        }

    def app_request(self, method: str, path: str, **kwargs):
        if not self.config.github_app_id or not self.config.github_private_key_path:
            raise GitHubError("Configure a GitHub App first.")
        now = int(time.time())
        key = Path(self.config.github_private_key_path).read_text()
        app_token = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.config.github_app_id}, key, algorithm="RS256"
        )
        return self.request(method, path, app_token, **kwargs)

    def token(self, repo_id: int | None = None, write: bool = False) -> str:
        if not self.config.github_ready and self.config.github_auth != "cli":
            raise GitHubError("Configure a GitHub App and installation before starting a repository run.")
        if self.config.github_auth == "cli":
            result = subprocess.run(
                ["gh", "auth", "token", "--hostname", "github.com"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode or not result.stdout.strip():
                raise GitHubError("GitHub CLI is not signed in. No credentials were returned.")
            return result.stdout.strip()
        body = {
            "permissions": {
                "contents": "write" if write else "read",
                "issues": "read",
                "pull_requests": "write" if write else "read",
            }
        }
        if repo_id:
            body["repository_ids"] = [repo_id]
        return self.app_request(
            "POST",
            f"/app/installations/{self.config.github_installation_id}/access_tokens",
            json=body,
        )["token"]

    def request(self, method: str, path: str, token: str, **kwargs):
        if not path.startswith("/") or path.startswith("//"):
            raise GitHubError("Invalid GitHub endpoint.")
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.request(
                    method,
                    "https://api.github.com" + path,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    **kwargs,
                )
            if response.status_code >= 400:
                # Never include transport headers or arbitrary upstream response bodies.
                raise GitHubError(
                    f"GitHub returned HTTP {response.status_code}. Check installation access and rate limits."
                )
            return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise GitHubError("GitHub is unavailable. Retry when the connection is restored.") from exc

    def repositories(self) -> list[dict]:
        token = self.token()
        if self.config.github_auth == "cli":
            selected = self.selected_repositories()
            result = []
            for repo in selected:
                self.validate_repo(repo)
                r = self.request("GET", f"/repos/{repo}", token)
                result.append(
                    {
                        "id": r["id"],
                        "name": r["full_name"],
                        "private": r["private"],
                        "default_branch": r["default_branch"],
                    }
                )
            return result
        result = []
        for page in range(1, 11):
            data = self.request("GET", f"/installation/repositories?per_page=100&page={page}", token)
            result.extend(
                {
                    "id": r["id"],
                    "name": r["full_name"],
                    "private": r["private"],
                    "default_branch": r["default_branch"],
                }
                for r in data["repositories"]
            )
            if len(data["repositories"]) < 100:
                break
        return result

    def pull_history(self, repo: str, number: int) -> dict:
        """Read PR milestones within the configured installation; never execute code."""
        self.validate_repo(repo)
        selected = next((r for r in self.repositories() if r["name"].lower() == repo.lower()), None)
        if not selected or selected["private"]:
            raise GitHubError("Pull request is outside the configured public repositories.")
        token = self.token(selected["id"])
        pull = self.request("GET", f"/repos/{repo}/pulls/{number}", token)
        events = self.request("GET", f"/repos/{repo}/issues/{number}/events?per_page=100", token)
        commits = self.request("GET", f"/repos/{repo}/pulls/{number}/commits?per_page=100", token)
        milestones = [{"event": "opened", "created_at": pull["created_at"]}]
        milestones.extend(
            {"event": e["event"], "created_at": e["created_at"], "actor": (e.get("actor") or {}).get("login")}
            for e in events
            if e.get("created_at")
        )
        for name in ("closed", "merged"):
            if pull.get(name + "_at"):
                milestones.append({"event": name, "created_at": pull[name + "_at"]})
        unique = {(e["event"], e["created_at"]): e for e in milestones}
        return {
            "number": number,
            "state": "merged" if pull.get("merged_at") else pull["state"],
            "draft": pull.get("draft", False),
            "updated_at": pull["updated_at"],
            "events": sorted(unique.values(), key=lambda e: e["created_at"]),
            "limited": len(events) == 100,
            "commits": [
                {
                    "sha": c["sha"],
                    "message": c["commit"]["message"].splitlines()[0],
                    "created_at": (c["commit"].get("committer") or {}).get("date"),
                }
                for c in commits
            ],
            "commits_limited": len(commits) == 100,
        }

    def context(self, repo: str, issue: int, request: str = "") -> dict:
        self.validate_repo(repo)
        if self.config.github_auth == "cli" and repo.lower() not in {
            r.lower() for r in self.selected_repositories()
        }:
            raise GitHubError("Repository is outside the owner's explicit local allowlist.")
        token = self.token()
        metadata = self.request("GET", f"/repos/{repo}", token)
        if metadata.get("private"):
            raise GitHubError(
                "Private repositories are disabled in this pilot until provider data handling is configured."
            )
        # Repository IDs from the configured installation are authoritative.
        if metadata["id"] not in {r["id"] for r in self.repositories()}:
            raise GitHubError("Repository is outside this installation.")
        token = self.token(metadata["id"])
        item = (
            self.request("GET", f"/repos/{repo}/issues/{issue}", token)
            if issue
            else {
                "title": request.splitlines()[0][:200],
                "body": request,
                "html_url": f"https://github.com/{repo}",
            }
        )
        if "pull_request" in item:
            raise GitHubError("Start Forge from an issue, rather than a pull request.")
        branch = metadata["default_branch"]
        commit = self.request("GET", f"/repos/{repo}/commits/{branch}", token)
        tree = self.request(
            "GET", f"/repos/{repo}/git/trees/{commit['commit']['tree']['sha']}?recursive=1", token
        )
        if tree.get("truncated") or len(tree["tree"]) > 10_000:
            raise GitHubError("Repository tree exceeds the supported pilot size.")
        return dict(
            repo_id=metadata["id"],
            can_push=self.config.github_auth == "app" or metadata.get("permissions", {}).get("push", False),
            repo=repo,
            issue=issue,
            title=item["title"],
            body=(item.get("body") or "")[:30_000],
            issue_url=item["html_url"],
            base_sha=commit["sha"],
            base_tree=commit["commit"]["tree"]["sha"],
            branch=branch,
            file_modes={entry["path"]: entry["mode"] for entry in tree["tree"] if entry["type"] == "blob"},
        )

    @staticmethod
    def validate_repo(repo: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or ".." in repo:
            raise GitHubError("Expected a GitHub owner/repository name.")

    def snapshot(self, context: dict) -> dict[str, str]:
        token = self.token(context["repo_id"])
        # GitHub archives redirect to codeload. Constrain that origin and omit the API credential.
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            response = client.get(
                f"https://api.github.com/repos/{context['repo']}/tarball/{context['base_sha']}",
                headers={"Authorization": "Bearer " + token},
            )
            location = response.headers.get("location", "")
            if response.status_code != 302 or not location.startswith("https://codeload.github.com/"):
                raise GitHubError("GitHub did not provide an authorized source archive.")
            chunks, total = [], 0
            with client.stream("GET", location) as stream:
                stream.raise_for_status()
                for chunk in stream.iter_bytes():
                    total += len(chunk)
                    if total > 50_000_000:
                        raise PolicyError("Repository archive exceeds the 50 MB pilot limit.")
                    chunks.append(chunk)
        return read_archive(b"".join(chunks))

    def publish(self, run: dict, persist) -> dict:
        candidate = run["candidate"]
        approval = run.get("approval", {})
        if run["status"] != "publishing" or run.get("cancel") or not self.config.publish_enabled:
            raise PolicyError("This run is not authorized for publication.")
        if approval.get("actor") != "local-owner":
            raise PolicyError("A human owner approval is required.")
        if (
            candidate["fingerprint"] != fingerprint(candidate)
            or approval.get("fingerprint") != candidate["fingerprint"]
        ):
            raise PolicyError("Candidate changed after approval.")
        if time.time() > approval.get("expires", 0):
            raise PolicyError("Approval expired. Review the candidate again.")
        ctx = run["context"]
        if self.config.github_auth == "cli" and run["repo"].lower() not in {
            r.lower() for r in self.selected_repositories()
        }:
            raise PolicyError("Repository access was removed from the owner's allowlist.")
        token = self.token(ctx["repo_id"], write=True)
        root = f"/repos/{run['repo']}"
        current = self.request("GET", root + "/commits/" + ctx["branch"], token)
        if current["sha"] != candidate["base_sha"]:
            raise PolicyError("The base branch moved. Start a new run and approve its revalidated patch.")
        # Git database API avoids running git hooks, filters, or target-side scripts.
        branch = f"forge/issue-{run['issue']}-{run['id'][:10]}"
        publication = run.get("publication", {})
        write_repo = run["repo"]
        if not ctx.get("can_push", True):
            if self.config.github_auth != "cli":
                raise PolicyError("Fork publishing currently requires the owner's GitHub CLI account.")
            owner = self.request("GET", "/user", token)["login"]
            forks = self.request("GET", root + "/forks", token, params={"per_page": 100})
            fork = next(
                (f for f in forks if f.get("owner", {}).get("login", "").lower() == owner.lower()), None
            )
            if not fork:
                fork = self.request("POST", root + "/forks", token, json={"default_branch_only": True})
            write_repo = fork["full_name"]
            verified = self.request("GET", f"/repos/{write_repo}", token)
            if (
                verified.get("owner", {}).get("login", "").lower() != owner.lower()
                or verified.get("parent", {}).get("id") != ctx["repo_id"]
            ):
                raise PolicyError("Fork ownership or upstream identity could not be verified.")
        write_root = f"/repos/{write_repo}"
        if publication.get("write_repo", write_repo) != write_repo:
            raise PolicyError(
                "Publication account or target changed. Review a fresh proposal before retrying."
            )
        head = branch if write_repo == run["repo"] else write_repo.split("/")[0] + ":" + branch
        commit_sha = publication.get("commit_sha")
        if not commit_sha:
            tree = []
            for change in candidate["changes"]:
                entry = {
                    "path": safe_path(change["path"]),
                    "mode": ctx.get("file_modes", {}).get(change["path"], "100644"),
                    "type": "blob",
                }
                if change["after"] is None:
                    entry["sha"] = None
                else:
                    entry["content"] = change["after"]
                tree.append(entry)
            new_tree = self.request(
                "POST", write_root + "/git/trees", token, json={"base_tree": ctx["base_tree"], "tree": tree}
            )
            commit = self.request(
                "POST",
                write_root + "/git/commits",
                token,
                json={
                    "message": f"{ctx['title'][:120]}\n\nForge candidate {candidate['fingerprint']}",
                    "tree": new_tree["sha"],
                    "parents": [candidate["base_sha"]],
                },
            )
            commit_sha = commit["sha"]
            persist(dict(branch=branch, commit_sha=commit_sha, write_repo=write_repo))
        refs = self.request("GET", write_root + "/git/matching-refs/heads/" + branch, token)
        exact = [r for r in refs if r["ref"] == "refs/heads/" + branch]
        if exact and exact[0]["object"]["sha"] != commit_sha:
            raise PolicyError("Publication branch contains unexpected changes. It will not be overwritten.")
        if not exact:
            self.request(
                "POST",
                write_root + "/git/refs",
                token,
                json={"ref": "refs/heads/" + branch, "sha": commit_sha},
            )
        prs = self.request(
            "GET",
            root + "/pulls",
            token,
            params={"head": write_repo.split("/")[0] + ":" + branch, "state": "all"},
        )
        if prs:
            pr = prs[0]
        else:
            summary = run.get("summary", "Focused changes prepared by Forge.")
            check_lines = "\n".join(
                f"- {c['phase']}: {c['command']} — {c['status']} ({c['count']} tests)"
                for c in candidate["checks"]
            )
            body = (
                f"Issue: {ctx['issue_url']}\n\n{summary}\n\n### Validation\n{check_lines}"
                f"\n\nCandidate: `{candidate['fingerprint']}`\n"
                f"Model: `{run.get('model', 'unknown')}`\n\n"
                "Human-approved Forge proposal. Review before merging. No deployment was performed."
            )
            pr = self.request(
                "POST",
                root + "/pulls",
                token,
                json={
                    "title": ctx["title"][:200],
                    "head": head,
                    "base": ctx["branch"],
                    "draft": True,
                    "body": body,
                },
            )
        return dict(
            branch=branch,
            commit_sha=commit_sha,
            write_repo=write_repo,
            pr_url=pr["html_url"],
            pr_number=pr["number"],
        )


def read_archive(content: bytes) -> dict[str, str]:
    files, size, count = {}, 0, 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            count += 1
            if count > 10_000:
                raise PolicyError("Repository exceeds 10,000 entries.")
            path = member.name.partition("/")[2]
            if not path or member.isdir():
                continue
            safe_path(path)
            if not member.isfile():
                raise PolicyError("Symlinks, submodules, and special files are unsupported in this pilot.")
            size += member.size
            if size > 50_000_000:
                raise PolicyError("Expanded repository exceeds 50 MB.")
            if member.size > 500_000 or not eligible(path):
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            raw = source.read(500_001)
            if b"\x00" in raw:
                continue
            try:
                files[path] = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
    if not files:
        raise PolicyError("No supported source text found.")
    return files


def demo_context() -> tuple[dict, dict]:
    files = {
        "pagination.py": 'def validate_limit(limit: int) -> int:\n    """Validate a requested page size."""\n    if limit < 0 or limit > 100:\n        raise ValueError("limit must be between 1 and 100")\n    return limit\n',
        "test_pagination.py": "import unittest\nfrom pagination import validate_limit\n\nclass PaginationTests(unittest.TestCase):\n    def test_valid_limit(self):\n        self.assertEqual(validate_limit(20), 20)\n\n    def test_negative_limit(self):\n        with self.assertRaises(ValueError):\n            validate_limit(-1)\n\n    def test_upper_bound(self):\n        with self.assertRaises(ValueError):\n            validate_limit(101)\n",
        "README.md": "# Sample API\nPage sizes must be between 1 and 100, inclusive.\n",
    }
    sha = hashlib.sha1(str(sorted(files.items())).encode(), usedforsecurity=False).hexdigest()
    return dict(
        repo_id=0,
        repo="forge-demo/sample-api",
        issue=42,
        title="Reject a page size of zero",
        body="validate_limit(0) currently returns 0. Reject zero with ValueError; retain valid values 1–100.",
        issue_url="",
        base_sha=sha,
        branch="main",
        base_tree="",
    ), files
