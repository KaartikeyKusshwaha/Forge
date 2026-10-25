import json

import httpx
import pytest

from forge.config import Settings
from forge.llm import Provider
from forge.policy import PolicyError

PLAN = {
    "summary": "Add a bound",
    "steps": ["Fix and test"],
    "acceptance": ["Reject zero"],
    "files": ["pagination.py"],
    "needs_input": False,
    "question": "",
}


def transport(monkeypatch, responses, parameters=()):
    requests = []
    monkeypatch.setattr(
        "forge.llm.verify_free", lambda _: {"id": "user-selected-model", "parameters": parameters}
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            requests.append({"url": url, "headers": headers, "body": json})
            return responses[min(len(requests) - 1, len(responses) - 1)]

    monkeypatch.setattr("forge.llm.httpx.Client", Client)
    return requests


def completion(content, **choice):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, **choice}],
            "usage": {"total_tokens": 30, "cost": 0},
        },
    )


def provider(**settings):
    config = Settings(
        llm_provider="local",
        llm_base_url="http://127.0.0.1:9999/v1",
        llm_model="user-model",
        _env_file=None,
        **settings,
    )
    return Provider(config, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False)


def test_malformed_reply_is_retried_and_schema_is_still_required(monkeypatch):
    requests = transport(
        monkeypatch,
        [
            completion("I will start now."),
            completion(json.dumps({"summary": "incomplete"})),
            completion(json.dumps(PLAN)),
        ],
    )
    p = provider()
    assert p.ask("planner", "Plan", {}) == PLAN
    assert len(requests) == 3 and len(p.usage["output_recovery"]) == 2
    assert "Required JSON schema" in requests[0]["body"]["messages"][0]["content"]


def test_supported_tool_output_is_data_not_an_executed_tool(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {"name": "forge_result", "arguments": json.dumps(PLAN)},
                            }
                        ],
                    }
                }
            ],
            "usage": {"total_tokens": 30, "cost": 0},
        },
    )
    requests = transport(monkeypatch, [response], ["tools", "tool_choice"])
    assert provider().ask("planner", "Plan", {}) == PLAN
    body = requests[0]["body"]
    assert body["tool_choice"]["function"]["name"] == "forge_result"
    assert "response_format" not in body
    assert body["tools"][0]["function"]["parameters"]["properties"]["summary"]["type"] == "string"


def test_inaccurate_provider_capability_downgrades_within_budget(monkeypatch):
    requests = transport(
        monkeypatch,
        [
            httpx.Response(400, json={"error": {"message": "tools not supported"}}),
            completion(json.dumps(PLAN)),
        ],
        ["tools", "tool_choice"],
    )
    assert provider().ask("planner", "Plan", {}) == PLAN
    assert "tools" in requests[0]["body"] and "tools" not in requests[1]["body"]


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "responses"])
def test_other_users_protocols_recover_from_bad_then_valid_output(monkeypatch, protocol):
    def envelope(text):
        if protocol == "anthropic":
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})
        if protocol == "responses":
            return httpx.Response(
                200,
                json={"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]},
            )
        return completion(text)

    requests = transport(monkeypatch, [envelope("not JSON"), envelope(json.dumps(PLAN))])
    assert provider(llm_protocol=protocol).ask("planner", "Plan", {}) == PLAN
    assert len(requests) == 2


def test_truncated_reply_is_not_treated_as_a_complete_result(monkeypatch):
    requests = transport(
        monkeypatch, [completion(json.dumps(PLAN), finish_reason="length"), completion(json.dumps(PLAN))]
    )
    assert provider().ask("planner", "Plan", {}) == PLAN
    assert len(requests) == 2


def test_authentication_denial_does_not_trigger_format_retries(monkeypatch):
    requests = transport(monkeypatch, [httpx.Response(403, json={"error": {"message": "Access denied"}})])
    with pytest.raises(PolicyError, match="403"):
        provider().ask("planner", "Plan", {})
    assert len(requests) == 1


def test_output_recovery_cannot_exceed_call_budget(monkeypatch):
    requests = transport(monkeypatch, [completion("bad JSON")])
    with pytest.raises(PolicyError, match="budget"):
        provider(max_calls=1).ask("planner", "Plan", {})
    assert len(requests) == 1


def test_optional_null_question_does_not_require_another_call(monkeypatch):
    requests = transport(monkeypatch, [completion(json.dumps({**PLAN, "question": None}))])
    assert provider().ask("planner", "Plan", {}) == PLAN
    assert len(requests) == 1


def test_rejected_capability_request_does_not_invent_a_full_prompt_token_charge(monkeypatch):
    requests = transport(
        monkeypatch,
        [
            httpx.Response(400, json={"error": {"message": "tools not supported"}}),
            completion(json.dumps(PLAN)),
        ],
        ["tools", "tool_choice"],
    )
    p = provider(max_tokens=100000)
    assert p.ask("planner", "Plan", {"large_context": "x" * 79000}) == PLAN
    assert len(requests) == 2 and p.usage["tokens"] == 30


def test_unindexed_planner_paths_are_corrected_before_worker_execution(monkeypatch):
    requests = transport(
        monkeypatch,
        [completion(json.dumps({**PLAN, "files": ["invented.py"]})), completion(json.dumps(PLAN))],
    )
    assert provider().ask("planner", "Plan", {"available_paths": ["pagination.py"]}) == PLAN
    assert len(requests) == 2


def test_unlimited_permission_does_not_apply_a_forge_token_or_call_cap(monkeypatch):
    requests = transport(monkeypatch, [completion(json.dumps(PLAN))])
    p = provider(model_usage_mode="unlimited", max_calls=0, max_tokens=0)
    assert p.ask("planner", "Plan", {}) == PLAN
    assert len(requests) == 1


def test_provider_specific_token_parameter_is_corrected_without_raising_limit(monkeypatch):
    requests = transport(
        monkeypatch,
        [
            httpx.Response(
                400,
                json={"error": {"message": "max_tokens is unsupported. Use max_completion_tokens instead."}},
            ),
            completion(json.dumps(PLAN)),
        ],
    )
    p = provider()
    assert p.ask("planner", "Plan", {}) == PLAN
    assert "max_tokens" in requests[0]["body"]
    assert "max_tokens" not in requests[1]["body"]
    assert requests[1]["body"]["max_completion_tokens"] == requests[0]["body"]["max_tokens"]
