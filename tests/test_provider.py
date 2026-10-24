import httpx
import pytest

from forge.config import Settings
from forge.llm import Provider, free_models
from forge.policy import PolicyError, diff_files


def test_catalog_excludes_models_with_any_price(monkeypatch):
    catalog = {
        "data": [
            {
                "id": "qwen/code:free",
                "name": "Qwen",
                "context_length": 1000,
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "deepseek/paid",
                "name": "Paid",
                "context_length": 1000,
                "pricing": {"prompt": "1", "completion": "1"},
            },
            {
                "id": "pretend/free:free",
                "name": "Not free",
                "context_length": 1000,
                "pricing": {"prompt": "0", "completion": "0", "request": "1"},
            },
        ]
    }
    monkeypatch.setattr(
        "forge.llm.httpx.get",
        lambda *args, **kwargs: httpx.Response(
            200, json=catalog, request=httpx.Request("GET", "https://fixture.test")
        ),
    )
    assert [m["id"] for m in free_models()] == ["qwen/code:free"]


def test_provider_retries_are_reserved_and_never_paid(monkeypatch):
    monkeypatch.setattr("forge.llm.free_models", lambda: [{"id": "qwen/code:free", "parameters": []}])
    monkeypatch.setattr("forge.llm.time.sleep", lambda _: None)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            calls.append(json)
            return httpx.Response(429, request=httpx.Request("POST", url))

    monkeypatch.setattr("forge.llm.httpx.Client", Client)
    config = Settings(llm_api_key="fixture", max_calls=2, max_tokens=50000, _env_file=None)
    usage = {"calls": 0, "tokens": 0}
    with pytest.raises(PolicyError, match="budget"):
        Provider(config, usage, lambda _: None, lambda: False).ask("planner", "Plan", {})
    assert usage["calls"] == 2
    assert all(c["model"] == "qwen/code:free" and c["provider"]["max_price"]["prompt"] == 0 for c in calls)


def test_downloaded_diff_handles_newline_and_new_or_deleted_files():
    diff = diff_files({"a.py": "old"}, {"a.py": "new", "b.py": "added\n"})
    assert "-old\n\\ No newline at end of file\n+new\n" in diff
    assert "--- /dev/null\n+++ b/b.py\n" in diff
    assert "+++ /dev/null\n" in diff_files({"a.py": "old\n"}, {})
