"""Run the real controller on a disposable CI VM with fixed acceptance fixtures."""
import base64
import gzip
import hashlib
import json
import os
import runpy
import uuid
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

python_tests = '''import os, socket, resource
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
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
project_files = {
    "pyproject.toml": '[build-system]\nrequires=["setuptools", "wheel"]\nbuild-backend="setuptools.build_meta"\n',
    "setup.py": "import os,socket\nfrom setuptools import setup\nassert os.getuid()==65534\nassert not os.access('/home/runner',os.R_OK)\nassert not any(k in os.environ for k in ('GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN'))\ns=socket.socket();s.settimeout(1);assert s.connect_ex(('1.1.1.1',443))!=0;s.close()\nsetup(name='forge-sandbox-fixture',version='1.0',py_modules=['fixture_package'])\n",
    "requirements.txt": "packaging>=24\n",
    "fixture_package.py": "VALUE = 42\n",
    "test_package.py": "import fixture_package,packaging\ndef test_installed_package(): assert fixture_package.VALUE == 42\n",
}
reports = []
for profile, files, expected in [("python", {"test_isolation.py": python_tests}, 6),
                                 ("python", project_files, 1),
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
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forge.snapshot import public_snapshot

source_repo = "KaartikeyKusshwaha/Forge-Acceptance"
source_sha = "683ff962c5a8d27f9ab8d3c85ba71e012b8797ce"
files = public_snapshot(source_repo, source_sha)
edits = {"test_transport.py": "import os\ndef test_remote_overlay(): assert os.getuid() == 65534\n"}
files.update(edits)
raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
envelope = json.dumps({"edits": edits}).encode()
os.environ.update(FORGE_REQUEST_ID=uuid.uuid4().hex, FORGE_PROFILE="python",
    FORGE_SNAPSHOT=base64.b64encode(gzip.compress(envelope)).decode(),
    FORGE_SNAPSHOT_DIGEST=hashlib.sha256(raw).hexdigest(),
    FORGE_SOURCE_REPO=source_repo, FORGE_SOURCE_SHA=source_sha)
runpy.run_path("scripts/actions-check.py", run_name="__main__")
result = json.loads(Path("test-results/result.json").read_text())
assert result["exit_code"] == 0 and result["count"] >= 3, result["output"]
Path("test-results/source-transport.json").write_text(json.dumps(result, indent=2))
print("PASS: real offline/non-root/read-only Python and TypeScript execution; no Docker.")
