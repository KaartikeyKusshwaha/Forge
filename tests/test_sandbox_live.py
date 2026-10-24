"""Actual Docker acceptance, run explicitly on a Linux Docker host."""

import os

import pytest

from forge.github import demo_context
from forge.sandbox import DockerSandbox, demo_candidate

pytestmark = pytest.mark.skipif(
    os.environ.get("FORGE_TEST_DOCKER") != "1", reason="Explicit Linux Docker acceptance only"
)


def test_python_actual_container():
    sandbox = DockerSandbox()
    _, base = demo_context()
    before = sandbox.check(base, "baseline")
    after = sandbox.check(demo_candidate(), "candidate")
    assert before["status"] == "passed" and before["count"] == 3
    assert after["status"] == "passed" and after["count"] == 5
    assert after["image"].startswith("sha256:")


def test_node_actual_container():
    result = DockerSandbox().check(
        {
            "sum.ts": "export function sum(a: number, b: number) { return a + b; }\n",
            "sum.test.ts": "import { test } from 'node:test';\nimport assert from 'node:assert/strict';\nimport {sum} from './sum.ts';\ntest('adds', () => assert.equal(sum(2,3),5));\n",
        },
        "candidate",
        profile="typescript",
    )
    assert result["status"] == "passed" and result["count"] == 1


def test_actual_container_is_nonroot_readonly_and_offline():
    source = """import os, socket
from pathlib import Path
def test_isolation():
    assert os.getuid() == 65534
    assert not Path('/var/run/docker.sock').exists()
    assert not any(name in os.environ for name in ('GITHUB_TOKEN', 'FORGE_OWNER_TOKEN', 'OPENAI_API_KEY'))
    try:
        Path('/root-write-test').write_text('denied')
    except OSError:
        pass
    else:
        raise AssertionError('root filesystem writable')
    with socket.socket() as sock:
        sock.settimeout(1)
        assert sock.connect_ex(('1.1.1.1', 443)) != 0
"""
    result = DockerSandbox().check({"test_isolation.py": source}, "isolation")
    assert result["status"] == "passed" and result["count"] == 1
