"""Pinned llama.cpp runtime, independent of any other project on this machine."""
import hashlib
import json
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".forge" / "models"
RUNTIMES = {
    "Windows": ("llama-b11857-bin-win-vulkan-x64.zip", "6d90c98f2eaa19389f426f5b1daa8721226ed7e4a491d181bc0efa13eda6c453"),
    "Linux": ("llama-b11857-bin-ubuntu-x64.tar.gz", "d2f82dbe8fa95738cccfc9e8b14d1186d85d56cd1d19acdebb4ddf24b0a0453e"),
}
name, expected = RUNTIMES[platform.system()]
ROOT.mkdir(parents=True, exist_ok=True)
target = ROOT / name
url = "https://github.com/ggml-org/llama.cpp/releases/download/b11857/" + name
if not target.exists():
    print("Downloading pinned llama.cpp runtime…", flush=True)
    urllib.request.urlretrieve(url, target)
with target.open("rb") as stream:
    actual = hashlib.file_digest(stream, "sha256").hexdigest()
if actual != expected:
    raise SystemExit("Runtime checksum mismatch. Archive was not executed or extracted.")
runtime = ROOT / "runtime"
runtime.mkdir(exist_ok=True)
if name.endswith(".zip"):
    with zipfile.ZipFile(target) as archive:
        for entry in archive.infolist():
            path = (runtime / entry.filename).resolve()
            if not path.is_relative_to(runtime.resolve()):
                raise SystemExit("Unsafe runtime archive path")
        archive.extractall(runtime)
else:
    with tarfile.open(target) as archive:
        archive.extractall(runtime, filter="data")
(ROOT / "runtime-provenance.json").write_text(json.dumps({"source": url, "sha256": actual, "license": "MIT"}, indent=2))
print("Verified runtime extracted to", runtime)
