import json

import httpx
import pytest

from forge.device_setup import DeviceSetup
from forge.integrations import endpoint_base, parse_example, redacted_example, validate_remote
from forge.policy import PolicyError


@pytest.mark.parametrize(
    "url",
    [
        "https://api.deepseek.com/v1",
        "https://api.together.xyz/v1",
        "https://api.fireworks.ai/inference/v1",
        "https://api.cerebras.ai/v1",
        "https://api.sambanova.ai/v1",
        "https://api.mistral.ai/v1",
        "https://api.moonshot.ai/v1",
        "https://api.siliconflow.cn/v1",
        "https://api.x.ai/v1",
        "https://api.deepinfra.com/v1/openai",
        "https://api.minimax.io/v1",
        "https://open.bigmodel.cn/api/paas/v4",
    ],
)
def test_examples_from_compatible_providers_parse_without_llm(url, monkeypatch):
    monkeypatch.setattr("forge.llm.Provider.ask", lambda *_: pytest.fail("No model is required for setup"))
    code = f'from openai import OpenAI\nclient = OpenAI(base_url="{url}", api_key="opaque-fixture-secret")\nclient.chat.completions.create(model="test-coder", messages=[])'
    parsed = parse_example(code=code)
    assert parsed["endpoint"] == url
    assert parsed["key"] == "opaque-fixture-secret"
    assert parsed["model"] == "test-coder" and parsed["protocol"] == "openai"


def test_native_provider_formats_and_opaque_key():
    assert parse_example("sk-ant-fixture-only")["protocol"] == "anthropic"
    assert (
        parse_example("AIzaFixtureOnly")["endpoint"]
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert parse_example("nvapi-fixture-only")["endpoint"] == "https://integrate.api.nvidia.com/v1"
    assert parse_example("opaque-fixture-only")["needs"] == "endpoint"
    code = 'const client = new OpenAI({apiKey: "opaque-fixture", baseURL: "https://example.com/v1"}); client.responses.create({model: "test-model"})'
    assert parse_example(code=code)["protocol"] == "responses"


def test_missing_environment_can_be_supplied_at_connection_time(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EXAMPLE_API_KEY", raising=False)
    code = 'client = OpenAI(api_key=os.getenv("EXAMPLE_API_KEY"), base_url="https://example.com/v1")'
    missing = parse_example(code=code)
    assert missing["needs"] == "environment" and missing["variables"] == ["EXAMPLE_API_KEY"]
    parsed = parse_example(code=code, supplied={"EXAMPLE_API_KEY": "opaque-fixture-secret"})
    assert parsed["key"] == "opaque-fixture-secret"


@pytest.mark.parametrize(
    "code",
    [
        '{"api_key":"opaque-json-secret","base_url":"https://example.com/v1","model":"coder"}',
        'curl https://example.com/v1/messages -H "x-api-key: opaque-json-secret"',
        'curl https://generativelanguage.googleapis.com/v1beta/openai/models -H "x-goog-api-key: opaque-json-secret"',
    ],
)
def test_json_and_native_auth_headers_extract_key(code):
    assert parse_example(code=code)["key"] == "opaque-json-secret"


def test_saved_environment_credentials_are_scoped_to_endpoint(monkeypatch, tmp_path, setup):
    config, _, client = setup
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHARED_API_KEY", raising=False)
    requests = []
    monkeypatch.setattr("forge.integrations.validate_remote", lambda value: value)

    def get(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{"id": "coder"}]})

    monkeypatch.setattr("forge.integrations.httpx.get", get)
    body = {
        "command": 'client=OpenAI(base_url="https://first.example/v1",api_key=os.getenv("SHARED_API_KEY"))',
        "environment_values": {"SHARED_API_KEY": "first-provider-secret"},
        "endpoint_consent": True,
        "billing_guard_confirmed": True,
    }
    assert "profiles" in client.post("/api/model-profiles", json=body).json()
    body["environment_values"] = {}
    assert "profiles" in client.post("/api/model-profiles", json=body).json()
    calls = len(requests)
    body["command"] = body["command"].replace("first.example", "second.example")
    response = client.post("/api/model-profiles", json=body)
    assert response.json()["setup"]["needs"] == "environment"
    assert len(requests) == calls
    assert "first-provider-secret" not in response.text


def test_connection_setup_requires_destination_and_billing_consent(monkeypatch, setup):
    config, _, client = setup
    requests = []
    monkeypatch.setattr("forge.integrations.validate_remote", lambda value: value)

    def get(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{"id": "test-coder"}]})

    monkeypatch.setattr("forge.integrations.httpx.get", get)
    body = {"api_key": "opaque-fixture-secret", "endpoint": "https://example.com/v1"}
    first = client.post("/api/model-profiles", json=body).json()
    assert first["setup"]["needs"] == "endpoint_consent" and not requests
    body["endpoint_consent"] = True
    second = client.post("/api/model-profiles", json=body).json()
    assert second["profiles"][0]["mode"] == "free_only"
    response = client.post("/api/model-profiles", json=body)
    assert response.status_code == 200, response.text
    assert config.llm_provider == "compatible" and config.llm_model == "test-coder"
    assert "opaque-fixture-secret" not in response.text


def test_environment_setup_is_saved_to_private_profile_not_global_shell(monkeypatch, tmp_path, setup):
    from forge.models import load_profiles

    config, _, client = setup
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    monkeypatch.setattr("forge.integrations.validate_remote", lambda value: value)
    monkeypatch.setattr(
        "forge.integrations.httpx.get",
        lambda url, **kwargs: httpx.Response(
            200, request=httpx.Request("GET", url), json={"data": [{"id": "test"}]}
        ),
    )
    body = {
        "command": 'client = OpenAI(base_url="https://example.com/v1", api_key=os.getenv("CUSTOM_API_KEY"))',
        "environment_values": {"CUSTOM_API_KEY": "opaque-fixture"},
        "endpoint_consent": True,
        "billing_guard_confirmed": True,
    }
    assert client.post("/api/model-profiles", json=body).status_code == 200
    assert not (tmp_path / ".env").exists()
    assert load_profiles(config.model_copy(update={"llm_api_key": ""})).llm_api_key == "opaque-fixture"


def test_helper_redaction_removes_keys_and_url_tokens():
    code = 'client=OpenAI(api_key="opaque-secret", base_url="https://example.com/v1/opaque-secret?key=another-secret")\nmodel="opaque-secret"'
    text = json.dumps(redacted_example(code))
    assert "opaque-secret" not in text and "another-secret" not in text


def test_external_endpoints_cannot_resolve_to_private_networks(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *_args, **_kwargs: [(2, 1, 6, "", ("192.168.1.1", 443))])
    with pytest.raises(PolicyError, match="public addresses"):
        validate_remote("https://example.com/v1")
    with pytest.raises(PolicyError):
        endpoint_base("https://user:secret@example.com/v1")


def test_local_runtime_setup_requires_consent_and_never_executes_arbitrary_actions(monkeypatch):
    setup = DeviceSetup()
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: pytest.fail("No command may run"))
    with pytest.raises(PolicyError, match="Approve"):
        setup.start("install_ollama", False)
    with pytest.raises(PolicyError, match="Unsupported"):
        setup.start("powershell evil", True)


def test_approved_runtime_action_uses_fixed_arguments_and_strips_keys(monkeypatch):
    import time

    device = DeviceSetup()
    monkeypatch.setattr(device, "executable", lambda: "fixture-ollama")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_must_not_reach_installer")
    captured = []

    def run(command, **kwargs):
        captured.append((command, kwargs))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", run)
    device.start("pull_model", True, "qwen2.5-coder:7b")
    deadline = time.monotonic() + 3
    while not captured and time.monotonic() < deadline:
        time.sleep(0.01)
    assert captured[0][0] == ["fixture-ollama", "pull", "qwen2.5-coder:7b"]
    assert "GROQ_API_KEY" not in captured[0][1]["env"]
    with pytest.raises(PolicyError):
        device.start("pull_model", True, "model; powershell evil")


@pytest.mark.parametrize("protocol", ["anthropic", "responses"])
def test_native_text_adapters_send_correct_auth_and_read_output(monkeypatch, protocol):
    from forge.config import Settings
    from forge.llm import Provider

    monkeypatch.setattr("forge.llm.verify_free", lambda _: {"id": "fixture", "parameters": []})
    requests = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            requests.append((url, kwargs))
            data = (
                {"content": [{"type": "text", "text": '{"summary":"ok"}'}]}
                if protocol == "anthropic"
                else {
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": '{"summary":"ok"}'}]}
                    ]
                }
            )
            return httpx.Response(200, request=httpx.Request("POST", url), json=data)

    monkeypatch.setattr("forge.llm.httpx.Client", Client)
    config = Settings(
        llm_protocol=protocol,
        llm_base_url="https://example.com/v1",
        llm_api_key="fixture-key",
        _env_file=None,
    )
    assert Provider(config, {"calls": 0, "tokens": 0}, lambda _: None, lambda: False).ask(
        "diagnostic", "Fix", {}
    ) == {"summary": "ok"}
    assert requests[0][0].endswith("/messages" if protocol == "anthropic" else "/responses")
    if protocol == "anthropic":
        assert requests[0][1]["headers"]["x-api-key"] == "fixture-key"


def test_helper_is_optional_and_per_owner(monkeypatch, setup):
    config, _, client = setup
    assert client.get("/api/setup-assistant").json()["required"] is False
    monkeypatch.setattr(
        "forge.models.discover", lambda *_: ("groq-free", [{"id": "qwen/qwen3.8-27b", "parameters": []}])
    )
    response = client.post(
        "/api/setup-assistant", json={"api_key": "gsk_fixture_only_secret", "groq_confirmed": True}
    )
    assert response.status_code == 200 and response.json()["configured"] is True
    assert config.llm_model == "auto"  # Setup helper never replaces the coding model.
    assert "gsk_fixture_only_secret" not in client.get("/api/model-profiles").text
