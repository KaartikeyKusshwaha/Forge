"""Generate real local-model candidates. Execution happens separately in Docker, never on this host."""
import argparse
import json
import time
from pathlib import Path

from forge.config import Settings
from forge.index import retrieve
from forge.llm import Provider
from forge.policy import apply_edits, diff_files
from forge.worker import Changes, Plan, Review

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8788/v1")
parser.add_argument("--model", required=True)
parser.add_argument("--output", default=".forge/model-evaluation.json")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
config = Settings(llm_provider="local", llm_base_url=args.url, llm_model=args.model, llm_api_key="", _env_file=None)
report = {"model": args.model, "api_cost": 0, "validation_status": "pending_real_docker_execution", "cases": []}
for case in json.loads((root / "evaluation/cases.json").read_text()):
    start = time.monotonic()
    usage = {"calls": 0, "tokens": 0}
    provider = Provider(config, usage, lambda _: None, lambda: False)
    result = {"id": case["id"], "profile": case["profile"]}
    try:
        evidence = {"issue": case["issue"], "retrieved_files": retrieve(case["files"], case["issue"])}
        print("Planning", case["id"], flush=True)
        plan = Plan.model_validate(provider.ask("planner", "Return {summary:string,steps:string[],acceptance:string[],files:string[],needs_input:boolean}. Cite supplied file paths only.", evidence))
        print("Coding", case["id"], flush=True)
        changes = Changes.model_validate(provider.ask("coder", "Return {summary:string,edits:[{path:string,content:string}]}. content is complete new file text. Fix the issue, preserve existing behavior and add regression tests. Do not remove tests.", {**evidence, "plan": plan.model_dump(), "files": case["files"]}))
        candidate = apply_edits(case["files"], [e.model_dump() for e in changes.edits])
        print("Testing role", case["id"], flush=True)
        tests = provider.ask("tester", "Return {edits:[{path:string,content:string}]}. Only add or extend regression test files; full file text. Return edits:[] if adequate. Do not change product code.", {"issue": case["issue"], "files": candidate})
        if tests.get("edits"):
            if any("test" not in e["path"] for e in tests["edits"]):
                raise ValueError("Tester attempted a product edit")
            candidate = apply_edits(candidate, tests["edits"])
        edits = [{"path": p, "content": candidate.get(p)} for p in case["files"].keys() | candidate.keys() if case["files"].get(p) != candidate.get(p)]
        candidate = apply_edits(case["files"], edits)
        print("Reviewing", case["id"], flush=True)
        review = Review.model_validate(provider.ask("reviewer", "Return {summary:string,findings:string[],acceptable:boolean}. Inspect the diff against the issue. No checks have run yet; do not claim they passed.", {"issue": case["issue"], "patch": diff_files(case["files"], candidate)}))
        result.update(plan=plan.model_dump(), summary=changes.summary, files=candidate, review=review.model_dump(), patch=diff_files(case["files"], candidate))
    except Exception as exc:
        result["error"] = str(exc)
    result.update(usage=usage, seconds=round(time.monotonic() - start, 2))
    report["cases"].append(result)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(case["id"], "candidate generated" if "files" in result else "failed: " + result["error"], flush=True)
