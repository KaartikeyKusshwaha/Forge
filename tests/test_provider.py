import httpx
import pytest

from forge.config import Settings
from forge.llm import Provider, free_models, rejection_message
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


def test_harness_access_restriction_is_explained_without_blame_on_key():
    config = Settings(llm_model="thinkingmachines/inkling:free", _env_file=None)
    response = httpx.Response(403, json={"error": {"message": "Only available on agentic harnesses"}})
    message = rejection_message(response, config)
    assert "approved agent" in message and "key can be valid" in message
    assert "free model" in message and "HTTP 403" in message


def test_provider_error_details_are_bounded_and_credentials_are_redacted():
    config = Settings(llm_api_key="fixture-private-key", owner_token="fixture-owner-token", _env_file=None)
    response = httpx.Response(403, json={"error": {"message": config.llm_api_key + config.owner_token}})
    message = rejection_message(response, config)
    assert config.llm_api_key not in message and config.owner_token not in message
    assert "[redacted]" in message
    assert "HTTP 403" in rejection_message(httpx.Response(403, text="<html>Forbidden</html>"), config)


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


def test_local_provider_omits_empty_authorization_header(monkeypatch):
    captured = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            captured.append(headers)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                    "usage": {"total_tokens": 20},
                },
            )

    monkeypatch.setattr("forge.llm.httpx.Client", Client)
    config = Settings(
        llm_provider="local",
        llm_base_url="http://127.0.0.1:8788/v1",
        llm_model="fixture",
        llm_api_key="",
        _env_file=None,
    )
    assert (
        Provider(config, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False).ask(
            "diagnostic", "Plan", {}
        )["summary"]
        == "ok"
    )
    assert captured == [{}]


@pytest.mark.parametrize("role,allowed", [("conversation", True), ("planner", False)])
def test_plain_text_is_accepted_only_for_advisory_chat(monkeypatch, role, allowed):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "I received your message."}}],
                    "usage": {"cost": 0, "total_tokens": 30},
                },
            )

    monkeypatch.setattr("forge.llm.httpx.Client", Client)
    config = Settings(
        llm_provider="local", llm_base_url="http://127.0.0.1:8788/v1", llm_model="fixture", _env_file=None
    )
    provider = Provider(config, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False)
    if allowed:
        assert provider.ask(role, "Respond", {}) == {"reply": "I received your message."}
    else:
        with pytest.raises(PolicyError, match="structured"):
            provider.ask(role, "Respond", {})
