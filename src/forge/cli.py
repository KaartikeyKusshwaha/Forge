import argparse
import json
import os
import secrets
import threading
from pathlib import Path

import httpx
import uvicorn

from forge.api import create_app
from forge.config import Settings
from forge.llm import free_models
from forge.sandbox import DockerSandbox
from forge.setup import load_registration
from forge.store import Store
from forge.worker import serve_worker


def local_config() -> Settings:
    config = Settings()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    token_path = config.data_dir / "owner-token"
    if not config.owner_token:
        if not token_path.exists():
            token_path.write_text(secrets.token_urlsafe(40), encoding="utf-8")
            if os.name != "nt":
                token_path.chmod(0o600)
        config.owner_token = token_path.read_text(encoding="utf-8").strip()
    # Never consume OPENAI_API_KEY or another paid provider key implicitly.
    if not config.llm_api_key:
        config.llm_api_key = os.environ.get("OPENROUTER_API_KEY", "")
    return load_registration(config)


def main():
    parser = argparse.ArgumentParser(description="Forge local control plane. No standalone product website.")
    parser.add_argument("command", choices=["serve", "worker", "models", "setup", "doctor"])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--with-worker", action="store_true", help="Local development only: run the worker in a thread."
    )
    args = parser.parse_args()
    config = local_config()
    if args.command == "setup":
        print("Owner token file:", (config.data_dir / "owner-token").resolve())
        print("Load this extension folder:", Path("extension").resolve())
        print("Paste the token into the extension's Connection settings. Keep it private.")
        return
    if args.command == "models":
        print(json.dumps(free_models(), indent=2))
        return
    if args.command == "doctor":
        model_online = False
        if config.llm_provider == "local":
            try:
                from forge.llm import verify_free

                verify_free(config)
                response = httpx.get(config.llm_base_url.rstrip("/") + "/models", timeout=5)
                model_online = response.status_code == 200 and any(
                    m.get("id") == config.llm_model for m in response.json().get("data", [])
                )
            except (httpx.HTTPError, ValueError):
                pass
        print(
            json.dumps(
                {
                    "github_app_configured": config.github_ready,
                    "model_configured": config.llm_ready,
                    "model": config.llm_model,
                    "provider": config.llm_provider,
                    "local_model_online": model_online,
                    "linux_docker_available": DockerSandbox.available(),
                    "publishing_enabled": config.publish_enabled,
                    "token_file": str((config.data_dir / "owner-token").resolve()),
                    "extension": str(Path("extension").resolve()),
                    "next": "Pair the extension, complete Connect GitHub App, and verify Docker before real issue runs.",
                },
                indent=2,
            )
        )
        return
    store = Store(config.database_url)
    if args.command == "worker":
        serve_worker(config, store)
        return
    stop = threading.Event()
    if args.with_worker:
        threading.Thread(target=serve_worker, args=(config, store, stop), daemon=True).start()
    print("Forge: http://127.0.0.1:" + str(args.port))
    print("Token stored locally at", (config.data_dir / "owner-token").resolve())
    try:
        uvicorn.run(create_app(config, store), host="127.0.0.1", port=args.port, access_log=False)
    finally:
        stop.set()


if __name__ == "__main__":
    main()
