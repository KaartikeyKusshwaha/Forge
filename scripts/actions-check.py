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

from sandbox_dependencies import python_requirements
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
    def isolated(command, stage, writable, limit="16M", offline=True):
        scratch = Path(tempfile.mkdtemp(prefix="forge-scratch-", dir="/tmp"))
        writable = [*writable, scratch]
        scratch.chmod(0o777)
        service = ["sudo", "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
            "--unit=forge-" + request_id + "-" + stage,
            "--property=User=nobody", "--property=Group=nogroup", "--property=PrivateNetwork=" + ("yes" if offline else "no"),
            "--property=ProtectSystem=strict", "--property=ProtectHome=yes", "--property=PrivateDevices=yes",
            "--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=", "--property=RestrictSUIDSGID=yes",
            "--property=MemoryMax=1G", "--property=TasksMax=128", "--property=CPUQuota=100%",
            "--property=RuntimeMaxSec=240", "--property=LimitFSIZE=" + limit,
            "--property=WorkingDirectory=" + directory,
            "--property=ReadWritePaths=" + " ".join(map(str, writable)),
            "--property=InaccessiblePaths=/home /root /run/docker.sock",
            "--setenv=HOME=/nonexistent", "--setenv=TMPDIR=" + str(scratch), "--setenv=PYTHONDONTWRITEBYTECODE=1",
            "--setenv=PIP_CONFIG_FILE=/dev/null", *(["--setenv=PIP_NO_INDEX=1"] if offline else []), "--", *command]
        try:
            with tempfile.TemporaryFile() as log:
                proc = subprocess.run(service, stdout=log, stderr=subprocess.STDOUT, timeout=260)
                log.seek(0)
                return proc.returncode, log.read(60_000).decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            subprocess.run(["sudo", "systemctl", "kill", "forge-" + request_id + "-" + stage], capture_output=True)
            return 124, "Execution time limit exceeded."

    setup = {"status": "not-required", "output": "", "requirements": [], "wheels": []}
    environment = Path(tempfile.mkdtemp(prefix="forge-venv-", dir="/tmp"))
    wheels = Path(tempfile.mkdtemp(prefix="forge-wheels-", dir="/tmp"))
    environment.chmod(0o755)
    wheels.chmod(0o755)
    # Only static package specifications reach the networked wheel downloader.
    # No project code or source builds run in the controller process.
    if profile == "python":
        try:
            requirements, install_project = python_requirements(files)
            setup["requirements"] = requirements
            clean_env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "SSL_CERT_FILE") if k in os.environ}
            subprocess.run(["sudo", "chown", "nobody:nogroup", str(wheels)], check=True)
            code, output = isolated([sys.executable, "-m", "pip", "--isolated", "download",
                "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--dest", str(wheels),
                "--no-cache-dir", "--disable-pip-version-check", *requirements],
                "download", [wheels], "128M", offline=False)
            setup["output"] = output
            if code:
                raise ValueError("Dependency wheel resolution failed; see setup output. Source-only packages need a reviewed setup profile.")
            setup["wheels"] = [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                               for p in sorted(wheels.glob("*.whl"))]
            subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, env=clean_env)
            subprocess.run(["sudo", "chown", "-R", "nobody:nogroup", str(environment)], check=True)
            python = str(environment / "bin/python")
            code, output = isolated([python, "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
                "--no-cache-dir", *map(str, sorted(wheels.glob("*.whl")))], "dependencies", [environment], "128M")
            setup["output"] += "\n" + output
            if code:
                raise ValueError("Offline dependency installation failed.")
            if install_project:
                code, output = isolated([python, "-m", "pip", "--isolated", "install", "--no-index",
                    "--no-deps", "--no-build-isolation", "--no-cache-dir", "."], "project", [work, environment], "128M")
                setup["output"] += "\n" + output
                if code:
                    raise ValueError("Offline project installation failed.")
            setup["status"] = "ready"
        except (ValueError, subprocess.SubprocessError) as exc:
            setup["status"] = "failed"
            setup["output"] += "\n" + str(exc)
    if profile == "typescript" and "package.json" in files:
        try:
            manifest = json.loads(files["package.json"])
            if manifest.get("dependencies") or manifest.get("devDependencies"):
                if "package-lock.json" not in files:
                    raise ValueError("Node dependency setup requires package-lock.json. Generate and commit a lockfile before running Forge.")
                # No lifecycle hooks run during networked dependency retrieval.
                # npm test and build hooks execute only in the offline test stage.
                code, output = isolated([shutil.which("npm"), "ci", "--ignore-scripts", "--no-audit",
                    "--no-fund", "--cache", str(work / ".npm-cache"), "--userconfig=/dev/null"],
                    "node-dependencies", [work], "128M", offline=False)
                setup["output"] = output
                if code:
                    raise ValueError("Locked Node dependency installation failed.")
                setup["status"] = "ready"
        except (ValueError, subprocess.SubprocessError) as exc:
            setup["status"] = "failed"
            setup["output"] += "\n" + str(exc)
    # A root-owned, read-only systemd service enforces the execution boundary.
    # The target never receives Actions credentials, model keys, or source-control credentials.
    if profile == "python":
        command = [str(environment / "bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=results.xml"]
    else:
        tests = sorted(str(p.relative_to(work)) for p in work.rglob("*") if p.name.endswith((".test.ts", ".test.js")))
        command = [shutil.which("node"), "--experimental-strip-types", "--test", *tests]
        if "package.json" in files and json.loads(files["package.json"]).get("scripts", {}).get("test"):
            command = [shutil.which("npm"), "test"]
        elif not tests:
            command = [shutil.which("node"), "-e", "console.error('No supported tests');process.exit(1)"]
    if setup["status"] == "failed":
        code, output = 2, "Sandbox dependency setup failed.\n" + setup["output"]
    else:
        code, output = isolated(command, "tests", [work])
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
              "exit_code": code, "count": count, "output": output, "setup": setup}
    shutil.rmtree(environment, ignore_errors=True)
    shutil.rmtree(wheels, ignore_errors=True)
Path("test-results").mkdir(exist_ok=True)
Path("test-results/result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k not in {"output", "setup"}}))
