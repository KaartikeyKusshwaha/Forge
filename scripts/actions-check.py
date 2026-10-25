"""Trusted controller on a disposable GitHub VM; target code runs under a different UID and systemd."""
import base64
import glob
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

request_id = os.environ.pop("FORGE_REQUEST_ID")
profile = os.environ.pop("FORGE_PROFILE")
packed = os.environ.pop("FORGE_SNAPSHOT")
digest = os.environ.pop("FORGE_SNAPSHOT_DIGEST")
source_repo = os.environ.pop("FORGE_SOURCE_REPO", "")
source_sha = os.environ.pop("FORGE_SOURCE_SHA", "")
if not re.fullmatch(r"[a-f0-9]{32}", request_id) or profile not in {"python", "typescript"}:
    raise SystemExit("Invalid check request")
if len(packed) > 58_000 or not re.fullmatch(r"[a-f0-9]{64}", digest):
    raise SystemExit("Invalid snapshot envelope")
with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(packed, validate=True))) as stream:
    raw = stream.read(50_000_001)
if len(raw) > 50_000_000:
    raise SystemExit("Source envelope exceeds size limit")
if source_repo or source_sha:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from forge.snapshot import reconstruct

    files, raw = reconstruct(json.loads(raw), source_repo, source_sha)
if len(raw) > 50_000_000 or hashlib.sha256(raw).hexdigest() != digest:
    raise SystemExit("Snapshot digest or size mismatch")
files = json.loads(raw)
if not isinstance(files, dict) or len(files) > 10_000:
    raise SystemExit("Invalid source inventory")

with tempfile.TemporaryDirectory(prefix="forge-isolated-", dir="/tmp") as directory:
    work = Path(directory)
    work.chmod(0o777)
    for path, text in files.items():
        if (not isinstance(path, str) or not isinstance(text, str) or path.startswith("/") or "\\" in path
                or any(p in {"", ".", "..", ".git"} for p in path.split("/"))
                or any(ord(c) < 32 for c in path) or len(text.encode()) > 500_000):
            raise SystemExit("Unsafe source path or content")
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        target.chmod(0o666)
    for parent in work.rglob("*"):
        if parent.is_dir():
            parent.chmod(0o777)
    # A root-owned, read-only systemd service enforces the execution boundary.
    # The target never receives Actions credentials, model keys, or source-control credentials.
    if profile == "python":
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=results.xml"]
    else:
        tests = sorted(str(p.relative_to(work)) for p in work.rglob("*") if p.name.endswith((".test.ts", ".test.js")))
        command = [shutil.which("node"), "--experimental-strip-types", "--test", *tests]
        if not tests:
            command = [shutil.which("node"), "-e", "console.error('No supported tests');process.exit(1)"]
    service = ["sudo", "systemd-run", "--quiet", "--wait", "--pipe", "--collect", "--unit=forge-" + request_id,
        "--property=User=nobody", "--property=Group=nogroup", "--property=PrivateNetwork=yes",
        "--property=ProtectSystem=strict", "--property=ProtectHome=yes", "--property=PrivateDevices=yes",
        "--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=", "--property=RestrictSUIDSGID=yes",
        "--property=MemoryMax=512M", "--property=TasksMax=128", "--property=CPUQuota=100%",
        "--property=RuntimeMaxSec=180", "--property=LimitFSIZE=16M", "--property=WorkingDirectory=" + directory,
        "--property=ReadWritePaths=" + directory, "--property=InaccessiblePaths=/home /root /run/docker.sock",
        "--setenv=PYTHONDONTWRITEBYTECODE=1", "--setenv=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "--", *command]
    try:
        with tempfile.TemporaryFile() as log:
            proc = subprocess.run(service, stdout=log, stderr=subprocess.STDOUT, timeout=200)
            log.seek(0)
            output = log.read(60_000).decode("utf-8", errors="replace")
        code = proc.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["sudo", "systemctl", "kill", "forge-" + request_id], capture_output=True)
        code, output = 124, "Execution time limit exceeded."
    count = 0
    if profile == "python":
        try:
            root = ET.parse(work / "results.xml").getroot()
            count = sum(int(s.get("tests", 0)) - int(s.get("skipped", 0)) for s in root.iter("testsuite"))
        except (OSError, ET.ParseError, ValueError):
            pass
    else:
        matches = re.findall(r"# tests (\d+)", output)
        count = int(matches[-1]) if matches else 0
    result = {"request_id": request_id, "snapshot_digest": digest, "command": " ".join(command),
              "exit_code": code, "count": count, "output": output}
Path("test-results").mkdir(exist_ok=True)
Path("test-results/result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "output"}))
