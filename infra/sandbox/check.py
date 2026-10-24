"""Fixed sandbox entry point. This file lives in the image, outside the writable workspace."""
import glob
import json
import os
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

profile = os.environ.get("FORGE_PROFILE", "python")
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
    total = 0
    for member in archive:
        total += member.size
        parts = member.name.split("/")
        if (not member.isfile() or member.name.startswith("/") or ".." in parts
                or "\\" in member.name or total > 50_000_000):
            raise SystemExit("Unsafe archive")
        os.makedirs(os.path.dirname(member.name) or ".", exist_ok=True)
        with open(member.name, "wb") as out:
            out.write(archive.extractfile(member).read())

if profile == "python":
    command = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=/tmp/results.xml"]
else:
    files = sorted(glob.glob("**/*.test.ts", recursive=True) + glob.glob("**/*.test.js", recursive=True))
    command = ["node", "--experimental-strip-types", "--test", *files]
    if not files:
        print(json.dumps(dict(command="node --test", count=0, exit_code=1, output="No supported test files.")))
        raise SystemExit(0)

with open("/tmp/check-output", "wb") as log:
    try:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=165)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
with open("/tmp/check-output", "rb") as log:
    output = log.read(60_000).decode("utf-8", errors="replace")
count = 0
if profile == "python":
    try:
        root = ET.parse("/tmp/results.xml").getroot()
        suites = list(root.iter("testsuite"))
        count = sum(int(s.get("tests", 0)) - int(s.get("skipped", 0)) for s in suites)
    except (OSError, ET.ParseError):
        pass
else:
    matches = re.findall(r"# tests (\d+)", output)
    count = int(matches[-1]) if matches else 0
print(json.dumps(dict(command=" ".join(command), count=count, exit_code=exit_code, output=output)))
