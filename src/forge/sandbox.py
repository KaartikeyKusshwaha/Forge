import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path

from forge.github import demo_context
from forge.policy import PolicyError, safe_path

DEMO_TEST = "\n    def test_zero_limit(self):\n        with self.assertRaises(ValueError):\n            validate_limit(0)\n\n    def test_inclusive_boundaries(self):\n        self.assertEqual(validate_limit(1), 1)\n        self.assertEqual(validate_limit(100), 100)\n"


def demo_candidate() -> dict:
    _, files = demo_context()
    files["pagination.py"] = files["pagination.py"].replace("limit < 0", "limit <= 0")
    files["test_pagination.py"] += DEMO_TEST
    return files


class DemoSandbox:
    """Only exact bundled fixture bytes can execute locally. Never used for GitHub or model output."""

    def check(self, files: dict, phase: str, cancelled=lambda: False) -> dict:
        _, base = demo_context()
        regression = base.copy()
        regression["test_pagination.py"] += DEMO_TEST
        if files not in (base, regression, demo_candidate()):
            raise PolicyError("Local demo execution is limited to the exact bundled fixtures.")
        if cancelled():
            raise PolicyError("Run cancelled.")
        with tempfile.TemporaryDirectory(prefix="forge-owned-demo-") as directory:
            for name, text in files.items():
                Path(directory, name).write_text(text, encoding="utf-8")
            command = [
                sys.executable,
                "-I",
                "-c",
                "import sys,unittest; sys.path.insert(0,sys.argv[1]); "
                "suite=unittest.defaultTestLoader.discover(sys.argv[1]); "
                "result=unittest.TextTestRunner(verbosity=2).run(suite); "
                "sys.exit(not result.wasSuccessful())",
                directory,
            ]
            start = time.monotonic()
            env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
            proc = subprocess.run(command, capture_output=True, text=True, timeout=15, env=env, cwd=directory)
        output = proc.stdout + proc.stderr
        match = re.search(r"Ran (\d+) tests?", output)
        count = int(match[1]) if match else 0
        return dict(
            phase=phase,
            command="python -I · bundled unittest fixture",
            exit_code=proc.returncode,
            status="passed" if proc.returncode == 0 and count else "failed",
            count=count,
            seconds=round(time.monotonic() - start, 3),
            output=output[:30_000],
            environment="Trusted bundled demo · local Python",
            image="demo-fixture-v1",
        )


class DockerSandbox:
    IMAGES = {"python": "forge-python:local", "typescript": "forge-node:local"}

    @staticmethod
    def available() -> bool:
        if not shutil.which("docker"):
            return False
        try:
            return (
                subprocess.run(
                    ["docker", "info", "--format", "{{.OSType}}"], capture_output=True, timeout=10, text=True
                ).stdout.strip()
                == "linux"
            )
        except (OSError, subprocess.TimeoutExpired):
            return False

    def check(self, files: dict, phase: str, cancelled=lambda: False, profile="python") -> dict:
        if profile not in self.IMAGES or not self.available():
            raise PolicyError(
                "A Linux Docker engine and built Forge sandbox images are required. Host execution is disabled."
            )
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            for path, text in files.items():
                safe_path(path)
                content = text.encode()
                member = tarfile.TarInfo(path)
                member.size, member.mode = len(content), 0o600
                archive.addfile(member, io.BytesIO(content))
        name = "forge-" + uuid.uuid4().hex
        image = self.IMAGES[profile]
        inspect = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if inspect.returncode:
            raise PolicyError(f"Build the {image} sandbox image before running checks.")
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "-i",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--pids-limit",
            "128",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--ulimit",
            "fsize=131072:131072",
            "--tmpfs",
            "/workspace:rw,nosuid,nodev,size=64m,mode=1777",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=32m,mode=1777",
            "--workdir",
            "/workspace",
            image,
        ]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output, overflow = bytearray(), threading.Event()

        def read():
            while chunk := proc.stdout.read(4096):
                if len(output) + len(chunk) > 256_000:
                    overflow.set()
                    continue
                output.extend(chunk)

        def write():
            try:
                proc.stdin.write(data.getvalue())
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        reader, writer = (
            threading.Thread(target=read, daemon=True),
            threading.Thread(target=write, daemon=True),
        )
        reader.start()
        writer.start()
        start = time.monotonic()
        stopped = ""
        try:
            while proc.poll() is None:
                if cancelled() or time.monotonic() - start > 180 or overflow.is_set():
                    stopped = "cancelled" if cancelled() else "resource limit"
                    subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)
                    proc.kill()
                    break
                time.sleep(0.2)
            proc.wait(timeout=10)
            reader.join(timeout=3)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
        if stopped:
            raise PolicyError(f"Sandbox stopped: {stopped}.")
        try:
            result = json.loads(output.decode())
            if not isinstance(result["count"], int) or result["count"] < 0:
                raise ValueError
        except (ValueError, KeyError, UnicodeDecodeError):
            raise PolicyError(
                "Sandbox did not return a valid check report. Check the image and dependencies."
            ) from None
        result.update(
            phase=phase,
            image=inspect.stdout.strip(),
            environment="Docker · no network · non-root",
            seconds=round(time.monotonic() - start, 3),
        )
        result["status"] = "passed" if result["exit_code"] == 0 and result["count"] > 0 else "failed"
        return result
