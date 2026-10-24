import pytest
from fastapi.testclient import TestClient

from forge.api import create_app
from forge.config import Settings
from forge.store import Store


@pytest.fixture
def setup(tmp_path):
    config = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        owner_token="test-owner-token-which-is-not-a-real-secret",
        github_webhook_secret="fixture-secret",
        llm_api_key="",
        github_app_id="",
        _env_file=None,
    )
    store = Store(config.database_url)
    with TestClient(create_app(config, store)) as client:
        client.headers["Authorization"] = "Bearer " + config.owner_token
        yield config, store, client


def create_demo(client, key="fixture-request-0001"):
    response = client.post(
        "/api/runs", json=dict(repo="forge-demo/sample-api", issue=42, mode="demo", request_key=key)
    )
    assert response.status_code == 201, response.text
    return response.json()
