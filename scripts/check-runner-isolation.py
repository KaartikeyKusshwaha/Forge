"""Run the real controller on a disposable CI VM with fixed acceptance fixtures."""
import base64
import gzip
import hashlib
import json
import os
import runpy
import uuid
from pathlib import Path

python_tests = '''import os, socket, resource
from pathlib import Path
def test_nonroot(): assert os.getuid() == 65534
def test_secrets_absent():
    assert not any(k in os.environ for k in ('GROQ_API_KEY','FORGE_LLM_API_KEY','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN'))
def test_offline():
    with socket.socket() as s:
        s.settimeout(1)
        assert s.connect_ex(('1.1.1.1',443)) != 0
def test_readonly_system():
    try: Path('/etc/forge-illegal-write').write_text('denied')
    except OSError: return
    raise AssertionError('System was writable')
def test_private_home(): assert not os.access('/home/runner',os.R_OK)
def test_file_size_limit(): assert resource.getrlimit(resource.RLIMIT_FSIZE)[0] <= 16*1024*1024
'''
node_tests = "import {test} from 'node:test';\nimport assert from 'node:assert/strict';\ntest('typescript executes',()=>assert.equal(2+3,5));\n"
reports = []
for profile, files, expected in [("python", {"test_isolation.py": python_tests}, 6),
                                 ("typescript", {"isolation.test.ts": node_tests}, 1)]:
    raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    os.environ.update(FORGE_REQUEST_ID=uuid.uuid4().hex, FORGE_PROFILE=profile,
        FORGE_SNAPSHOT=base64.b64encode(gzip.compress(raw)).decode(),
        FORGE_SNAPSHOT_DIGEST=hashlib.sha256(raw).hexdigest())
    runpy.run_path("scripts/actions-check.py", run_name="__main__")
    result = json.loads(Path("test-results/result.json").read_text())
    assert result["exit_code"] == 0 and result["count"] == expected, result["output"]
    reports.append({"profile": profile, **result})
Path("test-results/runner-isolation.json").write_text(json.dumps({"passed": True, "checks": reports}, indent=2))
print("PASS: real offline/non-root/read-only Python and TypeScript execution; no Docker.")
