import threading
import time
import uuid

from forge.actions import ActionsSandbox
from forge.config import Settings
from forge.contracts import Changes, Edit, Plan, Review
from forge.github import GitHub, GitHubError, demo_context
from forge.index import retrieve
from forge.llm import Provider, verify_free
from forge.policy import PolicyError, apply_edits, seal_candidate
from forge.sandbox import DemoSandbox, demo_candidate
from forge.store import Conflict, Store


class Worker:
    def __init__(self, config: Settings, store: Store):
        self.config, self.store = config, store
        self.owner = uuid.uuid4().hex

    def run_once(self) -> bool:
        from forge.models import ModelVault

        ModelVault(self.config).load_active()
        self.store.recover()
        run = self.store.claim(self.owner)
        if not run:
            return False
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(15):
                self.store.heartbeat(run["id"], self.owner)

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            if run["status"] == "publishing":
                self.publish(run)
            else:
                self.execute(run)
        except Conflict:
            pass  # A lost lease never grants another write.
        except Exception as exc:
            if isinstance(exc, (PolicyError, GitHubError)):
                error = str(exc)
            else:
                error = f"{type(exc).__name__}: run stopped safely. Inspect the local server diagnostics."
            current = self.store.get(run["id"])
            status = (
                "cancelled"
                if current["cancel"]
                else "needs_input"
                if current.get("plan", {}).get("needs_input")
                else "failed"
            )
            if "base branch moved" in error:
                status = "stale"
            try:
                self.store.mutate(
                    run["id"],
                    lambda r, d: (
                        d.update(error=error) or {"status": status, "lease_until": 0, "lease_owner": ""}
                    ),
                    status,
                    error,
                    owner=self.owner,
                )
            except Conflict:
                pass
        finally:
            stop.set()
            thread.join(timeout=1)
        return True

    def execute(self, run: dict):
        run_id, mode = run["id"], run["mode"]
        started = time.monotonic()

        def cancelled():
            if time.monotonic() - started > self.config.max_run_seconds:
                raise PolicyError("Whole-run time budget exceeded.")
            return self.store.get(run_id)["cancel"]

        def stage(status, message, **values):
            if cancelled():
                raise PolicyError("Run cancelled.")
            self.store.mutate(
                run_id, lambda r, d: d.update(values) or {"status": status}, status, message, owner=self.owner
            )

        def save(**values):
            self.store.mutate(run_id, lambda r, d: d.update(values), owner=self.owner)

        stage("snapshotting", "Freezing the issue and repository revision.")
        github = GitHub(self.config)
        if mode == "demo":
            context, files = demo_context()
            sandbox = DemoSandbox()
            model = "Scripted demo roles · no model calls"
        else:
            if not self.config.llm_ready:
                raise PolicyError(
                    "Connect a verified model profile in Connection settings before starting a real run."
                )
            if not ActionsSandbox.available():
                raise PolicyError(
                    "GitHub Actions runner is unavailable. No repository code will run on the host."
                )
            context = (
                github.context(run["repo"], run["issue"], run.get("request", ""))
                if run.get("request")
                else github.context(run["repo"], run["issue"])
            )
            files = github.snapshot(context)
            sandbox = ActionsSandbox(self.config)
            if hasattr(sandbox, "set_source"):
                sandbox.set_source(context, files)
            model = verify_free(self.config)["id"]
        if run.get("feedback"):
            context["owner_feedback"] = run["feedback"]
        context["repository_guidelines"] = {
            p: text[:12000]
            for p, text in files.items()
            if p.lower() in {"agents.md", "contributing.md", ".github/contributing.md"}
        }
        if run.get("previous_request"):
            context["previous_owner_feedback"] = run["previous_request"]
        if run.get("previous_publication"):
            context["previous_publication"] = run["previous_publication"]
            context["follow_up_policy"] = (
                "This is a new proposal on the current upstream base. Do not assume an unmerged previous PR is present. Explain dependencies on prior changes to the owner."
            )
        from forge.environment import environment_plan

        save(context=context, title=context["title"], model=model, environment_plan=environment_plan(files))
        profile = (
            "typescript"
            if any(p.endswith((".ts", ".js")) for p in files) and not any(p.endswith(".py") for p in files)
            else "python"
        )
        if run.get("requested_profile") in {"python", "typescript"}:
            profile = run["requested_profile"]
        elif "typescript" in (context["title"] + " " + context["body"]).lower():
            profile = "typescript"
        if mode != "demo" and (
            "package.json" in files or "pyproject.toml" in files or "requirements.txt" in files
        ):
            save(
                limitations=[
                    "Checks install declared Python dependencies and the project in an isolated disposable GitHub runner, then run tests offline."
                ]
            )
        stage("indexing", "Finding implementation files, symbols, and nearby tests.")
        shortlist = retrieve(files, context["title"] + " " + context["body"])
        save(
            index={
                "file_count": len(files),
                "files": [{k: v for k, v in f.items() if k != "content"} for f in shortlist],
            },
            profile=profile,
        )

        def check(source, phase):
            if mode == "demo":
                return sandbox.check(source, phase, cancelled)
            return sandbox.check(source, phase, cancelled, profile=profile)

        stage("baseline", "Running existing checks against the unchanged base.")
        baseline = check(files, "baseline")
        checks = [baseline]
        save(checks=checks)
        if baseline.get("exit_code") == 2:
            raise PolicyError(
                "Baseline setup or test collection failed. Review the sandbox setup and import errors in Checks. No model-driven edits were attempted."
            )
        if baseline["count"] == 0:
            raise PolicyError(
                "Baseline collected no tests. Configure a supported test profile before asking Forge to edit."
            )
        usage = {
            "calls": 0,
            "tokens": 0,
            "cost": 0,
            "run_id": run_id,
            "pricing": "Free-only model access"
            if self.config.model_usage_mode == "free_only"
            else "Owner-authorized profile spending policy",
        }
        provider_config = (
            self.config.model_copy(update={"llm_model": model}) if mode != "demo" else self.config
        )
        provider = Provider(provider_config, usage, lambda u: save(usage=u), cancelled)
        evidence = {
            "available_paths": sorted({f["path"] for f in shortlist}),
            "issue": context,
            "retrieved_files": shortlist,
        }
        stage("planning", "Planner is defining a focused change and acceptance checks.")
        if mode == "demo":
            plan = Plan(
                summary="Reject zero at the existing validation boundary and prove both inclusive limits still work.",
                steps=[
                    "Locate page-size validation and its existing tests.",
                    "Change the lower-bound comparison to include zero.",
                    "Add a regression test plus boundary coverage.",
                    "Run checks and review the focused diff.",
                ],
                acceptance=[
                    "Zero raises ValueError.",
                    "Values 1 and 100 remain valid.",
                    "Existing tests still pass.",
                ],
                files=["pagination.py", "test_pagination.py"],
            )
        else:
            plan = Plan.model_validate(
                provider.ask(
                    "planner",
                    "Return {summary, steps: string[], acceptance: string[], files: string[], needs_input: boolean, question: string}. Cite only supplied paths. Set needs_input=true ONLY if implementation is blocked by a specific missing requirement or protected edit; state the exact question. Routine human approval before publication and the absence of future test results do not block coding. If the issue is clear, needs_input=false and question=''. A separate runner will execute tests.",
                    evidence,
                )
            )
            if plan.needs_input and not plan.question.strip():
                plan = Plan.model_validate(
                    provider.ask(
                        "planner",
                        "Your earlier plan marked needs_input but identified no question. Return the same full schema with a concrete question ONLY if implementation is actually blocked. Approval before publication is already enforced and is not missing information. Otherwise needs_input=false and question=''.",
                        {**evidence, "previous_plan": plan.model_dump()},
                    )
                )
            if any(path not in files for path in plan.files):
                raise PolicyError("Planner cited a file absent from the pinned repository.")
        save(plan=plan.model_dump())
        if plan.needs_input:
            raise PolicyError(
                "Planner needs input: "
                + (plan.question or "A clearer issue or a change outside the protected scope is required.")
            )
        stage("coding", "Coder is preparing a minimal candidate; no commits are created.")
        if mode == "demo":
            after = demo_candidate()
            summary = "Reject page size zero and add regression and inclusive-boundary tests."
        else:
            changes = Changes.model_validate(
                provider.ask(
                    "coder",
                    "Return {summary, edits:[{path, content}]}. content is the COMPLETE new file text, or null for deletion. Preserve unrelated code. Add a regression test.",
                    {
                        **evidence,
                        "plan": plan.model_dump(),
                        "selected_files": {p: files[p] for p in plan.files[:12]},
                    },
                )
            )
            after = apply_edits(files, [e.model_dump() for e in changes.edits])
            summary = changes.summary
            stage("testing", "Tester is examining regression coverage before execution.")
            tests = provider.ask(
                "tester",
                "Return {edits:[{path, content}]}. Suggest only new or extended regression test files. Return an empty edits array when coverage is adequate. Never change product code or remove existing test cases.",
                {
                    "issue": context,
                    "plan": plan.model_dump(),
                    "changed_files": {p: v for p, v in after.items() if files.get(p) != v},
                },
            )
            if tests.get("edits"):
                test_edits = [Edit.model_validate(e).model_dump() for e in tests["edits"]]
                for edit in test_edits:
                    if "test" not in edit["path"].lower() or edit["content"] is None:
                        raise PolicyError("Tester attempted to modify a non-test file or delete a test.")
                after = apply_edits(after, test_edits)
        # Recheck the entire aggregate change (not merely each role's incremental output).
        aggregate = [
            {"path": p, "content": after.get(p)}
            for p in sorted(files.keys() | after.keys())
            if files.get(p) != after.get(p)
        ]
        after = apply_edits(files, aggregate)
        save(summary=summary)
        stage("validating", "Running the new regression checks on the base, then the candidate.")
        regression_base = files.copy()
        for path, text in after.items():
            if "test" in path.lower() and files.get(path) != text:
                regression_base[path] = text
        if regression_base != files:
            checks.append(check(regression_base, "regression_on_base"))
        review = None
        for attempt in range(3):
            result = check(after, "candidate" if attempt == 0 else f"repair_{attempt}")
            checks.append(result)
            save(checks=checks, repairs=attempt)
            stage("reviewing", "Reviewer is checking the diff against the issue and actual runner results.")
            if mode == "demo":
                review = Review(
                    summary="Focused lower-bound fix. Zero is rejected; inclusive bounds and existing behavior are covered.",
                    findings=[],
                    acceptable=result["status"] == "passed",
                )
            else:
                review = Review.model_validate(
                    provider.ask(
                        "reviewer",
                        "Return {summary, findings: string[], acceptable: boolean}. Inspect for requirement gaps, weakened tests, unrelated edits and security concerns. You cannot approve publication.",
                        {
                            "issue": context,
                            "plan": plan.model_dump(),
                            "changes": aggregate,
                            "checks": [{**c, "output": c["output"][:8000]} for c in checks],
                        },
                    )
                )
            save(review=review.model_dump())
            save(
                candidate=seal_candidate(
                    context["base_sha"], files, after, checks, review.model_dump(), profile
                )
            )
            if result["status"] == "passed" and review.acceptable:
                break
            if attempt == 2 or mode == "demo":
                raise PolicyError(
                    "Candidate did not pass required checks and review within the repair limit."
                )
            stage("repairing", f"Repair attempt {attempt + 1} of 2.")
            repair = Changes.model_validate(
                provider.ask(
                    "coder",
                    "Repair this candidate. Return {summary, edits:[{path,content}]}, complete file text. Address the check failures and reviewer findings without weakening tests.",
                    {
                        "issue": context,
                        "candidate": {p: after[p] for p in plan.files if p in after},
                        "result": result,
                        "review": review.model_dump(),
                    },
                )
            )
            after = apply_edits(after, [e.model_dump() for e in repair.edits])
            aggregate = [
                {"path": p, "content": after.get(p)}
                for p in sorted(files.keys() | after.keys())
                if files.get(p) != after.get(p)
            ]
            after = apply_edits(files, aggregate)
            stage("validating", "Re-running the repaired candidate in a fresh sandbox.")
        candidate = seal_candidate(context["base_sha"], files, after, checks, review.model_dump(), profile)
        save(candidate=candidate, usage=usage, ready_at=time.time())
        stage(
            "awaiting_approval",
            "Candidate ready. Human approval is required before any commit, push, or draft PR.",
        )
        self.store.mutate(run_id, lambda r, d: {"lease_owner": "", "lease_until": 0}, owner=self.owner)

    def publish(self, run: dict):
        if run["cancel"]:
            raise PolicyError("Publication was cancelled before starting.")
        if run["mode"] == "demo":
            self.store.mutate(
                run["id"],
                lambda r, d: {"status": "demo_complete", "lease_until": 0, "lease_owner": ""},
                "demo_complete",
                "Demo approval recorded. No GitHub commit, branch, or PR was created.",
                owner=self.owner,
            )
            return
        if not self.config.publish_enabled:
            raise PolicyError(
                "GitHub publishing is disabled. Review the target CI policy before enabling it."
            )

        def persist(publication):
            self.store.mutate(run["id"], lambda r, d: d.update(publication=publication), owner=self.owner)

        result = GitHub(self.config).publish(run, persist)
        self.store.mutate(
            run["id"],
            lambda r, d: (
                d.update(publication=result) or {"status": "pr_opened", "lease_until": 0, "lease_owner": ""}
            ),
            "pr_opened",
            "The approved candidate was published as a draft pull request.",
            owner=self.owner,
        )


def serve_worker(config: Settings, store: Store, stop: threading.Event | None = None):
    stop = stop or threading.Event()
    worker = Worker(config, store)
    while not stop.is_set():
        if not worker.run_once():
            stop.wait(config.worker_poll_seconds)
