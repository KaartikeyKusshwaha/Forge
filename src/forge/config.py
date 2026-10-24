from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGE_", env_file=".env", extra="ignore")

    data_dir: Path = Path(".forge")
    database_url: str = "sqlite:///.forge/forge.sqlite3"
    owner_token: str = ""
    demo_enabled: bool = True
    github_app_id: str = ""
    github_private_key_path: str = ""
    github_installation_id: int = 0
    github_webhook_secret: str = ""
    github_app_slug: str = ""
    # Deliberate opt-in: branch pushes can trigger privileged target CI.
    publish_enabled: bool = False
    llm_provider: str = "openrouter-free"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "auto"
    max_tokens: int = 100_000
    max_calls: int = 20
    max_run_seconds: int = 1200
    approval_ttl_seconds: int = 1800
    worker_poll_seconds: float = 1

    @property
    def github_ready(self) -> bool:
        return bool(self.github_app_id and self.github_private_key_path and self.github_installation_id)

    @property
    def llm_ready(self) -> bool:
        return bool((self.llm_api_key or self.llm_provider == "local") and self.llm_model)


def settings() -> Settings:
    return Settings()
