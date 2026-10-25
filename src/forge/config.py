from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGE_", env_file=".env", extra="ignore")

    data_dir: Path = Path(".forge")
    database_url: str = "sqlite:///.forge/forge.sqlite3"
    owner_token: str = Field(default="", repr=False)
    demo_enabled: bool = True
    github_app_id: str = ""
    github_private_key_path: str = ""
    github_installation_id: int = 0
    github_webhook_secret: str = Field(default="", repr=False)
    github_app_slug: str = ""
    github_auth: str = "app"
    allowed_repositories: str = ""
    # Deliberate opt-in: branch pushes can trigger privileged target CI.
    publish_enabled: bool = False
    llm_provider: str = "openrouter-free"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = "auto"
    groq_free_plan_confirmed: bool = False
    model_profile_id: str = ""
    model_usage_mode: str = "free_only"
    max_output_tokens: int = 8192
    executor: str = "github-actions"
    runner_repository: str = "KaartikeyKusshwaha/Forge"
    runner_ref: str = "main"
    runner_timeout_seconds: int = 600
    max_tokens: int = 100_000
    max_calls: int = 20
    max_run_seconds: int = 1200
    approval_ttl_seconds: int = 1800
    worker_poll_seconds: float = 1

    @property
    def github_ready(self) -> bool:
        if self.github_auth == "cli":
            return bool(self.allowed_repositories.strip() or (self.data_dir / "repositories.json").exists())
        return bool(self.github_app_id and self.github_private_key_path and self.github_installation_id)

    @property
    def llm_ready(self) -> bool:
        return bool((self.llm_api_key or self.llm_provider == "local") and self.llm_model)


def settings() -> Settings:
    return Settings()
