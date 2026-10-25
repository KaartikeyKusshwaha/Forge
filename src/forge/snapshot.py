"""Pure source loading shared by the local coordinator and trusted VM controller."""

import io
import json
import re
import tarfile
import urllib.request

from forge.policy import PolicyError, eligible, safe_path


def public_snapshot(repo, sha):
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
        or ".." in repo
        or not re.fullmatch(r"[a-f0-9]{40}", sha)
    ):
        raise PolicyError("Public source requires a valid repository and exact commit SHA.")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise PolicyError("Source archive redirects are forbidden.")

    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(f"https://codeload.github.com/{repo}/tar.gz/{sha}", timeout=60) as response:
        content = response.read(50_000_001)
    if len(content) > 50_000_000:
        raise PolicyError("Repository archive exceeds 50 MB.")
    return read_archive(content)


def reconstruct(envelope, repo, sha):
    files = public_snapshot(repo, sha)
    edits = envelope.get("edits") if isinstance(envelope, dict) else None
    if not isinstance(edits, dict) or len(edits) > 100:
        raise PolicyError("Invalid source overlay.")
    for path, text in edits.items():
        safe_path(path)
        if text is None:
            files.pop(path, None)
        elif isinstance(text, str) and len(text.encode()) <= 500_000:
            files[path] = text
        else:
            raise PolicyError("Source overlay contains an invalid file.")
    return files, json.dumps(files, sort_keys=True, separators=(",", ":")).encode()


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
