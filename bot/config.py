"""Runtime configuration via pydantic-settings v2.

Reads from `.env` locally and environment variables in production. Secrets
typed as `SecretStr` to keep them out of logs and repr by default. See the
`.env.example` at the repo root for the full key list and per-key purpose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: SecretStr
    owner_telegram_chat_id: int
    telegram_webhook_secret: SecretStr = SecretStr("")

    # n8n integration
    n8n_webhook_url: str
    n8n_webhook_secret: SecretStr
    callback_token: SecretStr
    callback_base_url: str = "http://localhost:8080"

    # Google
    google_service_account_path: Path = Path("./bot/secrets/credentials.json")
    google_sheet_id: str
    archive_folder_id: str

    # Mode / web server
    mode: Literal["polling", "webhook"] = "polling"
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    webhook_base_url: str = "https://example.com"

    # Logging
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
