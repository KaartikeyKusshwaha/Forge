"""GitHub transport. No target code is ever imported or executed here."""

import hashlib
import io
import re
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

    def token(self, repo_id: int | None = None, write: bool = False) -> str:
        if not self.config.github_ready:
            raise GitHubError("Configure a GitHub App and installation before starting a repository run.")
        now = int(time.time())
        key = Path(self.config.github_private_key_path).read_text()
        app_token = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.config.github_app_id}, key, algorithm="RS256"
        )
        body = {
            "permissions": {
                "contents": "write" if write else "read",
                "issues": "read",
                "pull_requests": "write" if write else "read",
            }
        }
        if repo_id:
            body["repository_ids"] = [repo_id]
        return self.request(
            "POST",
            f"/app/installations/{self.config.github_installation_id}/access_tokens",
            app_token,
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

    def context(self, repo: str, issue: int) -> dict:
        self.validate_repo(repo)
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
        item = self.request("GET", f"/repos/{repo}/issues/{issue}", token)
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
        token = self.token(ctx["repo_id"], write=True)
        root = f"/repos/{run['repo']}"
        current = self.request("GET", root + "/commits/" + ctx["branch"], token)
        if current["sha"] != candidate["base_sha"]:
            raise PolicyError("The base branch moved. Start a new run and approve its revalidated patch.")
        # Git database API avoids running git hooks, filters, or target-side scripts.
        branch = f"forge/issue-{run['issue']}-{run['id'][:10]}"
        publication = run.get("publication", {})
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
                "POST", root + "/git/trees", token, json={"base_tree": ctx["base_tree"], "tree": tree}
            )
            commit = self.request(
                "POST",
                root + "/git/commits",
                token,
                json={
                    "message": f"Fix #{run['issue']}: {ctx['title'][:120]}\n\nForge candidate {candidate['fingerprint']}",
                    "tree": new_tree["sha"],
                    "parents": [candidate["base_sha"]],
                },
            )
            commit_sha = commit["sha"]
            persist(dict(branch=branch, commit_sha=commit_sha))
        refs = self.request("GET", root + "/git/matching-refs/heads/" + branch, token)
        exact = [r for r in refs if r["ref"] == "refs/heads/" + branch]
        if exact and exact[0]["object"]["sha"] != commit_sha:
            raise PolicyError("Publication branch contains unexpected changes. It will not be overwritten.")
        if not exact:
            self.request(
                "POST", root + "/git/refs", token, json={"ref": "refs/heads/" + branch, "sha": commit_sha}
            )
        prs = self.request(
            "GET",
            root + "/pulls",
            token,
            params={"head": run["repo"].split("/")[0] + ":" + branch, "state": "all"},
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
                    "head": branch,
                    "base": ctx["branch"],
                    "draft": True,
                    "body": body,
                },
            )
        return dict(branch=branch, commit_sha=commit_sha, pr_url=pr["html_url"], pr_number=pr["number"])


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
