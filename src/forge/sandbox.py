import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from forge.github import demo_context
from forge.policy import PolicyError

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
