import difflib
import hashlib
import json
import re
from pathlib import PurePosixPath


class PolicyError(Exception):
    pass


def safe_path(path: str) -> str:
    if (
        not path
        or len(path) > 250
        or any(ord(c) < 32 for c in path)
        or "\\" in path
        or ":" in path
        or path.startswith("/")
    ):
        raise PolicyError("Unsafe repository path.")
    parts = path.split("/")
    if any(p in {"", ".", ".."} or p.lower() == ".git" or p.endswith((".", " ")) for p in parts):
        raise PolicyError("Unsafe repository path.")
    if any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts):
        raise PolicyError("Reserved repository path.")
    return str(PurePosixPath(path))


def protected(path: str) -> bool:
    p = path.lower()
    names = {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "dockerfile",
        "compose.yaml",
        "docker-compose.yml",
    }
    return (
        any(x in p.split("/") for x in (".github", "migrations", "auth", "secrets"))
        or p.split("/")[-1] in names
        or p.startswith(".env")
        or p.endswith((".pem", ".key", ".p12"))
    )


def eligible(path: str) -> bool:
    safe_path(path)
    return not (
        any(
            x in path.split("/")
            for x in ("node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".next")
        )
        or path.split("/")[-1].startswith(".env")
        or path.lower().endswith((".pem", ".key", ".p12"))
    )


def apply_edits(files: dict[str, str], edits: list[dict]) -> dict[str, str]:
    if not edits or len(edits) > 10:
        raise PolicyError("A candidate must change between 1 and 10 files.")
    result = files.copy()
    seen = set()
    for edit in edits:
        path = safe_path(edit["path"])
        if path in seen or protected(path) or not eligible(path):
            raise PolicyError(f"Editing {path} is blocked by the execution policy.")
        seen.add(path)
        text = edit["content"]
        if text is None:
            result.pop(path, None)
        elif isinstance(text, str) and len(text.encode()) <= 500_000 and "\x00" not in text:
            if re.search(
                r"(?:gh[pousr]_[A-Za-z0-9_]{24,}|-----BEGIN .*PRIVATE KEY-----|sk-[A-Za-z0-9]{24,})", text
            ):
                raise PolicyError("Candidate contains a likely secret.")
            result[path] = text
        else:
            raise PolicyError("Invalid file content or oversized edit.")
    lines = diff_files(files, result)
    if (
        sum(
            1
            for line in lines.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )
        > 500
    ):
        raise PolicyError("Patch exceeds the 500-line limit. Rescope this issue.")
    if not lines:
        raise PolicyError("The candidate contains no changes.")
    return result


def diff_files(before: dict, after: dict) -> str:
    chunks = []
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) != after.get(path):
            lines = difflib.unified_diff(
                before.get(path, "").splitlines(keepends=True),
                after.get(path, "").splitlines(keepends=True),
                fromfile=f"a/{path}" if path in before else "/dev/null",
                tofile=f"b/{path}" if path in after else "/dev/null",
            )
            for line in lines:
                chunks.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(chunks)


def fingerprint(candidate: dict) -> str:
    content = {k: v for k, v in candidate.items() if k != "fingerprint"}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def seal_candidate(base: str, before: dict, after: dict, checks: list, review: dict, profile: str) -> dict:
    changes = [
        {"path": p, "before": before.get(p), "after": after.get(p)}
        for p in sorted(before.keys() | after.keys())
        if before.get(p) != after.get(p)
    ]
    candidate = dict(
        base_sha=base,
        changes=changes,
        patch=diff_files(before, after),
        checks=checks,
        review=review,
        profile=profile,
        policy_version=1,
    )
    candidate["fingerprint"] = fingerprint(candidate)
    return candidate
