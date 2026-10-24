"""Download an official, pinned Apache-2.0 coding model. No account or paid API."""
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".forge" / "models"
NAME = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
REVISION = "13fb94bfda8c8cf22497dc57b78f391a9acb426a"
SHA256 = "509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c"
SIZE = 4683073536
URL = f"https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/{REVISION}/{NAME}"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / NAME
    if target.exists():
        if target.stat().st_size != SIZE or digest(target) != SHA256:
            raise SystemExit("Existing model does not match the pinned digest. It was left untouched.")
    else:
        temp = target.with_suffix(".partial")
        start = time.monotonic()
        with urllib.request.urlopen(URL, timeout=60) as response, temp.open("wb") as out:
            total, last = 0, 0
            while chunk := response.read(4 * 1024 * 1024):
                out.write(chunk)
                total += len(chunk)
                if total > SIZE:
                    raise SystemExit("Download exceeded expected model size.")
                if time.monotonic() - last > 15:
                    print(f"Model download: {total / SIZE:.1%} · {total // 1_000_000} MB", flush=True)
                    last = time.monotonic()
        if temp.stat().st_size != SIZE or digest(temp) != SHA256:
            raise SystemExit("Download failed digest verification. Partial file retained for diagnosis.")
        os.replace(temp, target)
        print(f"Verified in {time.monotonic() - start:.1f}s", flush=True)
    provenance = dict(model="Qwen2.5-Coder-7B-Instruct", quantization="Q4_K_M", revision=REVISION,
                      sha256=SHA256, size=SIZE, source=URL, license="Apache-2.0")
    (ROOT / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print("Verified local coding model:", target)
