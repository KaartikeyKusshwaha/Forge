import httpx
import pytest

from forge.cloudflare import discover, endpoint
from forge.integrations import discover_compatible, parse_example
from forge.policy import PolicyError

ACCOUNT = "a" * 32


def test_cloudflare_token_requests_account_without_probing_a_provider():
    result = parse_example("cfut_fixture_not_a_real_token")
    assert result["needs"] == "environment"
    assert result["variables"] == ["CLOUDFLARE_ACCOUNT_ID"]
    result = parse_example("cfut_fixture_not_a_real_token", supplied={"CLOUDFLARE_ACCOUNT_ID": ACCOUNT})
    assert result["endpoint"] == endpoint(ACCOUNT)


def test_native_catalog_is_adapted_to_compatible_models(monkeypatch):
    requests = []

    def get(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "success": True,
                "result": [
                    {
                        "name": "@cf/zai-org/glm-4.7-flash",
                        "task": {"name": "Text Generation"},
                        "properties": [{"property_id": "function_calling", "value": "true"}],
                    },
                    {"name": "@cf/zai-org/glm-5.3", "task": {"name": "Text Generation"}, "properties": []},
                    {"name": "@cf/embedding", "task": {"name": "Text Embeddings"}, "properties": []},
                ],
            },
        )

    monkeypatch.setattr("forge.cloudflare.httpx.get", get)
    monkeypatch.setattr("forge.integrations.validate_remote", lambda value: value)
    result = discover_compatible(endpoint(ACCOUNT), "fixture-token")
    assert len(result["models"]) == 2
    assert result["models"][0]["id"] == "@cf/zai-org/glm-4.7-flash"
    assert "tools" in result["models"][0]["parameters"]
    assert result["models"][1]["requires_paid_plan"]
    assert requests[0][0].endswith("/ai/models/search")
    assert requests[0][1]["headers"] == {"Authorization": "Bearer fixture-token"}


def test_cloudflare_permission_failure_is_actionable_and_redacted(monkeypatch):
    monkeypatch.setattr("forge.cloudflare.httpx.get", lambda *a, **k: httpx.Response(403))
    with pytest.raises(PolicyError, match="Workers AI Read") as exc:
        discover(endpoint(ACCOUNT), "never-echo-this-token")
    assert "never-echo-this-token" not in str(exc.value)


def test_cloudflare_connection_uses_the_account_and_protected_vault(setup, monkeypatch):
    config, store, client = setup
    monkeypatch.setattr("forge.integrations.validate_remote", lambda value: value)
    monkeypatch.setattr(
        "forge.cloudflare.discover",
        lambda *args: {
            "provider_name": "Cloudflare Workers AI",
            "models": [
                {"id": "@cf/test-coder", "parameters": [], "requires_paid_plan": False},
                {"id": "@cf/paid-coder", "parameters": [], "requires_paid_plan": True},
            ],
        },
    )
    response = client.post(
        "/api/model-profiles",
        json={"api_key": "cfut_fixture_secret", "account_id": ACCOUNT, "endpoint_consent": True},
    )
    assert response.status_code == 200, response.text
    assert config.llm_base_url == endpoint(ACCOUNT)
    assert config.llm_model == "@cf/test-coder" and config.model_usage_mode == "free_only"
    assert len(response.json()["profiles"][0]["models"]) == 1
    assert "cfut_fixture_secret" not in response.text
