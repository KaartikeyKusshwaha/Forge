from conftest import create_demo

from forge.github import demo_context
from forge.sandbox import DEMO_TEST, DemoSandbox, demo_candidate
from forge.worker import Worker


def simulated_live_loop(monkeypatch, config, *, persistent_failure=False):
    """Simulate remote transports; execute only known, exact bundled fixture code."""
    ctx, base = demo_context()

    class GithubFixture:
        def __init__(self, *_):
            pass

        def context(self, *_):
            return ctx.copy()

        def snapshot(self, *_):
            return base.copy()

    class SandboxFixture:
        @staticmethod
        def available():
            return True

        def __init__(self, *_):
            pass

        def check(self, files, phase, cancelled, profile):
            return DemoSandbox().check(files, phase, cancelled)

    class ProviderFixture:
        def __init__(self, *_):
            self.coder_calls = 0

        def ask(self, role, instructions, context):
            if role == "planner":
                return {
                    "summary": "Fix the lower bound",
                    "steps": ["Fix and test"],
                    "acceptance": ["Reject zero"],
                    "files": ["pagination.py", "test_pagination.py"],
                }
            if role == "tester":
                return {"edits": []}
            if role == "reviewer":
                passed = context["checks"][-1]["status"] == "passed"
                return {
                    "summary": "Check recorded test output",
                    "findings": [] if passed else ["Zero is accepted"],
                    "acceptable": passed,
                }
            assert role == "coder"
            self.coder_calls += 1
            if self.coder_calls == 1 or persistent_failure:
                return {
                    "summary": "Add regression coverage",
                    "edits": [
                        {"path": "test_pagination.py", "content": base["test_pagination.py"] + DEMO_TEST}
                    ],
                }
            return {
                "summary": "Fix the bound",
                "edits": [{"path": "pagination.py", "content": demo_candidate()["pagination.py"]}],
            }

    monkeypatch.setattr("forge.worker.GitHub", GithubFixture)
    monkeypatch.setattr("forge.worker.ActionsSandbox", SandboxFixture)
    monkeypatch.setattr("forge.worker.Provider", ProviderFixture)
    monkeypatch.setattr("forge.worker.verify_free", lambda _: {"id": "fixture/model:free"})
    config.llm_api_key = "fixture-not-a-real-key"


def test_first_candidate_failure_repairs_within_limit(setup, monkeypatch):
    config, store, client = setup
    run = create_demo(client)
    store.mutate(run["id"], lambda r, d: d.update(mode="github"))
    simulated_live_loop(monkeypatch, config)
    Worker(config, store).run_once()
    result = store.get(run["id"])
    assert result["status"] == "awaiting_approval", result.get("error")
    assert result["repairs"] == 1
    assert result["checks"][-2]["status"] == "failed"
    assert result["checks"][-1]["status"] == "passed"
    assert "approval" not in result


def test_persistent_failure_stops_after_two_repairs_and_keeps_diff(setup, monkeypatch):
    config, store, client = setup
    run = create_demo(client)
    store.mutate(run["id"], lambda r, d: d.update(mode="github"))
    simulated_live_loop(monkeypatch, config, persistent_failure=True)
    Worker(config, store).run_once()
    result = store.get(run["id"])
    assert result["status"] == "failed"
    # Second identical no-op repair may stop earlier under edit policy; neither path loops forever.
    assert result["repairs"] <= 2
    assert result["candidate"]["patch"]
    assert "approval" not in result and "publication" not in result
