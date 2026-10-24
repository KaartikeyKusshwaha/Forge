"""Execute frozen local-model outputs in isolated GitHub Actions plus evaluator-owned tests."""
import argparse
import json
from pathlib import Path

from forge.actions import ActionsSandbox
from forge.config import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", default="test-results/model-evaluation.json")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
cases = {case["id"]: case for case in json.loads((root / "evaluation/cases.json").read_text())}
generated = json.loads(Path(args.input).read_text())
report = {"model": generated["model"], "api_cost": generated["api_cost"], "execution": "isolated GitHub Actions", "cases": []}
sandbox = ActionsSandbox(Settings())
for candidate in generated["cases"]:
    case = cases[candidate["id"]]
    if candidate.get("error") or "files" not in candidate:
        report["cases"].append({"id": case["id"], "passed": False, "error": candidate.get("error", "No candidate")})
        continue
    base = sandbox.check(case["files"], "baseline", profile=case["profile"])
    reproduction = sandbox.check({**case["files"], **case["external"]}, "external_on_base", profile=case["profile"])
    after = sandbox.check({**candidate["files"], **case["external"]}, "external_on_candidate", profile=case["profile"])
    passed = base["status"] == "passed" and reproduction["status"] == "failed" and after["status"] == "passed"
    report["cases"].append({"id": case["id"], "passed": passed, "checks": [base, reproduction, after],
                            "model_usage": candidate["usage"], "generation_seconds": candidate["seconds"]})
    print(case["id"], "PASS" if passed else "FAIL", flush=True)
report["passed"] = len(report["cases"]) == len(cases) and all(r["passed"] for r in report["cases"])
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
raise SystemExit(0 if report["passed"] else 1)
